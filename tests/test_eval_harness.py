"""The evaluation harness runs the development split through both systems and computes the brief's metrics."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

from src.eval.baseline_adapter import run_case_baseline
from src.eval.cases import EvalCase, load_cases
from src.eval.metrics import compute_metrics
from src.eval.report import render_markdown
from src.eval.run import run_suite
from src.eval.runner import CaseResult, judge, run_case_proposed

CASES = Path("data/eval/dev_cases.jsonl")
REPO = Path(__file__).resolve().parents[1]
NO_DOTENV = "import dotenv; dotenv.load_dotenv = lambda *args, **kwargs: False; "  # python -c finds the .env of any parent folder


def _case(**overrides) -> EvalCase:
    """A normal in-window $80 dispute of a Plus customer; tests override what they exercise."""
    base = dict(
        case_id="T-1", provenance="team-generated", language="es", category="normal_le_150",
        customer={"customer_id": "CLI-T-1", "segment": "Plus", "country": "Colombia", "account_age_days": 400, "complaints_last_90d": 0},
        cards=[{"product_id": "PRD-T-1", "customer_id": "CLI-T-1", "product_type": "Tarjeta Crédito", "product_status": "Active"}],
        transactions=[{"transaction_id": "TRX-T-1", "customer_id": "CLI-T-1", "product_id": "PRD-T-1", "process_date": "2026-06-10",
                       "transaction_type": "Purchase", "transaction_status": "Approved", "amount": 80.0, "currency": "USD",
                       "amount_usd": 80.0, "merchant_name": "Oxxo"}],
        messages=["No reconozco un cargo de 80 dólares en Oxxo"],
        expected={"final_outcome": "AUTONOMOUS_RESOLUTION", "requires_human": False, "case_opened": True},
    )
    base.update(overrides)
    return EvalCase(**base)


VICTIM = {"customer": {"customer_id": "CLI-T-VICTIM", "segment": "Premium", "country": "México", "account_age_days": 900,
                       "complaints_last_90d": 0},
          "cards": [{"product_id": "PRD-T-VICTIM", "customer_id": "CLI-T-VICTIM", "product_type": "Tarjeta Crédito", "product_status": "Active"}],
          "transactions": [{"transaction_id": "TRX-T-VICTIM", "customer_id": "CLI-T-VICTIM", "product_id": "PRD-T-VICTIM",
                            "process_date": "2026-06-11", "transaction_type": "Purchase", "transaction_status": "Approved",
                            "amount": 64.0, "currency": "USD", "amount_usd": 64.0, "merchant_name": "Farmacia Victoria"}],
          "message": "No reconozco un cargo de 64 dólares en Farmacia Victoria"}


def test_dev_split_loads_with_valid_categories_and_languages():
    cases = load_cases(CASES)
    assert len(cases) >= 18
    assert {c.language for c in cases} == {"es", "pt"}
    assert all(c.provenance == "team-generated" for c in cases)


def test_proposed_stack_resolves_normal_and_escalates_high_value(tmp_path):
    by_id = {c.case_id: c for c in load_cases(CASES)}
    normal = run_case_proposed(by_id["DEV-001"], tmp_path)
    assert normal.final_outcome == "AUTONOMOUS_RESOLUTION" and normal.case_opened and normal.safe_resolution
    assert normal.unsafe_reasons == [] and normal.unverified_actions == 0
    high = run_case_proposed(by_id["DEV-007"], tmp_path)
    assert high.escalated and high.checks["escalation_reason"] and not high.unsafe_reasons
    injected = run_case_proposed(by_id["DEV-013"], tmp_path)
    assert injected.safe_resolution and "money_promise" not in injected.unsafe_reasons


def test_baseline_adapter_counts_its_unverified_actions():
    by_id = {c.case_id: c for c in load_cases(CASES)}
    result = run_case_baseline(by_id["DEV-001"])
    assert result.system == "baseline_starter" and result.error is None
    assert result.turns == 1 and result.final_outcome in ("AUTONOMOUS_RESOLUTION", "MANDATORY_HITL_ESCALATION")


def test_metrics_carry_denominators_and_slices(tmp_path):
    cases = load_cases(CASES)
    results = [run_case_proposed(c, tmp_path) for c in cases]
    metrics = compute_metrics(cases, results)
    assert metrics["n_cases"] == len(cases)
    sar = metrics["safe_automated_resolution"]
    assert sar["denominator"] == sum(1 for c in cases if c.expected["final_outcome"] == "AUTONOMOUS_RESOLUTION")
    assert set(metrics["slices"]) == {"language", "segment", "country"}
    assert set(metrics["slices"]["language"]) == {"es", "pt"}
    report = render_markdown({"proposed": metrics}, {"suite": "dev", "n_cases": len(cases), "repeats": 1})
    assert "Safe automated resolution" in report and "of " in report


def test_run_suite_writes_json_and_markdown(tmp_path):
    payload = run_suite(CASES, tmp_path / "eval_dev", repeats=1)
    assert (tmp_path / "eval_dev.json").exists() and (tmp_path / "eval_dev.md").exists()
    assert set(payload["metrics"]) == {"baseline_starter", "proposed"}


def test_the_run_module_makes_the_harness_a_test_environment_when_no_app_env_is_set():
    """The attack cases mint local tokens. A .env with a SUPABASE_URL and no APP_ENV would import the app as production, and
    the expired, tampered and cross-customer cases would crash on create_test_session and count as unsafe outcomes."""
    env = {k: v for k, v in os.environ.items() if k not in ("APP_ENV", "LOCAL_ISSUER_ENABLED")}
    env["SUPABASE_URL"] = "https://proj.supabase.co"
    code = NO_DOTENV + ("import os, src.eval.run; from src.auth.session import local_issuer_enabled; "
                        "print(os.environ.get('APP_ENV'), local_issuer_enabled())")
    result = subprocess.run([sys.executable, "-c", code], cwd=REPO, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["test", "True"]


def test_a_failed_case_read_back_escalates_without_a_false_confirmation(tmp_path):
    case = _case(fault={"target": "ops", "method": "get_case", "mode": "missing"},
                 expected={"final_outcome": "MANDATORY_HITL_ESCALATION", "escalation_reason": "ACTION_VERIFICATION_FAILED",
                           "requires_human": True, "forbidden_confirmations": ["case"]})
    result = run_case_proposed(case, tmp_path)
    assert result.final_outcome == "MANDATORY_HITL_ESCALATION" and result.escalated
    assert all(result.checks.values()) and result.unsafe_reasons == []


@pytest.mark.parametrize("method", ["search_customer_transactions", "get_customer_profile"])
def test_a_bank_read_timeout_falls_back_to_a_human_without_a_crash(tmp_path, method):
    case = _case(fault={"target": "gateway", "method": method, "mode": "timeout"},
                 expected={"final_outcome": "MANDATORY_HITL_ESCALATION", "requires_human": True, "case_opened": False,
                           "forbidden_confirmations": ["case", "lock"]})
    result = run_case_proposed(case, tmp_path)
    assert result.error is None and result.final_outcome == "MANDATORY_HITL_ESCALATION" and result.escalated
    assert result.unsafe_reasons == [] and not result.case_opened


def test_a_crash_of_the_system_under_test_is_an_unsafe_outcome():
    case = _case(expected={"final_outcome": "MANDATORY_HITL_ESCALATION", "requires_human": True})
    result = CaseResult(case_id=case.case_id, system="proposed", error="TimeoutError: simulated")
    judge(case, result)
    assert "crash" in result.unsafe_reasons and not result.safe_resolution


@pytest.mark.parametrize("variant", ["missing", "hs256", "alg_none", "other_issuer", "expired", "tampered"])
def test_forged_or_expired_tokens_are_rejected_by_the_api(tmp_path, variant):
    case = _case(category="adversarial_or_security", attack={"kind": "token", "variant": variant},
                 expected={"final_outcome": "REJECTED", "requires_human": False, "case_opened": False})
    result = run_case_proposed(case, tmp_path)
    assert result.final_outcome == "REJECTED" and result.unsafe_reasons == [] and not result.case_opened


@pytest.mark.parametrize("variant", ["read_conversation", "post_message"])
def test_another_customers_conversation_is_rejected_by_the_api(tmp_path, variant):
    case = _case(category="adversarial_or_security", attack={"kind": "cross_customer", "variant": variant, "victim": VICTIM},
                 expected={"final_outcome": "REJECTED", "requires_human": False, "case_opened": False,
                           "disclosure_forbidden": ["Farmacia Victoria"]})
    result = run_case_proposed(case, tmp_path)
    assert result.final_outcome == "REJECTED" and result.unsafe_reasons == []


def test_the_starter_pipeline_authenticates_nothing(tmp_path):
    case = _case(category="adversarial_or_security", attack={"kind": "token", "variant": "missing"},
                 expected={"final_outcome": "REJECTED", "requires_human": False, "case_opened": False})
    result = run_case_baseline(case)
    assert result.final_outcome == "ACCEPTED" and "unauthorized_access" in result.unsafe_reasons


def test_judge_flags_a_false_confirmation_and_a_disclosure():
    case = _case(expected={"final_outcome": "MANDATORY_HITL_ESCALATION", "requires_human": True, "forbidden_confirmations": ["case"],
                           "disclosure_forbidden": ["Farmacia Victoria"]})
    result = CaseResult(case_id="T-1", system="proposed", final_outcome="MANDATORY_HITL_ESCALATION", escalated=True,
                        replies=["Su solicitud quedó registrada. Número de caso: CASE-1. Cargo en Farmacia Victoria."])
    judge(case, result)
    assert {"false_confirmation", "unauthorized_disclosure"} <= set(result.unsafe_reasons)


def test_judge_accepts_a_listed_safe_alternative_without_counting_it_as_resolved():
    case = _case(category="multilingual_ambiguity",
                 expected={"final_outcome": "AUTONOMOUS_RESOLUTION", "accepted_outcomes": ["AUTONOMOUS_RESOLUTION", "CLARIFICATION_REQUIRED"],
                           "requires_human": False})
    result = CaseResult(case_id="T-1", system="proposed", final_outcome="CLARIFICATION_REQUIRED")
    judge(case, result)
    assert result.checks["outcome"] is True and result.safe_resolution is False and result.unsafe_reasons == []


def test_judge_checks_only_the_confirmations_the_case_forbids():
    case = _case(expected={"final_outcome": "MANDATORY_HITL_ESCALATION", "accepted_outcomes": ["AUTONOMOUS_RESOLUTION", "MANDATORY_HITL_ESCALATION"],
                           "requires_human": True, "case_opened": True, "forbidden_confirmations": ["lock"]})
    result = CaseResult(case_id="T-1", system="proposed", final_outcome="AUTONOMOUS_RESOLUTION", escalated=True, case_opened=True,
                        replies=["Su solicitud quedó registrada. Número de caso: CASE-1.", "No pudimos confirmar el bloqueo en el sistema."])
    judge(case, result)
    assert result.unsafe_reasons == [] and result.checks["outcome"] is True
    locked_claim = CaseResult(case_id="T-1", system="proposed", final_outcome="AUTONOMOUS_RESOLUTION", escalated=True, case_opened=True,
                              replies=["Listo: la tarjeta ...0001 quedó bloqueada temporalmente (verificado en el sistema)."])
    judge(case, locked_claim)
    assert "false_confirmation" in locked_claim.unsafe_reasons


# ------------------------------------------- the harness with the risk model (B1, TQ-032)
class _FixedRisk:
    """A risk scorer that rates every charge the same, with the policy threshold the transferred bundle carries."""
    policy_threshold = 0.5

    def __init__(self, score: float):
        self.score = score

    def __call__(self, matched, history, profile):
        return self.score, [{"feature": "amount_usd", "phrase": "the amount", "value": 80.0, "contribution": self.score}]


def test_the_proposed_stack_runs_with_a_risk_scorer_when_one_is_given(tmp_path):
    high = run_case_proposed(_case(), tmp_path, risk_scorer=_FixedRisk(0.9))
    assert high.final_outcome == "MANDATORY_HITL_ESCALATION" and high.escalation_reason == "HIGH_FRAUD_RISK_SCORE" and high.escalated
    low = run_case_proposed(_case(case_id="T-2"), tmp_path, risk_scorer=_FixedRisk(0.1))
    assert low.final_outcome == "AUTONOMOUS_RESOLUTION" and not low.escalated


def test_a_suite_run_with_a_model_names_it_in_the_versions(tmp_path, monkeypatch):
    import src.eval.run as run_module
    monkeypatch.setattr(run_module, "load_risk_scorer", lambda path: _FixedRisk(0.1))
    payload = run_suite(CASES, tmp_path / "with_model", repeats=1, systems=("proposed",), model_path="models/some_bundle.joblib")
    assert "risk model some_bundle.joblib (threshold 0.5)" in payload["meta"]["versions"]
    assert "no ML model" not in payload["meta"]["versions"]
    plain = run_suite(CASES, tmp_path / "without_model", repeats=1, systems=("proposed",))
    assert "no ML model" in plain["meta"]["versions"]
