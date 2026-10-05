"""
Policy explainer over data/policy_corpus.json (roadmap Tasks 2.2 to 3.2): the corpus contract of TQ-037, BM25
retrieval, the confidence gate and the templated answers. The questions are team-written for these tests; the
evaluation bank of Task 1.2 is separate and never tunes them.
"""
import json
import re
import zlib
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import numpy as np
import pytest

from src.orchestrator.dispute_orchestrator import DisputeOrchestrator
from src.rag import onnx_retriever
from src.rag.bm25_retriever import BM25Retriever, Hit, tokenize
from src.rag.corpus import DEFAULT_CORPUS_PATH, load_corpus
from src.rag.gate import Band, ConfidenceGate
from src.rag.onnx_retriever import (
    DEFAULT_MODEL_DIR,
    MODEL_FILES,
    E5Retriever,
    OnnxE5Embedder,
    mean_pool,
)
from src.rag.policy_explainer import PolicyExplainer, load_policy_explainer
from src.rules.dispute_policy import DisputePolicyEngine
from src.tools.gateway import BankingToolGateway
from src.understand.jev_extractor import JevSignals, StubJev
from src.understand.keyword_extractor import KeywordIntentExtractor
from src.understand.router import UnderstandRouter

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


# ------------------------------------------------------------------ E5 retrieval (Task 2.3), on stand-in embedders
class WordEmbedder:
    """Stands in for the E5 model: each text is the unit vector of its accent-free words (crc32 buckets), so texts that
    share words point the same way. It records every text it embeds."""

    def __init__(self, dims: int = 4096):
        self.dims, self.texts = dims, []

    def embed(self, texts: list[str]) -> np.ndarray:
        self.texts += texts
        vectors = np.zeros((len(texts), self.dims))
        for row, text in enumerate(texts):
            for word in tokenize(text):
                vectors[row, zlib.crc32(word.encode()) % self.dims] += 1.0
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        return vectors / np.where(norms == 0, 1.0, norms)


class PresetEmbedder:
    """Clause i of the corpus gets the i-th unit vector; any question gets the vector given."""

    def __init__(self, question_vector):
        self.passages = [f"passage: {c.index_text}" for c in CORPUS.clauses]
        self.question_vector = np.asarray(question_vector, dtype=float)

    def embed(self, texts: list[str]) -> np.ndarray:
        identity = np.eye(len(self.passages))
        return np.array([identity[self.passages.index(t)] if t in self.passages else self.question_vector for t in texts])


def test_e5_embeds_each_clause_as_a_passage_and_the_question_as_a_query():
    embedder = WordEmbedder()
    retriever = E5Retriever(CORPUS, embedder)
    assert embedder.texts == [f"passage: {c.index_text}" for c in CORPUS.clauses]  # the text BM25 indexes too
    retriever.search("¿Cuánto tiempo tengo?", k=1)
    assert embedder.texts[-1] == "query: ¿Cuánto tiempo tengo?"


def test_e5_hits_are_the_cosine_similarities_best_first():
    ids = [c.clause_id for c in CORPUS.clauses]
    question = np.zeros(len(ids))
    question[3], question[7] = 0.6, 0.8
    hits = E5Retriever(CORPUS, PresetEmbedder(question)).search("any", k=3)
    assert E5Retriever.name == "e5"
    assert [h.clause_id for h in hits] == [ids[7], ids[3], ids[0]]  # equal scores keep the corpus order
    assert [h.score for h in hits] == pytest.approx([0.8, 0.6, 0.0])


def test_a_portuguese_question_against_the_spanish_corpus_is_answered_in_portuguese():
    explainer = PolicyExplainer(CORPUS, E5Retriever(CORPUS, WordEmbedder()), ALWAYS_CONFIDENT)
    explanation = explainer.explain("Quanto tempo tenho para contestar uma cobrança?", "pt")
    assert explanation.cited_clauses == ["POL-WIN-60"]
    assert explanation.reply == f"{CORPUS.clause('POL-WIN-60').answer('pt')} [POL-WIN-60]"


