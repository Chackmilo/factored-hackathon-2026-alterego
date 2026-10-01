"""
Policy explainer over data/policy_corpus.json (roadmap Tasks 2.2 to 3.2): the corpus contract of TQ-037, BM25
retrieval, the confidence gate and the templated answers. The questions are team-written for these tests; the
evaluation bank of Task 1.2 is separate and never tunes them.
"""
import json
import re
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

from src.rag.bm25_retriever import BM25Retriever, Hit
from src.rag.corpus import DEFAULT_CORPUS_PATH, load_corpus
from src.rag.gate import Band, ConfidenceGate
from src.rag.policy_explainer import PolicyExplainer
from src.rules.dispute_policy import DisputePolicyEngine

SPEC = Path(__file__).resolve().parents[1] / "docs" / "specs" / "dispute-policy-v2.3.md"
CORPUS = load_corpus()
RETRIEVER = BM25Retriever(CORPUS)
INTERNAL = {"POL-AUT-150", "POL-SEC-SESSION", "POL-ESC-ML-RISK"}
PUBLIC_GENERIC = {"POL-ESC-LEGAL", "POL-ESC-DISTRESS"}
ALWAYS_CONFIDENT = ConfidenceGate(tau_upper=0.0, tau_lower=0.0)


def customer_texts() -> list[str]:
    """Everything a customer can read: the redirect, and the answers and titles of the clauses that are not internal."""
    texts = [CORPUS.internal_redirect("es"), CORPUS.internal_redirect("pt")]
    for clause in CORPUS.clauses:
        if clause.exposure != "internal":
            texts += [clause.answer("es"), clause.answer("pt"), clause.title("es"), clause.title("pt")]
    return texts


class FixedRetriever:
    """Returns the same hits for any question, to put chosen clauses in front of the gate."""

    def __init__(self, hits: list[Hit]):
        self.hits = hits

    def search(self, text: str, k: int = 3) -> list[Hit]:
        return self.hits[:k]


# ------------------------------------------------------------------ corpus contract (TQ-037)
def test_the_corpus_holds_exactly_the_clauses_of_the_spec():
    spec_ids = set(re.findall(r"^\| `(POL-[A-Z0-9-]+)`", SPEC.read_text(encoding="utf-8"), re.M))
    assert len(spec_ids) == 13
    assert {c.clause_id for c in CORPUS.clauses} == spec_ids


def test_the_exposure_follows_tq_037():
    exposure = {c.clause_id: c.exposure for c in CORPUS.clauses}
    assert {cid for cid, e in exposure.items() if e == "internal"} == INTERNAL
    assert {cid for cid, e in exposure.items() if e == "public_generic"} == PUBLIC_GENERIC
    assert all(CORPUS.clause(cid).answer(lang) is None for cid in INTERNAL for lang in ("es", "pt"))


@pytest.mark.parametrize("word", [
    "crédit", "credit", "150", "180", "riesgo", "risco", "score", "sesión", "sessão", "token", "abogad", "advogad",
    "demanda", "superintend", "condusef", "procon", "bcra", "desesper", "angustia", "premium", "reembolso", "devoluc",
    "devoluç", "estorno", "pol-",
])
def test_no_customer_text_reveals_what_tq_037_keeps_internal(word):
    assert [t for t in customer_texts() if word in t.lower()] == []


def test_customer_texts_state_only_numbers_the_policy_already_tells():
    numbers = {n for t in customer_texts() for n in re.findall(r"\d+", t)}
    assert numbers <= {"3", "5", "48", "60", "500"}


def test_the_window_the_corpus_states_is_the_one_the_engine_applies(sample_dispute_input):
    clause = CORPUS.clause("POL-WIN-60")
    days = clause.parameters["window_days"]
    assert f"{days} días" in clause.answer("es") and f"{days} dias" in clause.answer("pt")
    today = sample_dispute_input.current_date
    inside = DisputePolicyEngine.evaluate(replace(sample_dispute_input, transaction_date=today - timedelta(days=days)))
    outside = DisputePolicyEngine.evaluate(replace(sample_dispute_input, transaction_date=today - timedelta(days=days + 1)))
    assert inside.escalation_reason != "OUT_OF_POLICY_WINDOW"
    assert outside.escalation_reason == "OUT_OF_POLICY_WINDOW"


