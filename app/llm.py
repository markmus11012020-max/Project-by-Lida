"""AITUNNEL / OpenAI-compatible LLM client."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Protocol

from openai import (
    APIConnectionError,
    APITimeoutError,
    InternalServerError,
    OpenAI,
    OpenAIError,
    RateLimitError,
)

from app.config import Settings

logger = logging.getLogger(__name__)

TRANSIENT_ERRORS = (
    APITimeoutError,
    APIConnectionError,
    RateLimitError,
    InternalServerError,
)


class LLMError(RuntimeError):
    """Raised when the LLM request cannot be completed."""


@dataclass
class LLMResponse:
    content: str
    model: str
    usage: dict[str, Any]
    latency_ms: int


class LLMClient(Protocol):
    def complete_json(self, messages: list[dict[str, str]]) -> LLMResponse:
        """Return a JSON-mode completion for the given chat messages."""


class AITunnelClient:
    """Thin wrapper around the OpenAI SDK with two controlled retries."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client: OpenAI | None = None
        if settings.llm_configured:
            self._client = OpenAI(
                api_key=settings.aitunnel_api_key,
                base_url=settings.aitunnel_base_url,
                timeout=settings.aitunnel_timeout,
                max_retries=0,
            )

    def complete_json(self, messages: list[dict[str, str]]) -> LLMResponse:
        if self._client is None:
            raise LLMError(
                "AITUNNEL_API_KEY не настроен. Вставьте реальный ключ в .env "
                "или запускайте тесты с fake LLM."
            )

        last_error: Exception | None = None
        max_tokens = self.settings.aitunnel_max_tokens
        for attempt in range(1, 3):
            started = time.perf_counter()
            try:
                response = self._client.chat.completions.create(
                    model=self.settings.aitunnel_model,
                    messages=messages,
                    temperature=self.settings.aitunnel_temperature,
                    max_tokens=max_tokens,
                    response_format={"type": "json_object"},
                )
                latency_ms = int((time.perf_counter() - started) * 1000)
                if not response.choices:
                    raise LLMError("LLM вернул пустой список choices")

                choice = response.choices[0]
                if choice.finish_reason == "length":
                    if attempt == 1:
                        max_tokens = min(max_tokens * 2, 8000)
                        logger.warning(
                            "LLM response truncated, retrying with max_tokens=%s",
                            max_tokens,
                        )
                        continue
                    raise LLMError(
                        "Ответ LLM обрезан по лимиту max_tokens после повтора"
                    )

                content = choice.message.content or ""
                usage: dict[str, Any] = {}
                if response.usage is not None:
                    usage = response.usage.model_dump()
                    extra = getattr(response.usage, "model_extra", None)
                    if extra:
                        usage.update(extra)

                return LLMResponse(
                    content=content,
                    model=response.model or self.settings.aitunnel_model,
                    usage=usage,
                    latency_ms=latency_ms,
                )
            except TRANSIENT_ERRORS as exc:
                last_error = exc
                logger.warning(
                    "LLM transient error (attempt %s/2): %s",
                    attempt,
                    type(exc).__name__,
                )
                if attempt == 1:
                    time.sleep(1.5)
            except OpenAIError as exc:
                logger.error("LLM request failed: %s", type(exc).__name__)
                raise LLMError(f"Ошибка LLM API: {exc}") from exc
            except LLMError:
                raise

        raise LLMError(
            "LLM API недоступен после 2 попыток: "
            f"{type(last_error).__name__ if last_error else 'unknown error'}"
        )
