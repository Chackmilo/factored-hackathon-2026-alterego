"""Policy explainer over data/policy_corpus.json (docs/RAG_IMPLEMENTATION_ROADMAP.md): BM25 retrieval, a confidence
gate and templated answers. Not wired to the orchestrator yet (Task 5.1)."""
from src.rag.bm25_retriever import BM25Retriever, Hit
from src.rag.corpus import Clause, PolicyCorpus, load_corpus
from src.rag.gate import Band, ConfidenceGate
from src.rag.policy_explainer import Explanation, PolicyExplainer

__all__ = ["BM25Retriever", "Band", "Clause", "ConfidenceGate", "Explanation", "Hit", "PolicyCorpus", "PolicyExplainer",
           "load_corpus"]