def test_mean_pool_averages_only_the_tokens_the_mask_keeps_and_returns_unit_vectors():
    hidden = np.array([[[1.0, 0.0], [3.0, 0.0], [100.0, 100.0]], [[0.0, 3.0], [0.0, 1.0], [0.0, 2.0]]])
    mask = np.array([[1, 1, 0], [1, 1, 1]])
    assert mean_pool(hidden, mask) == pytest.approx(np.array([[1.0, 0.0], [0.0, 1.0]]))


def test_the_e5_embedder_refuses_a_missing_or_changed_model_file(tmp_path):
    with pytest.raises(FileNotFoundError, match="download"):
        OnnxE5Embedder(tmp_path)
    for name in MODEL_FILES:
        (tmp_path / name).write_bytes(b"not the pinned file")
    with pytest.raises(ValueError, match="SHA-256"):
        OnnxE5Embedder(tmp_path)


def test_a_download_that_does_not_match_its_pinned_hash_is_not_kept(tmp_path, monkeypatch):
    monkeypatch.setattr(onnx_retriever.urllib.request, "urlretrieve", lambda url, path: Path(path).write_bytes(b"tampered"))
    with pytest.raises(ValueError, match="SHA-256"):
        onnx_retriever.download_model(tmp_path)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.skipif(not all((DEFAULT_MODEL_DIR / name).is_file() for name in MODEL_FILES),
                    reason="E5 model not downloaded (uv run python -m src.rag.onnx_retriever download)")
def test_the_real_e5_model_embeds_to_unit_vectors_of_384_dimensions():
    pytest.importorskip("onnxruntime")
    vectors = OnnxE5Embedder(DEFAULT_MODEL_DIR).embed(
        ["query: ¿Cuánto tiempo tengo para disputar un cargo?", f"passage: {CORPUS.clause('POL-WIN-60').index_text}"])
    assert vectors.shape == (2, 384)
    assert np.linalg.norm(vectors, axis=1) == pytest.approx([1.0, 1.0])


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


# ------------------------------------------------------------------ routing into the explainer (Task 5.1)
@pytest.mark.parametrize("message, distress_score, prior_distress, clause", [
    ("¿Qué plazo tengo? Si no responden voy a la Superintendencia", None, None, "POL-ESC-LEGAL"),
    ("Quanto tempo tenho? Vou falar com meu advogado", None, None, "POL-ESC-LEGAL"),
    ("¿Cuánto tiempo tengo? Estoy desesperado, no tengo para comer", None, None, "POL-ESC-DISTRESS"),
    ("¿Cuánto tiempo tengo? Estoy desesperado", 0.5, None, None),  # a Jev score overrides the keywords (S7)
    ("¿Cuánto tiempo tengo para disputar?", 2.0, None, "POL-ESC-DISTRESS"),
    ("¿Cuánto tiempo tengo para disputar?", None, 2.0, "POL-ESC-DISTRESS"),  # the case memory escalates too (P3)
    ("¿Cuánto tiempo tengo para disputar?", None, None, None),
])
def test_the_policy_names_a_legal_or_distress_escalation_the_message_alone_fires(message, distress_score, prior_distress, clause):
    assert DisputePolicyEngine.message_escalation(message, distress_score, prior_distress) == clause


def start(orchestrator, session):
    return orchestrator.start_conversation(session)["conversation_id"]


def explained(ops_store, conversation_id):
    return [a for a in ops_store.list_audit(conversation_id=conversation_id) if a["action"] == "POLICY_EXPLAINED"]


@pytest.fixture
def rag_orchestrator(bank_fixture_db, ops_store):
    return DisputeOrchestrator(gateway=BankingToolGateway(db_path=bank_fixture_db), ops=ops_store,
                               explainer=PolicyExplainer(CORPUS, RETRIEVER, ALWAYS_CONFIDENT))


@pytest.mark.parametrize("text, language", [
    ("¿Cuánto tiempo tengo para disputar un cargo?", "es"), ("Quanto tempo tenho para contestar uma cobrança?", "pt"),
])
def test_a_policy_question_gets_the_clause_answer_and_opens_nothing(rag_orchestrator, owner_session, ops_store, text, language):
    cid = start(rag_orchestrator, owner_session)
    turn = rag_orchestrator.handle_message(owner_session, cid, text)
    assert (turn.policy_outcome, turn.cited_clauses, turn.state) == ("POLICY_EXPLANATION", ["POL-WIN-60"], "new")
    assert turn.reply == f"{CORPUS.clause('POL-WIN-60').answer(language)} [POL-WIN-60]"
    assert ops_store.list_cases(owner_session.customer_id) == []
    [audit] = explained(ops_store, cid)
    assert audit["details"]["retriever"] == "bm25" and audit["details"]["hits"][0]["clause_id"] == "POL-WIN-60"


