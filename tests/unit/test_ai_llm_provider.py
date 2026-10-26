"""Anthropic adapter and provider selection - no network: the SDK client is faked."""

import pytest

from cloudspend.ai.llm import AnthropicProvider, LLMNotAvailable, get_provider


class _Block:
    def __init__(self, text):
        self.text = text


class _FakeClient:
    def __init__(self, text="ok"):
        self.calls = []
        self.messages = self
        self._text = text

    def create(self, **kw):
        self.calls.append(kw)
        return type("Msg", (), {"content": [_Block(self._text), object()]})()


def test_provider_sends_system_and_user_and_returns_text():
    c = _FakeClient("Spend rose.")
    p = AnthropicProvider(model="m-test", client=c)
    assert p.complete("SYS", "USER") == "Spend rose."
    call = c.calls[0]
    assert call["model"] == "m-test" and call["system"] == "SYS" and call["temperature"] == 0
    assert call["messages"] == [{"role": "user", "content": "USER"}] and call["max_tokens"] <= 1000


def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    assert get_provider() is None
    assert get_provider("none") is None


def test_anthropic_without_key_falls_back_cleanly(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    with pytest.raises(LLMNotAvailable, match="LLM_API_KEY"):
        get_provider("anthropic")


def test_unknown_provider_is_reported():
    with pytest.raises(LLMNotAvailable, match="no adapter"):
        get_provider("something-else")


def test_key_is_never_part_of_the_error_message(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "sk-secret-123")
    monkeypatch.setitem(__import__("sys").modules, "anthropic", None)   # simulate the package being absent
    with pytest.raises(LLMNotAvailable) as e:
        get_provider("anthropic")
    assert "sk-secret-123" not in str(e.value)


# ----------------------------------------------------------------------------- Gemini
def test_gemini_request_shape_and_key_in_header_only():
    from cloudspend.ai.llm import GeminiProvider
    seen = {}

    def post(url, headers, body):
        seen.update(url=url, headers=headers, body=body)
        return {"candidates": [{"content": {"parts": [{"text": "Spend "}, {"text": "rose."}]}}]}

    p = GeminiProvider(api_key="k-123", model="gemini-test", post=post)
    assert p.complete("SYS", "USER") == "Spend rose."
    assert seen["url"].endswith("/models/gemini-test:generateContent") and "k-123" not in seen["url"]
    assert seen["headers"]["x-goog-api-key"] == "k-123"
    assert seen["body"]["systemInstruction"]["parts"][0]["text"] == "SYS"
    assert seen["body"]["contents"][0]["parts"][0]["text"] == "USER" and seen["body"]["generationConfig"]["temperature"] == 0


def test_gemini_blocked_or_empty_response_returns_empty_string():
    from cloudspend.ai.llm import GeminiProvider
    assert GeminiProvider(api_key="k", post=lambda *a: {"promptFeedback": {"blockReason": "SAFETY"}}).complete("s", "u") == ""
    assert GeminiProvider(api_key="k", post=lambda *a: {"candidates": [{"finishReason": "SAFETY"}]}).complete("s", "u") == ""


def test_gemini_selected_by_name_and_needs_a_key(monkeypatch):
    for v in ("LLM_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(v, raising=False)
    with pytest.raises(LLMNotAvailable, match="LLM_API_KEY"):
        get_provider("gemini")
    monkeypatch.setenv("LLM_API_KEY", "k")
    assert get_provider("gemini").name == "gemini"


def test_gemini_http_error_does_not_leak_the_key():
    import urllib.error

    from cloudspend.ai import llm as m
    err = urllib.error.HTTPError("https://x?key=SECRET", 403, "forbidden", {}, None)
    orig = m.urllib.request.urlopen
    m.urllib.request.urlopen = lambda *a, **k: (_ for _ in ()).throw(err)
    try:
        with pytest.raises(RuntimeError) as e:
            m._http_post("https://x", {"x-goog-api-key": "SECRET"}, {})
    finally:
        m.urllib.request.urlopen = orig
    assert "403" in str(e.value) and "SECRET" not in str(e.value)


def test_a_failing_gemini_call_falls_back_to_the_deterministic_answer(bundle):
    from datetime import date

    from cloudspend.ai.analyst import answer
    from cloudspend.ai.llm import GeminiProvider
    from cloudspend.analytics.spend_metrics import Filters

    def boom(*a):
        raise RuntimeError("Gemini request failed (HTTP 429)")

    ans = answer("How much did we spend?", bundle, Filters(date(2025, 3, 1), date(2025, 3, 31)), GeminiProvider(api_key="k", post=boom))
    assert ans.mode == "deterministic" and ans.status == "ok" and ans.warnings


def test_gemini_retries_rate_limits_then_succeeds():
    import io
    import urllib.error

    from cloudspend.ai import llm as m
    calls, waits = [], []

    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=0):
        calls.append(1)
        if len(calls) < 3:
            raise urllib.error.HTTPError("u", 429, "slow down", {}, None)
        return Resp(b'{"candidates": []}')

    orig = m.urllib.request.urlopen
    m.urllib.request.urlopen = fake_urlopen
    try:
        assert m._http_post("https://x", {}, {}, sleep=waits.append) == {"candidates": []}
    finally:
        m.urllib.request.urlopen = orig
    assert len(calls) == 3 and waits == [4.0, 8.0]


def test_gemini_gives_up_after_max_attempts():
    import urllib.error

    from cloudspend.ai import llm as m
    orig = m.urllib.request.urlopen
    m.urllib.request.urlopen = lambda *a, **k: (_ for _ in ()).throw(urllib.error.HTTPError("u", 429, "x", {}, None))
    try:
        with pytest.raises(RuntimeError, match="HTTP 429"):
            m._http_post("https://x", {}, {}, sleep=lambda s: None)
    finally:
        m.urllib.request.urlopen = orig
