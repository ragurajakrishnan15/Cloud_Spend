"""Optional LLM layer. The analyst works fully without it; this only polishes the wording of an already-computed answer.

`LLM_PROVIDER=none` (the default) disables the layer. A provider is any object with `name` and
`complete(system, user) -> str`. Two adapters ship: `anthropic` (Claude, via the optional `anthropic` package) and `gemini`
(Google Gemini over its REST API, no extra package). Set `LLM_PROVIDER`, `LLM_API_KEY` and optionally `LLM_MODEL`. Enabling it sends the figures and small result tables for
the question to that API (never credentials or raw database access) and incurs API cost, so it is opt-in.
Whatever a provider returns is rejected unless every number in it matches the evidence ledger.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections.abc import Callable
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


DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"   # override with LLM_MODEL if your key has access to a newer model
GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


def _http_post(url: str, headers: dict[str, str], body: dict, timeout: float = 30.0) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - fixed https endpoint
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:   # report the status only: never echo the request (it carries the key header)
        raise RuntimeError(f"Gemini request failed (HTTP {exc.code})") from None
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError(f"Gemini request failed ({type(exc).__name__})") from None


class GeminiProvider:
    """Google Gemini adapter over the REST API. The key is sent in a header, never in the URL. `post` is injectable for tests."""

    name = "gemini"

    def __init__(self, api_key: str | None = None, model: str | None = None,
                 post: Callable[[str, dict[str, str], dict], dict] | None = None) -> None:
        self.model = model or os.environ.get("LLM_MODEL") or DEFAULT_GEMINI_MODEL
        key = api_key or os.environ.get("LLM_API_KEY") or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not key:
            raise LLMNotAvailable("LLM_PROVIDER=gemini needs LLM_API_KEY, so the deterministic summary is used.")
        self._key = key
        self._post = post or _http_post

    def complete(self, system: str, user: str) -> str:
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {"temperature": 0, "maxOutputTokens": 2048},
        }
        data = self._post(GEMINI_ENDPOINT.format(model=self.model),
                          {"Content-Type": "application/json", "x-goog-api-key": self._key}, body)
        cands = data.get("candidates") or []
        parts = (cands[0].get("content") or {}).get("parts", []) if cands else []
        return "".join(p.get("text", "") for p in parts)   # blocked / empty -> "" -> rejected by the grounding check


def get_provider(name: str | None = None) -> LLMProvider | None:
    """None when disabled. Raises LLMNotAvailable when a requested provider cannot be used (the caller falls back)."""
    chosen = (name or os.environ.get("LLM_PROVIDER") or "none").strip().lower()
    if chosen in ("", "none"):
        return None
    if chosen == "anthropic":
        return AnthropicProvider()
    if chosen == "gemini":
        return GeminiProvider()
    raise LLMNotAvailable(f"LLM provider '{chosen}' has no adapter in this build, so the deterministic summary is used. "
                          "Supported: none, anthropic, gemini.")


def grounded_or_none(provider: LLMProvider, system: str, user: str, ledger: Ledger) -> tuple[str | None, list[str]]:
    """Call the provider; return (text, []) if every number is grounded, else (None, offending_numbers)."""
    text = provider.complete(system, user)
    if not isinstance(text, str) or not text.strip():
        return None, ["empty response"]
    bad = ledger.ungrounded_numbers(text)
    return (None, bad) if bad else (text.strip(), [])
