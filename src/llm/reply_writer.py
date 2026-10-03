"""Claude Haiku drafts the prose of clarifications and escalations (docs/specs/claude-replies-v1.md, section 3.3).

The writer sends the customer's masked message and the prose with its data swapped for tokens (src/llm/reply_guard.py)
and returns the draft; the caller restores the values or answers the template. It never sees a bank record. The SDK is
imported on the first call, as JevExtractor does with its own, so a deployment without a key never loads it.
"""
from __future__ import annotations

import hashlib
import html
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.llm.budget import LlmBudget
from src.understand.router import CLAUDE_MODEL, CLAUDE_REPLY_ESTIMATE_USD

PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "reply_v1.md"
MAX_TOKENS = 400
TIMEOUT_S = 5.0
MAX_MESSAGE_CHARS = 1000
TOKEN_SYNTAX = str.maketrans({"⟦": "[", "⟧": "]"})  # the customer cannot write a token of the prose
INPUT_USD_PER_MILLION_TOKENS = 1.0  # Claude Haiku 4.5 (claude-api skill, models cached 2026-09-25)
OUTPUT_USD_PER_MILLION_TOKENS = 5.0
LANGUAGE_NAMES = {"es": "Spanish", "pt": "Portuguese"}


class WriterUnavailable(RuntimeError):
    """No usable draft this turn (no answer, an API error, a refusal or a cut-off answer): the caller answers the template."""


@dataclass
class ReplyDraft:
    text: str
    model: str
    request_id: str | None
    tokens_in: int
    tokens_out: int
    prompt_version: str


def claude_cost_usd(tokens_in: int, tokens_out: int) -> float:
    return tokens_in / 1_000_000 * INPUT_USD_PER_MILLION_TOKENS + tokens_out / 1_000_000 * OUTPUT_USD_PER_MILLION_TOKENS


def load_prompt(path: Path = PROMPT_PATH) -> tuple[str, str]:
    """The system prompt and its version: the first 12 hex digits of the SHA-256 of its text, read as UTF-8 with universal
    newlines so a CRLF checkout and Linux give the same version."""
    text = path.read_text(encoding="utf-8")
    return text, hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


class ClaudeReplyWriter:
    def __init__(self, api_key: str, budget: LlmBudget | None = None, client: Any = None, model: str = CLAUDE_MODEL,
                 prompt_path: Path = PROMPT_PATH):
        self.api_key = api_key
        self.budget = budget
        self.model = model
        self._client = client
        self.system_prompt, self.prompt_version = load_prompt(prompt_path)

    def _get_client(self):
        if self._client is None:
            import anthropic

            # max_retries=0: the SDK would obey a 429's retry-after with no cap; draft() retries once, only without an answer
            self._client = anthropic.Anthropic(api_key=self.api_key, timeout=TIMEOUT_S, max_retries=0)
        return self._client

    def draft(self, skeleton: str, masked_message: str, language: str, conversation_id: str | None = None) -> ReplyDraft:
        if self.budget is not None:
            self.budget.check(CLAUDE_REPLY_ESTIMATE_USD)  # BudgetExceeded: the router checked before Jev spent this turn
        # SEC-04, as the gateway escapes merchant names: the customer's text cannot close <customer_message>
        message = html.escape(masked_message[:MAX_MESSAGE_CHARS], quote=False).translate(TOKEN_SYNTAX)
        user = (f"<language>{LANGUAGE_NAMES.get(language, 'Spanish')}</language>\n"
                f"<customer_message>{message}</customer_message>\n"
                f"<prose>{skeleton}</prose>")
        response = self._create(user)
        try:  # a 200 that is not a Messages object (an HTML page, a body without usage) is unusable, not a crash
            tokens_in, tokens_out = response.usage.input_tokens, response.usage.output_tokens
            stop_reason = response.stop_reason
            texts = [block.text for block in response.content if block.type == "text"]
        except (AttributeError, TypeError) as exc:
            raise WriterUnavailable(f"malformed response: {type(response).__name__}") from exc
        request_id = getattr(response, "_request_id", None)  # set only on objects that came over HTTP
        if self.budget is not None:
            self.budget.record(provider="anthropic", model=self.model, purpose="reply", tokens_in=tokens_in,
                               tokens_out=tokens_out, cost_usd=claude_cost_usd(tokens_in, tokens_out),
                               conversation_id=conversation_id, request_id=request_id)
        if stop_reason != "end_turn":
            raise WriterUnavailable(f"stop_reason {stop_reason}")
        text = "".join(texts).strip()
        return ReplyDraft(text=text, model=self.model, request_id=request_id, tokens_in=tokens_in, tokens_out=tokens_out,
                          prompt_version=self.prompt_version)

    def _create(self, user: str):
        for attempt in (1, 2):  # one retry, only when no answer came back: at most two 5-second attempts
            try:
                return self._get_client().messages.create(model=self.model, max_tokens=MAX_TOKENS, system=self.system_prompt,
                                                          messages=[{"role": "user", "content": user}])
            except Exception as exc:  # SDK errors and a missing key (TypeError) all mean: answer the template this turn
                if attempt == 1 and _no_answer(exc):
                    continue
                raise WriterUnavailable(f"{type(exc).__name__}: {str(exc)[:160]}") from exc


def _no_answer(exc: Exception) -> bool:
    """A timeout or a dropped connection: no answer came back. anthropic 1.11.0 makes APITimeoutError a subclass."""
    import anthropic

    return isinstance(exc, anthropic.APIConnectionError)


def load_reply_writer(budget: LlmBudget | None = None) -> ClaudeReplyWriter | None:
    """The writer the app serves, or None without ANTHROPIC_API_KEY: the templates answer, as before."""
    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    return ClaudeReplyWriter(api_key=api_key, budget=budget) if api_key else None
