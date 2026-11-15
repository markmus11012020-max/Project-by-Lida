from __future__ import annotations

import json
import wave
from pathlib import Path

import httpx
import pytest

from app.audio import (
    AudioValidationError,
    STTClient,
    STTError,
    STTResult,
    STTSegment,
    transcript_text,
    validate_audio_file,
)


def _wav(path: Path, seconds: float = 0.25) -> Path:
    frames = int(8000 * seconds)
    with wave.open(str(path), "wb") as file:
        file.setnchannels(1)
        file.setsampwidth(2)
        file.setframerate(8000)
        file.writeframes(b"\x00\x00" * frames)
    return path


def test_validates_wav_and_reads_duration(tmp_path: Path) -> None:
    path = _wav(tmp_path / "call.wav")
    info = validate_audio_file(path)

    assert info.extension == ".wav"
    assert info.duration_ms >= 200
    assert info.channels == 1
    assert info.sample_rate == 8000


def test_rejects_unsupported_extension(tmp_path: Path) -> None:
    path = tmp_path / "call.txt"
    path.write_text("not audio", encoding="utf-8")

    with pytest.raises(AudioValidationError):
        validate_audio_file(path)


def test_rejects_empty_and_oversized(tmp_path: Path) -> None:
    empty = tmp_path / "empty.wav"
    empty.write_bytes(b"")
    with pytest.raises(AudioValidationError):
        validate_audio_file(empty)

    path = _wav(tmp_path / "call.wav")
    with pytest.raises(AudioValidationError):
        validate_audio_file(path, max_bytes=10)


def test_rejects_corrupt_audio(tmp_path: Path) -> None:
    path = tmp_path / "broken.mp3"
    path.write_bytes(b"not really an mp3")

    with pytest.raises(AudioValidationError):
        validate_audio_file(path)


def test_stt_success_and_transcript(tmp_path: Path) -> None:
    path = _wav(tmp_path / "call.wav")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer test-key"
        assert b'name="model"' in request.content
        return httpx.Response(
            200,
            json={
                "text": "Здравствуйте",
                "language": "ru",
                "segments": [
                    {"speaker": "operator", "start": 0, "end": 1, "text": "Здравствуйте"},
                    {"speaker": "client", "start": 1, "end": 2, "text": "Здравствуйте"},
                    {"speaker": "operator", "start": 2, "end": 3, "text": "Чем помочь?"},
                ],
            },
        )

    client = STTClient(
        "https://stt.example/v1/audio/transcriptions",
        "test-key",
        transport=httpx.MockTransport(handler),
    )
    result = client.transcribe(path)

    assert result.text == "Здравствуйте"
    assert len(result.segments) == 3
    assert transcript_text(result) == (
        "Оператор: Здравствуйте\n"
        "Клиент: Здравствуйте\n"
        "Оператор: Чем помочь?"
    )


def test_stt_http_error(tmp_path: Path) -> None:
    path = _wav(tmp_path / "call.wav")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="unavailable")

    client = STTClient(
        "https://stt.example/v1/audio/transcriptions",
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(STTError) as error:
        client.transcribe(path)
    assert "503" in str(error.value)


def test_stt_plain_text_response(tmp_path: Path) -> None:
    path = _wav(tmp_path / "call.wav")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="Просто текст")

    client = STTClient(
        "https://stt.example/v1/audio/transcriptions",
        transport=httpx.MockTransport(handler),
    )
    result = client.transcribe(path)

    assert result.text == "Просто текст"
    assert result.segments == []


def test_transcript_text_without_segments() -> None:
    result = STTResult(text="Текст без сегментов")
    assert transcript_text(result) == "Текст без сегментов"


def test_transcript_text_unknown_speaker() -> None:
    result = STTResult(
        text="x",
        segments=[STTSegment(speaker="2", start=0, end=1, text="Реплика")],
    )
    assert transcript_text(result) == "Спикер 2: Реплика"


def test_stt_missing_url(tmp_path: Path) -> None:
    path = _wav(tmp_path / "call.wav")
    with pytest.raises(STTError):
        STTClient("").transcribe(path)


def test_stt_empty_response(tmp_path: Path) -> None:
    path = _wav(tmp_path / "call.wav")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"text": ""})

    client = STTClient(
        "https://stt.example/v1/audio/transcriptions",
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(STTError):
        client.transcribe(path)