def test_the_amount_the_corpus_states_is_the_one_the_engine_escalates_above(sample_dispute_input):
    clause = CORPUS.clause("POL-ESC-500")
    limit = clause.parameters["amount_usd_above"]
    assert f"{limit} USD" in clause.answer("es") and f"{limit} USD" in clause.answer("pt")
    at = DisputePolicyEngine.evaluate(replace(sample_dispute_input, amount_usd=float(limit), transaction_amount=float(limit)))
    above = DisputePolicyEngine.evaluate(replace(sample_dispute_input, amount_usd=limit + 0.01, transaction_amount=limit + 0.01))
    assert at.escalation_reason != "AMOUNT_EXCEEDS_500_USD"
    assert above.escalation_reason == "AMOUNT_EXCEEDS_500_USD"


def test_the_hours_and_reply_days_the_corpus_states_are_the_ones_the_engine_tells(sample_dispute_input):
    hours = CORPUS.clause("POL-ESC-MULTI").parameters["hours"]
    multi = DisputePolicyEngine.evaluate(replace(sample_dispute_input, recent_disputed_charges_count=3))
    for text in (multi.explanation_es, multi.explanation_pt, *(CORPUS.clause("POL-ESC-MULTI").answer(lang) for lang in ("es", "pt"))):
        assert f"{hours} horas" in text
    days = CORPUS.clause("POL-AUT-INTAKE").parameters
    span = f"{days['formal_reply_business_days_min']} a {days['formal_reply_business_days_max']}"
    intake = DisputePolicyEngine.evaluate(sample_dispute_input)
    assert f"{span} días hábiles" in intake.explanation_es and f"{span} días hábiles" in CORPUS.clause("POL-AUT-INTAKE").answer("es")
    assert f"{span} dias úteis" in intake.explanation_pt and f"{span} dias úteis" in CORPUS.clause("POL-AUT-INTAKE").answer("pt")


@pytest.mark.parametrize("field, value", [("exposure", "publik"), ("answer_pt", None)])
def test_a_malformed_corpus_entry_is_refused(tmp_path, field, value):
    data = json.loads(DEFAULT_CORPUS_PATH.read_text(encoding="utf-8"))
    public = next(c for c in data["clauses"] if c["exposure"] == "public")
    public[field] = value
    bad = tmp_path / "corpus.json"
    bad.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError):
        load_corpus(bad)


# ------------------------------------------------------------------ BM25 retrieval
@pytest.mark.parametrize("question, clause_id", [
    ("¿Cuánto tiempo tengo para disputar un cargo?", "POL-WIN-60"),
    ("¿Puedo disputar un depósito o un movimiento pendiente?", "POL-DISP-TYPE"),
    ("¿Cómo desbloqueo mi tarjeta?", "POL-AUT-LOCK"),
    ("¿Qué pasa después de registrar la disputa?", "POL-AUT-INTAKE"),
    ("Quanto tempo tenho para contestar uma cobrança?", "POL-WIN-60"),
    ("Como faço para desbloquear o cartão?", "POL-AUT-LOCK"),
])
def test_bm25_ranks_first_the_clause_the_question_is_about(question, clause_id):
    assert RETRIEVER.search(question, k=3)[0].clause_id == clause_id


@pytest.mark.parametrize("question, clause_id", [("DEPOSITO", "POL-DISP-TYPE"), ("CARTAO", "POL-AUT-LOCK")])
def test_bm25_matches_without_accents_or_case(question, clause_id):
    assert RETRIEVER.search(question, k=1)[0].clause_id == clause_id


def test_a_question_made_of_stopwords_scores_nothing():
    assert RETRIEVER.search("¿y de la que el en o para?", k=1)[0].score == 0.0


def test_bm25_returns_k_hits_best_first():
    hits = RETRIEVER.search("plazo para disputar un cargo", k=5)
    assert len(hits) == 5
    assert [h.score for h in hits] == sorted((h.score for h in hits), reverse=True)


