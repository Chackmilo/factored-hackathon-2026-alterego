"""Confidence gate of the policy explainer (roadmap Task 3.1): the top score decides answer, clarification or abstention.

Thresholds are per retriever (E5 cosines sit between 0.7 and 1.0, BM25 has no fixed scale) and come only from the
development split of policy questions (Task 4.1), so there is no default.
"""
from dataclasses import dataclass
from enum import StrEnum


class Band(StrEnum):
    HIGH = "high"
    AMBIVALENT = "ambivalent"
    LOW = "low"


@dataclass(frozen=True)
class ConfidenceGate:
    tau_upper: float
    tau_lower: float

    def __post_init__(self):
        if self.tau_lower > self.tau_upper:
            raise ValueError(f"tau_lower {self.tau_lower} is above tau_upper {self.tau_upper}")

    def band(self, score: float) -> Band:
        if score >= self.tau_upper:
            return Band.HIGH
        if score >= self.tau_lower:
            return Band.AMBIVALENT
        return Band.LOW
