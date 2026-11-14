from __future__ import annotations

import pytest
from openai.types.chat import ChatCompletion
from openai.types.completion_usage import CompletionUsage

from app.config import Settings
from app.llm import AITunnelClient, LLMError


class FakeCompletions:
    def __init__(self, response: ChatCompletion) -> None:
        self.response = response
        self.kwargs: dict | None = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return self.response


class FakeChat:
    def __init__(self, completions: FakeCompletions) -> None:
        self.completions = completions


class FakeOpenAI:
    def __init__(self, completions: FakeCompletions) -> None:
        self.chat = FakeChat(completions)


def _response() -> ChatCompletion:
    return ChatCompletion(
        id="chatcmpl-test",
        object="chat.completion",
        created=0,
        model="gpt-4o-mini",
        choices=[
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": '{"ok": true}',
                },
            }
        ],
        usage=CompletionUsage(
            prompt_tokens=10,
            completion_tokens=5,
            total_tokens=15,
        ),
    )


def test_client_sends_json_mode_and_reads_usage(tmp_path) -> None:
    settings = Settings(
        _env_file=None,
        aitunnel_api_key="sk-test-key",
        aitunnel_model="gpt-4o-mini",
        database_path=tmp_path / "test.db",
    )
    client = AITunnelClient(settings)
    completions = FakeCompletions(_response())
    client._client = FakeOpenAI(completions)

    result = client.complete_json(
        [{"role": "user", "content": "Верни JSON"}]
    )

    assert result.content == '{"ok": true}'
    assert result.model == "gpt-4o-mini"
    assert result.usage["prompt_tokens"] == 10
    assert completions.kwargs is not None
    assert completions.kwargs["response_format"] == {"type": "json_object"}
    assert completions.kwargs["temperature"] == 0.2
    assert completions.kwargs["max_tokens"] == 800


def test_client_without_key_raises(tmp_path) -> None:
    settings = Settings(
        _env_file=None,
        aitunnel_api_key="sk-your-key-here",
        database_path=tmp_path / "test.db",
    )
    client = AITunnelClient(settings)
    with pytest.raises(LLMError):
        client.complete_json([{"role": "user", "content": "test"}])
