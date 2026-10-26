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
