"""Optional LLM layer. The analyst works fully without it; this only polishes the wording of an already-computed answer.

No provider SDK is bundled. `LLM_PROVIDER=none` (the default) disables the layer. A provider is any object with
`name` and `complete(system, user) -> str`; adding a real one is a deliberate, separate decision (cost, data policy).
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


def get_provider(name: str | None = None) -> LLMProvider | None:
    """None when disabled. Raises LLMNotAvailable when a provider is requested but no adapter exists."""
    chosen = (name or os.environ.get("LLM_PROVIDER") or "none").strip().lower()
    if chosen in ("", "none"):
        return None
    raise LLMNotAvailable(
        f"LLM provider '{chosen}' has no adapter in this build, so the deterministic summary is used. "
        "See docs/ai_analyst.md for how to add one."
    )


def grounded_or_none(provider: LLMProvider, system: str, user: str, ledger: Ledger) -> tuple[str | None, list[str]]:
    """Call the provider; return (text, []) if every number is grounded, else (None, offending_numbers)."""
    text = provider.complete(system, user)
    if not isinstance(text, str) or not text.strip():
        return None, ["empty response"]
    bad = ledger.ungrounded_numbers(text)
    return (None, bad) if bad else (text.strip(), [])
