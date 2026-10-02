"""The policy corpus (data/policy_corpus.json): one entry per clause of policy v2.3, with the exposure TQ-037 decided."""
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_CORPUS_PATH = Path(__file__).resolve().parents[2] / "data" / "policy_corpus.json"
EXPOSURES = ("public", "public_generic", "internal")


@dataclass(frozen=True)
class Clause:
    clause_id: str
    exposure: str
    title_es: str
    title_pt: str
    category: str
    official_text_es: str
    answer_es: str | None
    answer_pt: str | None
    keywords_es: tuple[str, ...]
    keywords_pt: tuple[str, ...]
    parameters: dict[str, Any]
    provenance: str

    @property
    def is_internal(self) -> bool:
        return self.exposure == "internal"

    @property
    def index_text(self) -> str:
        """What every retriever indexes, so the comparison of Hypothesis 5 does not depend on it (roadmap Task 1.1)."""
        return " ".join((self.official_text_es, *self.keywords_es, *self.keywords_pt))

    def title(self, language: str) -> str:
        return self.title_pt if language == "pt" else self.title_es

    def answer(self, language: str) -> str | None:
        return self.answer_pt if language == "pt" else self.answer_es


@dataclass(frozen=True)
class PolicyCorpus:
    clauses: tuple[Clause, ...]
    internal_redirect_es: str
    internal_redirect_pt: str

    def clause(self, clause_id: str) -> Clause:
        return next(c for c in self.clauses if c.clause_id == clause_id)

    def internal_redirect(self, language: str) -> str:
        return self.internal_redirect_pt if language == "pt" else self.internal_redirect_es


def load_corpus(path: Path = DEFAULT_CORPUS_PATH) -> PolicyCorpus:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    clauses = tuple(Clause(**{**entry, "keywords_es": tuple(entry["keywords_es"]), "keywords_pt": tuple(entry["keywords_pt"])})
                    for entry in data["clauses"])
    for clause in clauses:
        if clause.exposure not in EXPOSURES:
            raise ValueError(f"{clause.clause_id}: unknown exposure {clause.exposure!r}")
        if not clause.is_internal and not (clause.answer_es and clause.answer_pt):
            raise ValueError(f"{clause.clause_id}: a clause a customer can read needs answer_es and answer_pt")
    return PolicyCorpus(clauses, data["internal_redirect_es"], data["internal_redirect_pt"])
