from __future__ import annotations

import pytest
from openai.types.chat import ChatCompletion
from openai.types.completion_usage import CompletionUsage

from app.config import Settings
from app.llm import AITunnelClient, LLMError


class FakeCompletions:
    def __init__(self, responses: ChatCompletion | list[ChatCompletion]) -> None:
        self.responses = responses if isinstance(responses, list) else [responses]
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if not self.responses:
            raise AssertionError("FakeCompletions: no responses left")
        return self.responses.pop(0)


class FakeChat:
    def __init__(self, completions: FakeCompletions) -> None:
        self.completions = completions


class FakeOpenAI:
    def __init__(self, completions: FakeCompletions) -> None:
        self.chat = FakeChat(completions)


def _response(
    finish_reason: str = "stop",
    content: str = '{"ok": true}',
) -> ChatCompletion:
    return ChatCompletion(
        id="chatcmpl-test",
        object="chat.completion",
        created=0,
        model="gpt-4o-mini",
        choices=[
            {
                "index": 0,
                "finish_reason": finish_reason,
                "message": {
                    "role": "assistant",
                    "content": content,
                },
            }
        ],
        usage=CompletionUsage(
            prompt_tokens=10,
            completion_tokens=5,
            total_tokens=15,
        ),
    )


def _settings(tmp_path) -> Settings:
    return Settings(
        _env_file=None,
        aitunnel_api_key="sk-test-key",
        aitunnel_model="gpt-4o-mini",
        aitunnel_max_tokens=2500,
        database_path=tmp_path / "test.db",
    )


def test_client_sends_json_mode_and_reads_usage(tmp_path) -> None:
    client = AITunnelClient(_settings(tmp_path))
    completions = FakeCompletions(_response())
    client._client = FakeOpenAI(completions)

    result = client.complete_json(
        [{"role": "user", "content": "Верни JSON"}]
    )

    assert result.content == '{"ok": true}'
    assert result.model == "gpt-4o-mini"
    assert result.usage["prompt_tokens"] == 10
    assert len(completions.calls) == 1
    assert completions.calls[0]["response_format"] == {"type": "json_object"}
    assert completions.calls[0]["temperature"] == 0.2
    assert completions.calls[0]["max_tokens"] == 2500


def test_truncated_response_retries_with_more_tokens(tmp_path) -> None:
    client = AITunnelClient(_settings(tmp_path))
    completions = FakeCompletions(
        [
            _response(finish_reason="length", content='{"category":'),
            _response(finish_reason="stop", content='{"category": "other"}'),
        ]
    )
    client._client = FakeOpenAI(completions)

    result = client.complete_json(
        [{"role": "user", "content": "Верни JSON"}]
    )

    assert result.content == '{"category": "other"}'
    assert len(completions.calls) == 2
    assert completions.calls[0]["max_tokens"] == 2500
    assert completions.calls[1]["max_tokens"] == 5000


def test_truncated_twice_raises(tmp_path) -> None:
    client = AITunnelClient(_settings(tmp_path))
    completions = FakeCompletions(
        [
            _response(finish_reason="length", content='{"category":'),
            _response(finish_reason="length", content='{"category":'),
        ]
    )
    client._client = FakeOpenAI(completions)

    with pytest.raises(LLMError):
        client.complete_json([{"role": "user", "content": "Верни JSON"}])


def test_client_without_key_raises(tmp_path) -> None:
    settings = Settings(
        _env_file=None,
        aitunnel_api_key="sk-your-key-here",
        database_path=tmp_path / "test.db",
    )
    client = AITunnelClient(settings)
    with pytest.raises(LLMError):
        client.complete_json([{"role": "user", "content": "test"}])