def test_an_unanswerable_policy_question_abstains(bank_fixture_db, ops_store, owner_session):
    strict = PolicyExplainer(CORPUS, RETRIEVER, ConfidenceGate(tau_upper=1e6, tau_lower=1e6))
    orchestrator = DisputeOrchestrator(gateway=BankingToolGateway(db_path=bank_fixture_db), ops=ops_store, explainer=strict)
    turn = orchestrator.handle_message(owner_session, start(orchestrator, owner_session), "¿Cómo funciona la disputa?")
    assert (turn.policy_outcome, turn.cited_clauses, turn.state) == ("SAFE_POLICY_ABSTENTION", [], "new")


@pytest.mark.parametrize("text", [
    "¿Qué plazo tengo? Si no me responden voy a la Superintendencia",  # POL-ESC-LEGAL
    "¿Cuánto tiempo tengo para disputar? Estoy desesperado, no tengo para comer",  # POL-ESC-DISTRESS
    "¿Cuánto tiempo tengo para el cargo de 80 dólares que no reconozco?",  # a charge with its amount
])
def test_a_legal_distress_or_charge_message_stays_in_the_dispute_flow(rag_orchestrator, owner_session, ops_store, text):
    cid = start(rag_orchestrator, owner_session)
    turn = rag_orchestrator.handle_message(owner_session, cid, text)
    assert explained(ops_store, cid) == [] and turn.policy_outcome != "POLICY_EXPLANATION"


@pytest.mark.parametrize("first, state", [
    ("No reconozco un cargo", "awaiting_clarification"), ("Me robaron la tarjeta", "awaiting_lock_confirmation"),
])
def test_a_policy_question_while_a_charge_or_a_lock_is_pending_stays_in_the_dispute_flow(rag_orchestrator, owner_session,
                                                                                        ops_store, first, state):
    cid = start(rag_orchestrator, owner_session)
    assert rag_orchestrator.handle_message(owner_session, cid, first).state == state
    rag_orchestrator.handle_message(owner_session, cid, "¿Cuánto tiempo tengo para disputar un cargo?")
    assert explained(ops_store, cid) == []


@pytest.mark.parametrize("signals", [
    JevSignals(intent="tarjeta_robada", intent_confidence=0.9, stolen_card_probability=0.85, distress_score=0.2),
    JevSignals(intent="fuera_de_alcance", intent_confidence=0.9, stolen_card_probability=0.0, distress_score=0.0,
               out_of_scope_category="prestamo_o_credito"),
])
def test_a_policy_question_jev_reads_as_a_stolen_card_or_another_product_stays_in_the_dispute_flow(
        bank_fixture_db, ops_store, owner_session, signals):
    text = "¿Qué pasa si me roban la tarjeta?"
    assert KeywordIntentExtractor().extract(text).policy_question  # the keywords alone would send it to the explainer
    orchestrator = DisputeOrchestrator(gateway=BankingToolGateway(db_path=bank_fixture_db), ops=ops_store,
                                       router=UnderstandRouter(jev=StubJev(answers={text: signals})),
                                       explainer=PolicyExplainer(CORPUS, RETRIEVER, ALWAYS_CONFIDENT))
    cid = start(orchestrator, owner_session)
    orchestrator.handle_message(owner_session, cid, text)
    assert explained(ops_store, cid) == []


def test_without_calibrated_thresholds_a_policy_question_takes_the_dispute_flow(orchestrator, owner_session, ops_store):
    cid = start(orchestrator, owner_session)
    turn = orchestrator.handle_message(owner_session, cid, "¿Cuánto tiempo tengo para disputar un cargo?")
    assert explained(ops_store, cid) == [] and turn.policy_outcome != "POLICY_EXPLANATION"


