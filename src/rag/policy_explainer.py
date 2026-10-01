"""Policy explainer (roadmap Task 3.2): answers a policy question with the corpus templates; no model writes text.

The caller passes the masked message (docs/PLAN.md, row "Datos que ven los modelos"). The explainer never decides a
dispute: the routing that sends it a turn, and keeps disputes, legal citations and distress away from it, is Task 5.1.
"""
from dataclasses import dataclass

from src.rag.bm25_retriever import BM25Retriever, Hit
from src.rag.corpus import PolicyCorpus
from src.rag.gate import Band, ConfidenceGate

ABSTENTION = {
    "es": "No se encontró evidencia suficiente en la política de disputas vigente para responder su pregunta. Si quiere "
          "disputar un cargo, indíquenos cuál; para otros temas le ayudan la línea de atención o la app.",
    "pt": "Não encontramos evidência suficiente na política de contestações vigente para responder à sua pergunta. Se "
          "quiser contestar uma cobrança, indique qual; para outros assuntos, a central de atendimento ou o aplicativo podem ajudar.",
}
CLARIFY_INTRO = {"es": "¿Su pregunta es sobre alguno de estos temas?", "pt": "Sua pergunta é sobre algum destes temas?"}
CLARIFY_PICK = {"es": " Responda con el número del tema.", "pt": " Responda com o número do tema."}


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
                listing = "".join(f" {i}) {c.title(language)}." for i, c in enumerate(public, start=1))
                reply = CLARIFY_INTRO[language] + listing + CLARIFY_PICK[language]
                return Explanation("clarify", reply, band, [], [c.clause_id for c in public], hits)
        return Explanation("abstain", ABSTENTION[language], band, [], [], hits)
