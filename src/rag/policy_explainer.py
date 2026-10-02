"""Policy explainer (roadmap Task 3.2): answers a policy question with the corpus templates; no model writes text.

The caller passes the masked message (docs/PLAN.md, row "Datos que ven los modelos"). The explainer never decides a
dispute: the routing that sends it a turn, and keeps disputes, legal citations and distress away from it, is Task 5.1.
"""
import json
from dataclasses import dataclass
from pathlib import Path

from src.rag.bm25_retriever import BM25Retriever, Hit
from src.rag.corpus import DEFAULT_CORPUS_PATH, PolicyCorpus, load_corpus
from src.rag.gate import Band, ConfidenceGate

ABSTENTION = {
    "es": "No se encontró evidencia suficiente en la política de disputas vigente para responder su pregunta. Si quiere "
          "disputar un cargo, indíquenos cuál; para otros temas le ayudan la línea de atención o la app.",
    "pt": "Não encontramos evidência suficiente na política de contestações vigente para responder à sua pergunta. Se "
          "quiser contestar uma cobrança, indique qual; para outros assuntos, a central de atendimento ou o aplicativo podem ajudar.",
}
CLARIFY_INTRO = {"es": "¿Su pregunta es sobre alguno de estos temas?", "pt": "Sua pergunta é sobre algum destes temas?"}
# No numbers: a new question names the topic, and a bare "1" would not come back to the explainer.
CLARIFY_PICK = {"es": " Cuéntenos sobre cuál quiere saber.", "pt": " Conte sobre qual deles quer saber."}


@dataclass
class Explanation:
    action: str  # answer, redirect (an internal clause, TQ-037), clarify or abstain
    reply: str
    band: Band
    cited_clauses: list[str]
    candidates: list[str]  # the public clauses offered when the gate is ambivalent
    hits: list[Hit]  # what the retriever returned, for the audit log; it may name internal clauses


class PolicyExplainer:
    def __init__(self, corpus: PolicyCorpus, retriever: BM25Retriever, gate: ConfidenceGate, k: int = 3):
        self.corpus, self.retriever, self.gate, self.k = corpus, retriever, gate, k

    def explain(self, masked_text: str, language: str = "es") -> Explanation:
        language = "pt" if language == "pt" else "es"
        hits = self.retriever.search(masked_text, k=self.k)
        band = self.gate.band(hits[0].score) if hits else Band.LOW
        if band is Band.HIGH:
            top = self.corpus.clause(hits[0].clause_id)
            if top.is_internal:
                return Explanation("redirect", self.corpus.internal_redirect(language), band, [], [], hits)
            return Explanation("answer", f"{top.answer(language)} [{top.clause_id}]", band, [top.clause_id], [], hits)
        if band is Band.AMBIVALENT:
            public = [c for c in (self.corpus.clause(h.clause_id) for h in hits) if not c.is_internal]
            if public:
                listing = "".join(f" {c.title(language)}." for c in public)
                reply = CLARIFY_INTRO[language] + listing + CLARIFY_PICK[language]
                return Explanation("clarify", reply, band, [], [c.clause_id for c in public], hits)
        return Explanation("abstain", ABSTENTION[language], band, [], [], hits)


def load_policy_explainer(gate_path: Path, corpus_path: Path = DEFAULT_CORPUS_PATH) -> PolicyExplainer | None:
    """The explainer the app serves, or None while the gate has no calibrated thresholds (roadmap Tasks 4.1 and 5.1).
    The gate file is {"retriever": "bm25", "tau_upper": ..., "tau_lower": ...}; committing it is what turns the explainer on."""
    if not Path(gate_path).exists():
        return None
    gate = json.loads(Path(gate_path).read_text(encoding="utf-8"))
    if gate["retriever"] != BM25Retriever.name:
        raise ValueError(f"no retriever named {gate['retriever']!r}: the gate file must name bm25")
    corpus = load_corpus(corpus_path)
    return PolicyExplainer(corpus, BM25Retriever(corpus), ConfidenceGate(gate["tau_upper"], gate["tau_lower"]))
