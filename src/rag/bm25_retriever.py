"""BM25 over the policy corpus (roadmap Task 2.2): the lexical baseline of Hypothesis 5, and the engine while E5 is not deployed."""
import re
from dataclasses import dataclass

from rank_bm25 import BM25Okapi

from src.rag.corpus import PolicyCorpus
from src.understand.keyword_extractor import _strip_accents

# Spanish and Portuguese function words, without accents because tokens lose theirs before the lookup.
STOPWORDS = frozenset("""
    a al algo algun alguna alguno algunos ante como con contra cual cuales cuando de del desde donde e el ella ellas
    ellos en entre era es esa ese eso esta este esto estos fue ha han hay la las le les lo los me mi mis muy nada ni no
    nos o para pero por porque que quien se sea ser si sin sobre son su sus tambien te tu tus un una uno unos usted
    ustedes y ya yo
    ao aos as da das do dos ela ele eles em essa esse isso eu foi meu minha muito na nao nas num numa os ou pela pelo
    sem seu sua tem voce voces
""".split())


@dataclass(frozen=True)
class Hit:
    clause_id: str
    score: float


def tokenize(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+", _strip_accents(text.lower()))
    return [w for w in words if len(w) > 1 and w not in STOPWORDS]


class BM25Retriever:
    name = "bm25"

    def __init__(self, corpus: PolicyCorpus):
        self._clause_ids = [c.clause_id for c in corpus.clauses]
        self._bm25 = BM25Okapi([tokenize(c.index_text) for c in corpus.clauses])

    def search(self, text: str, k: int = 3) -> list[Hit]:
        """The k best clauses, best first; a question with no indexed word scores 0 everywhere."""
        scores = self._bm25.get_scores(tokenize(text))
        best = sorted(range(len(self._clause_ids)), key=lambda i: scores[i], reverse=True)[:k]
        return [Hit(self._clause_ids[i], float(scores[i])) for i in best]