# ------------------------------------------------------------------ confidence gate
@pytest.mark.parametrize("score, band", [
    (7.5, Band.HIGH), (5.0, Band.HIGH), (4.99, Band.AMBIVALENT), (2.0, Band.AMBIVALENT), (1.99, Band.LOW), (0.0, Band.LOW),
])
def test_the_gate_bands_the_top_score_with_inclusive_lower_bounds(score, band):
    assert ConfidenceGate(tau_upper=5.0, tau_lower=2.0).band(score) is band


def test_the_gate_refuses_a_lower_threshold_above_the_upper():
    with pytest.raises(ValueError):
        ConfidenceGate(tau_upper=1.0, tau_lower=2.0)


# ------------------------------------------------------------------ explainer
def test_a_confident_answer_is_the_clause_template_in_the_customer_language_with_its_citation():
    explainer = PolicyExplainer(CORPUS, RETRIEVER, ALWAYS_CONFIDENT)
    es = explainer.explain("¿Cuánto tiempo tengo para disputar un cargo?", language="es")
    pt = explainer.explain("Quanto tempo tenho para contestar uma cobrança?", language="pt")
    window = CORPUS.clause("POL-WIN-60")
    assert (es.action, es.reply, es.cited_clauses) == ("answer", f"{window.answer('es')} [POL-WIN-60]", ["POL-WIN-60"])
    assert (pt.action, pt.reply, pt.cited_clauses) == ("answer", f"{window.answer('pt')} [POL-WIN-60]", ["POL-WIN-60"])


def test_a_confident_hit_on_an_internal_clause_gets_the_redirect_and_cites_nothing():
    explanation = PolicyExplainer(CORPUS, RETRIEVER, ALWAYS_CONFIDENT).explain("¿Me devuelven el dinero del cargo?", language="es")
    assert explanation.hits[0].clause_id == "POL-AUT-150"  # the audit log keeps what the customer does not see
    assert explanation.band is Band.HIGH
    assert (explanation.action, explanation.reply, explanation.cited_clauses) == ("redirect", CORPUS.internal_redirect("es"), [])


def test_an_ambivalent_score_lists_only_public_clauses_to_choose_from():
    hits = [Hit("POL-AUT-150", 3.0), Hit("POL-WIN-60", 2.5), Hit("POL-DISP-TYPE", 2.0)]
    explainer = PolicyExplainer(CORPUS, FixedRetriever(hits), ConfidenceGate(tau_upper=10.0, tau_lower=1.0))
    explanation = explainer.explain("¿y el dinero?", language="pt")
    assert (explanation.action, explanation.candidates, explanation.cited_clauses) == ("clarify", ["POL-WIN-60", "POL-DISP-TYPE"], [])
    assert CORPUS.clause("POL-WIN-60").title("pt") in explanation.reply
    assert CORPUS.clause("POL-DISP-TYPE").title("pt") in explanation.reply
    assert CORPUS.clause("POL-AUT-150").title("pt") not in explanation.reply


def test_an_ambivalent_score_with_only_internal_candidates_abstains():
    hits = [Hit("POL-AUT-150", 3.0), Hit("POL-ESC-ML-RISK", 2.5)]
    explainer = PolicyExplainer(CORPUS, FixedRetriever(hits), ConfidenceGate(tau_upper=10.0, tau_lower=1.0))
    explanation = explainer.explain("¿y el dinero?", language="es")
    assert (explanation.action, explanation.candidates, explanation.cited_clauses) == ("abstain", [], [])


def test_a_low_score_abstains_in_the_customer_language():
    explainer = PolicyExplainer(CORPUS, RETRIEVER, ConfidenceGate(tau_upper=10.0, tau_lower=0.5))
    es, pt = explainer.explain("xyzzy plugh", language="es"), explainer.explain("xyzzy plugh", language="pt")
    assert es.action == pt.action == "abstain" and es.band is Band.LOW
    assert es.cited_clauses == pt.cited_clauses == []
    assert es.reply and pt.reply and es.reply != pt.reply
