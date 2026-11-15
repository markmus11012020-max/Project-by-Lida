"""Whisper-compatible Speech-to-Text client."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx


class STTError(RuntimeError):
    """Raised when the STT provider is unavailable or returns invalid data."""


@dataclass(frozen=True)
class STTSegment:
    speaker: str | None
    start: float | None
    end: float | None
    text: str


@dataclass(frozen=True)
class STTResult:
    text: str
    segments: list[STTSegment] = field(default_factory=list)
    language: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


class STTClient:
    def __init__(
        self,
        url: str,
        api_key: str = "",
        model: str = "whisper-1",
        timeout: float = 120.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.url = url
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.transport = transport

    def transcribe(
        self,
        path: Path,
        filename: str | None = None,
        language: str = "ru",
    ) -> STTResult:
        path = Path(path)
        if not self.url.strip():
            raise STTError("STT_API_URL не настроен")
        if not path.exists():
            raise STTError("Аудиофайл для распознавания не найден")

        headers = {}
        if self.api_key.strip():
            headers["Authorization"] = f"Bearer {self.api_key.strip()}"

        try:
            with httpx.Client(
                timeout=self.timeout,
                transport=self.transport,
            ) as client:
                response = client.post(
                    self.url,
                    headers=headers,
                    data={
                        "model": self.model,
                        "language": language,
                        "response_format": "verbose_json",
                    },
                    files={
                        "file": (
                            filename or path.name,
                            path.read_bytes(),
                            "application/octet-stream",
                        )
                    },
                )
        except httpx.HTTPError as exc:
            raise STTError(f"STT недоступен: {type(exc).__name__}") from exc

        if not 200 <= response.status_code < 300:
            raise STTError(
                f"STT вернул HTTP {response.status_code}: "
                f"{response.text[:300]}"
            )

        try:
            payload = response.json()
        except ValueError:
            text = response.text.strip()
            if not text:
                raise STTError("STT вернул пустой ответ")
            return STTResult(text=text)

        if not isinstance(payload, dict):
            raise STTError("STT вернул неожиданный JSON")

        text = str(payload.get("text") or payload.get("transcript") or "").strip()
        raw_segments = payload.get("segments") or []
        segments: list[STTSegment] = []
        if isinstance(raw_segments, list):
            for item in raw_segments:
                if not isinstance(item, dict):
                    continue
                segment_text = str(item.get("text") or "").strip()
                if not segment_text:
                    continue
                segments.append(
                    STTSegment(
                        speaker=_optional_string(
                            item.get("speaker")
                            or item.get("channel")
                            or item.get("role")
                        ),
                        start=_optional_float(item.get("start")),
                        end=_optional_float(item.get("end")),
                        text=segment_text,
                    )
                )

        if not text and segments:
            text = " ".join(segment.text for segment in segments)

        if not text:
            raise STTError("STT вернул пустой транскрипт")

        return STTResult(
            text=text,
            segments=segments,
            language=_optional_string(payload.get("language")),
            raw=payload,
        )


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def speaker_label(speaker: str | None) -> str:
    if speaker is None:
        return "Спикер"
    normalized = speaker.strip().lower()
    if normalized in {"0", "operator", "оператор", "agent"}:
        return "Оператор"
    if normalized in {"1", "client", "клиент", "customer"}:
        return "Клиент"
    return f"Спикер {speaker}"


def transcript_text(result: STTResult) -> str:
    """Flatten STT segments into a QA-friendly dialogue transcript."""

    if not result.segments:
        return result.text.strip()

    lines: list[str] = []
    current_speaker: str | None = None
    current_text: list[str] = []

    for segment in result.segments:
        label = speaker_label(segment.speaker)
        if label != current_speaker:
            if current_speaker is not None and current_text:
                lines.append(f"{current_speaker}: {' '.join(current_text)}")
            current_speaker = label
            current_text = [segment.text.strip()]
        else:
            current_text.append(segment.text.strip())

    if current_speaker is not None and current_text:
        lines.append(f"{current_speaker}: {' '.join(current_text)}")

    return "\n".join(lines).strip() or result.text.strip()
