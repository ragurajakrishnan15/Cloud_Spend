"""Optional LLM layer. The analyst works fully without it; this only polishes the wording of an already-computed answer.

`LLM_PROVIDER=none` (the default) disables the layer. A provider is any object with `name` and
`complete(system, user) -> str`. One adapter ships: `anthropic` (Claude, via the optional `anthropic` package; set
`LLM_PROVIDER=anthropic` and `LLM_API_KEY`, optionally `LLM_MODEL`). Enabling it sends the figures and small result tables for
the question to that API (never credentials or raw database access) and incurs API cost, so it is opt-in.
Whatever a provider returns is rejected unless every number in it matches the evidence ledger.
"""

from __future__ import annotations

import os
from typing import Protocol

from cloudspend.ai.ledger import Ledger


class LLMNotAvailable(RuntimeError):
    pass


class LLMProvider(Protocol):
    name: str

    def complete(self, system: str, user: str) -> str: ...


DEFAULT_ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"   # small, low-cost model: the task is rewording computed results
MAX_OUTPUT_TOKENS = 600


class AnthropicProvider:
    """Claude adapter. `client` is injectable so tests never touch the network."""

    name = "anthropic"

    def __init__(self, api_key: str | None = None, model: str | None = None, client=None) -> None:
        self.model = model or os.environ.get("LLM_MODEL") or DEFAULT_ANTHROPIC_MODEL
        if client is None:
            key = api_key or os.environ.get("LLM_API_KEY")
            if not key:
                raise LLMNotAvailable("LLM_PROVIDER=anthropic needs LLM_API_KEY, so the deterministic summary is used.")
            try:
                import anthropic
            except ImportError as exc:
                raise LLMNotAvailable("The 'anthropic' package is not installed (pip install anthropic), so the "
                                      "deterministic summary is used.") from exc
            client = anthropic.Anthropic(api_key=key, max_retries=1, timeout=30.0)
        self._client = client

    def complete(self, system: str, user: str) -> str:
        msg = self._client.messages.create(model=self.model, max_tokens=MAX_OUTPUT_TOKENS, temperature=0,
                                           system=system, messages=[{"role": "user", "content": user}])
        return "".join(getattr(b, "text", "") for b in msg.content)


def get_provider(name: str | None = None) -> LLMProvider | None:
    """None when disabled. Raises LLMNotAvailable when a requested provider cannot be used (the caller falls back)."""
    chosen = (name or os.environ.get("LLM_PROVIDER") or "none").strip().lower()
    if chosen in ("", "none"):
        return None
    if chosen == "anthropic":
        return AnthropicProvider()
    raise LLMNotAvailable(f"LLM provider '{chosen}' has no adapter in this build, so the deterministic summary is used. "
                          "Supported: none, anthropic.")


def grounded_or_none(provider: LLMProvider, system: str, user: str, ledger: Ledger) -> tuple[str | None, list[str]]:
    """Call the provider; return (text, []) if every number is grounded, else (None, offending_numbers)."""
    text = provider.complete(system, user)
    if not isinstance(text, str) or not text.strip():
        return None, ["empty response"]
    bad = ledger.ungrounded_numbers(text)
    return (None, bad) if bad else (text.strip(), [])
