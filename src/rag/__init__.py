"""Policy explainer over data/policy_corpus.json (docs/RAG_IMPLEMENTATION_ROADMAP.md): BM25 retrieval, a confidence
gate and templated answers, wired to the orchestrator behind data/rag_gate.json (Task 5.1). E5 (onnx_retriever) stays
out of these exports: the API imports this package, and E5 is offline until it fits the bundle (Task 2.0)."""
from src.rag.bm25_retriever import BM25Retriever, Hit
from src.rag.corpus import Clause, PolicyCorpus, load_corpus
from src.rag.gate import Band, ConfidenceGate
from src.rag.policy_explainer import Explanation, PolicyExplainer

__all__ = ["BM25Retriever", "Band", "Clause", "ConfidenceGate", "Explanation", "Hit", "PolicyCorpus", "PolicyExplainer",
           "load_corpus"]
