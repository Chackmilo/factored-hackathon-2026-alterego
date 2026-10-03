"""Deterministic guard around the drafts Claude writes (docs/specs/claude-replies-v1.md, section 3.2).

protect() swaps every datum of the prose for a token before the call: ids, ISO dates, card fragments, currency codes,
amounts and any other number, and the bank values the orchestrator passes for the turn, one token per appearance.
restore() checks the draft and puts the values back, or raises GuardRejected so the caller answers the template. Claude
never sees a value it could change, every value stays where the code put it, and a reply never carries a number, id,
link or email the code did not put there, nor a promise or a confirmation that only a verified write may give.
"""
from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

MAX_CHARS = 600
TOKEN_RE = re.compile(r"⟦(\d+)⟧")
DATUM_PATTERNS = (
    r"\b(?:CASE|HO|LOCK|CLI|PRD|TRX|CONV|MSG|AUD|USE)-[A-Z0-9][A-Z0-9-]*",  # ids (src/ops/store.py _new_id, bank ids)
    r"\b\d{4}-\d{2}-\d{2}\b",  # ISO dates
    r"\.\.\.[A-Za-z0-9-]{4}",  # card fragments (the orchestrator's _card_label)
    r"\b(?:USD|COP|ARS|MXN|BRL)\b",  # currency codes
    r"\$?\d{1,3}(?:,\d{3})+(?:\.\d+)?|\$?\d+(?:\.\d+)?",  # amounts as the policy prints them, and any other number
)
FORBIDDEN_MARKS = ("@", "<", ">", "{", "}", "⟦", "⟧", "REDACTED")
LINK_RE = re.compile(r"https?://|www\.|\w[.。]\w", re.IGNORECASE)  # each token reads as a word in the scan (⟦1⟧.com is x.com); NFKC folds full-width and other compatibility dots
# What src/eval/runner.py counts as money_promise or false_confirmation, plus any lock claim: in-scope prose never says it.
UNSAFE_RE = re.compile(r"reembols|refund|devolv|devolu[cç]|estorn|cr[eé]dito (?:aplicado|provisional|provis[oó]rio)"
                       r"|n[úu]mero d[eo] caso|bloque|verificad", re.IGNORECASE)


class GuardRejected(ValueError):
    """The draft cannot be shown: the caller answers the template instead."""


def protect(prose: str, known_values: Iterable[str | None] = ()) -> tuple[str, dict[str, str]]:
    """The prose with every datum swapped for ⟦n⟧ in order of appearance, and the map from each token to its value."""
    known = sorted({v for v in known_values if isinstance(v, str) and len(v.strip()) > 1}, key=len, reverse=True)
    pattern = re.compile("|".join([re.escape(v) for v in known] + [f"(?:{p})" for p in DATUM_PATTERNS]))
    values: dict[str, str] = {}

    def swap(match: re.Match[str]) -> str:
        token = f"⟦{len(values) + 1}⟧"
        values[token] = match.group(0)
        return token

    return pattern.sub(swap, prose), values


def restore(draft: str, values: dict[str, str], skeleton: str) -> str:
    """The draft on one line with the values back, or GuardRejected naming the first rule it breaks."""
    text = " ".join(draft.split())
    if not text:
        raise GuardRejected("empty draft")
    if len(text) > max(MAX_CHARS, 2 * len(skeleton)):
        raise GuardRejected("draft too long")
    tokens = [f"⟦{n}⟧" for n in TOKEN_RE.findall(text)]
    unknown = [t for t in tokens if t not in values]
    if unknown:
        raise GuardRejected(f"unknown token {unknown[0]}")
    for token in values:
        if tokens.count(token) != 1:
            raise GuardRejected(f"token {token} appears {tokens.count(token)} times")
    if tokens != list(values):  # an amount keeps its currency, and the limit stays the limit
        raise GuardRejected("tokens out of order")
    bare = unicodedata.normalize("NFKC", TOKEN_RE.sub("x", text))  # a token reads as a word: ⟦1⟧.com is x.com
    bare = "".join(ch for ch in bare if unicodedata.category(ch) != "Cf")  # zero-width and soft hyphens hide words
    if any(ch.isdigit() for ch in bare):  # str.isdigit also catches full-width and other Unicode digits
        raise GuardRejected("digit outside tokens")
    for mark in FORBIDDEN_MARKS:
        if mark in bare:
            raise GuardRejected(f"forbidden text {mark!r}")
    if LINK_RE.search(bare):
        raise GuardRejected("link")
    if UNSAFE_RE.search(bare):
        raise GuardRejected("promise or confirmation")
    return TOKEN_RE.sub(lambda match: values[match.group(0)], text)
