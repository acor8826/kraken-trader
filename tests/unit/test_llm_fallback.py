import pytest

from integrations.llm.claude import ClaudeLLM


class _FailingMessages:
    def create(self, **kwargs):
        raise Exception("Connection timeout to Anthropic API")


class _FailingClient:
    def __init__(self):
        self.messages = _FailingMessages()


@pytest.mark.asyncio
async def test_complete_falls_back_to_codex_on_connection_failure(monkeypatch):
    llm = ClaudeLLM(api_key="")
    llm.client = _FailingClient()
    llm.codex_api_key = "test-key"

    monkeypatch.setattr(
        llm,
        "_complete_with_codex",
        lambda prompt, max_tokens=1000, system_prompt=None: "codex fallback response"
    )

    result = await llm.complete("test prompt")
    assert result == "codex fallback response"


@pytest.mark.asyncio
async def test_complete_json_falls_back_to_codex_on_connection_failure(monkeypatch):
    llm = ClaudeLLM(api_key="")
    llm.client = _FailingClient()
    llm.codex_api_key = "test-key"

    monkeypatch.setattr(
        llm,
        "_complete_with_codex",
        lambda prompt, max_tokens=1000, system_prompt=None: '{"action":"HOLD","confidence":0.5}'
    )

    result = await llm.complete_json("test prompt")
    assert result["action"] == "HOLD"
    assert result["confidence"] == 0.5