def test_the_app_serves_no_explainer_until_the_gate_is_calibrated(tmp_path):
    assert load_policy_explainer(tmp_path / "rag_gate.json") is None


def test_a_calibrated_gate_file_turns_the_explainer_on(tmp_path):
    gate = tmp_path / "rag_gate.json"
    gate.write_text(json.dumps({"retriever": "bm25", "tau_upper": 4.0, "tau_lower": 1.5}), encoding="utf-8")
    explainer = load_policy_explainer(gate)
    assert (explainer.gate.tau_upper, explainer.gate.tau_lower, explainer.retriever.name) == (4.0, 1.5, "bm25")


def test_a_gate_file_for_an_unknown_retriever_is_refused(tmp_path):
    gate = tmp_path / "rag_gate.json"
    gate.write_text(json.dumps({"retriever": "e5", "tau_upper": 0.9, "tau_lower": 0.8}), encoding="utf-8")
    with pytest.raises(ValueError):
        load_policy_explainer(gate)


def test_a_policy_question_after_a_greeting_is_answered_and_keeps_the_listed_charges(rag_orchestrator, owner_session, ops_store):
    """A greeting lists recent charges; a rules question asked then still reaches the explainer, and the list stays pickable."""
    cid = start(rag_orchestrator, owner_session)
    greeting = rag_orchestrator.handle_message(owner_session, cid, "Hola")
    assert greeting.state == "awaiting_clarification" and greeting.candidates
    turn = rag_orchestrator.handle_message(owner_session, cid, "¿Cuántos días tengo para disputar un cargo?")
    assert (turn.policy_outcome, turn.cited_clauses, turn.state) == ("POLICY_EXPLANATION", ["POL-WIN-60"], "awaiting_clarification")
    assert ops_store.list_cases(owner_session.customer_id) == []
    option = next(i for i, c in enumerate(greeting.candidates, start=1) if c["transaction_status"] == "Approved" and c["amount_usd"] <= 150)
    picked = rag_orchestrator.handle_message(owner_session, cid, str(option))
    assert picked.case_id
    assert [c["transaction_id"] for c in ops_store.list_cases(owner_session.customer_id)] == [greeting.candidates[option - 1]["transaction_id"]]


# Two behaviors read from the code on 4-Oct and reproduced on 5-Oct. Each test states the behavior the customer needs; it is an
# expected failure until the team decides the fix (TQ-041, TQ-042), and strict, so the fix has to remove the mark.
@pytest.mark.xfail(strict=True, reason="TQ-041: an answered rules question that names 'un cargo' counts as an earlier dispute, "
                                       "so the next rules question takes the dispute flow and a third one reaches a human")
def test_rules_questions_after_a_greeting_keep_reaching_the_explainer_and_never_a_human(rag_orchestrator, owner_session, ops_store):
    cid = start(rag_orchestrator, owner_session)
    rag_orchestrator.handle_message(owner_session, cid, "Hola")
    first = rag_orchestrator.handle_message(owner_session, cid, "¿Cuántos días tengo para disputar un cargo?")
    assert first.policy_outcome == "POLICY_EXPLANATION"
    second = rag_orchestrator.handle_message(owner_session, cid, "¿Qué tipo de movimientos puedo disputar?")
    third = rag_orchestrator.handle_message(owner_session, cid, "¿Y cuánto tarda la respuesta?")
    assert [h for h in ops_store.list_handoffs() if h["conversation_id"] == cid] == []
    assert second.policy_outcome == "POLICY_EXPLANATION" and third.policy_outcome == "POLICY_EXPLANATION"


@pytest.mark.xfail(strict=True, reason="TQ-042: the conversation language is fixed by the first message, so a customer who greets in "
                                       "Spanish and then writes in Portuguese is answered in Spanish")
def test_a_customer_who_switches_to_portuguese_after_the_first_message_is_answered_in_portuguese(rag_orchestrator, owner_session):
    cid = start(rag_orchestrator, owner_session)
    assert rag_orchestrator.handle_message(owner_session, cid, "Hola").language == "es"
    turn = rag_orchestrator.handle_message(owner_session, cid, "Olá, não reconheço uma cobrança de 120 dólares no Cine Premium")
    assert turn.case_id  # the dispute itself is understood and the case opens
    assert turn.language == "pt"
