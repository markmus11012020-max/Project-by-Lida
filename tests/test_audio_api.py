from __future__ import annotations

import io
import wave
from pathlib import Path

from fastapi.testclient import TestClient

from app.audio import (
    AudioURLValidationError,
    DownloadedAudio,
    STTError,
    STTResult,
    STTSegment,
)
from app.config import Settings
from app.main import create_app
from app.scenarios.call_qa import QA_CRITERIA
from tests.conftest import FakeLLMClient


def _wav_bytes(seconds: float = 0.25) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as file:
        file.setnchannels(1)
        file.setsampwidth(2)
        file.setframerate(8000)
        file.writeframes(b"\x00\x00" * int(8000 * seconds))
    return buffer.getvalue()


def _call_payload() -> dict:
    findings = [
        {
            "criterion_id": criterion["id"],
            "criterion": criterion["name"],
            "status": "pass",
            "severity": criterion["severity"],
            "evidence": "цитата",
            "segment_id": "s1",
            "comment": None,
        }
        for criterion in QA_CRITERIA
    ]
    return {
        "call_type": "inbound",
        "intent": "delivery",
        "summary": "Клиент обратился по заказу.",
        "resolution": "Оператор проверил заказ.",
        "next_action": "Перезвонить клиенту.",
        "priority": "medium",
        "fields": {"order_id": "12345"},
        "sentiment": "neutral",
        "qa_score": 0,
        "qa_findings": findings,
        "confidence": "high",
        "escalate": False,
        "escalate_reason": None,
        "missing_fields": [],
    }


class FakeSTT:
    def __init__(self, result: STTResult | None = None, error: Exception | None = None):
        self.result = result or STTResult(
            text="Здравствуйте, чем помочь?",
            segments=[
                STTSegment("operator", 0, 1, "Здравствуйте, чем помочь?"),
                STTSegment("client", 1, 2, "Нужен статус заказа."),
            ],
        )
        self.error = error
        self.path: Path | None = None
        self.filename: str | None = None

    def transcribe(self, path: Path, filename: str | None = None) -> STTResult:
        self.path = Path(path)
        self.filename = filename
        if self.error is not None:
            raise self.error
        assert self.path.exists()
        return self.result


def _client(service, stt) -> TestClient:
    settings = Settings(
        _env_file=None,
        aitunnel_api_key="sk-test",
        database_path=service.db.path,
    )
    return TestClient(
        create_app(settings=settings, service=service, stt_client=stt)
    )


def test_ingest_audio_end_to_end(service_factory) -> None:
    service = service_factory(FakeLLMClient([_call_payload()]))
    stt = FakeSTT()
    client = _client(service, stt)

    response = client.post(
        "/api/v1/calls/ingest-audio",
        files={"file": ("call.wav", _wav_bytes(), "audio/wav")},
        data={"scenario": "call_qa", "source": "upload", "external_id": "ext-1"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "processed"
    assert payload["meta"]["pii_masked"] is True
    assert stt.filename == "call.wav"
    assert stt.path is not None
    assert not stt.path.exists()

    audit = service.get_audit(payload["request_id"])
    assert audit is not None
    assert audit["source"] == "upload"
    assert audit["metadata"]["external_id"] == "ext-1"
    assert audit["input_text"].startswith("Оператор: Здравствуйте")


def test_ingest_audio_rejects_bad_extension(service_factory) -> None:
    service = service_factory(FakeLLMClient([]))
    stt = FakeSTT()
    client = _client(service, stt)

    response = client.post(
        "/api/v1/calls/ingest-audio",
        files={"file": ("call.txt", b"not audio", "text/plain")},
    )

    assert response.status_code == 422
    assert stt.path is None


def test_ingest_audio_requires_stt(service_factory) -> None:
    service = service_factory(FakeLLMClient([]))
    client = TestClient(
        create_app(
            settings=Settings(
                _env_file=None,
                aitunnel_api_key="sk-test",
                database_path=service.db.path,
            ),
            service=service,
            stt_client=None,
        )
    )

    response = client.post(
        "/api/v1/calls/ingest-audio",
        files={"file": ("call.wav", _wav_bytes(), "audio/wav")},
    )

    assert response.status_code == 503


def test_ingest_audio_stt_error_returns_502(service_factory) -> None:
    service = service_factory(FakeLLMClient([]))
    stt = FakeSTT(error=STTError("stt down"))
    client = _client(service, stt)

    response = client.post(
        "/api/v1/calls/ingest-audio",
        files={"file": ("call.wav", _wav_bytes(), "audio/wav")},
    )

    assert response.status_code == 502
    assert stt.path is not None
    assert not stt.path.exists()


def test_ingest_audio_url_end_to_end(
    service_factory,
    tmp_path: Path,
    monkeypatch,
) -> None:
    service = service_factory(FakeLLMClient([_call_payload()]))
    stt = FakeSTT()
    client = _client(service, stt)

    audio_path = tmp_path / "call.wav"
    audio_path.write_bytes(_wav_bytes())
    downloaded = DownloadedAudio(
        path=audio_path,
        filename="call.wav",
        content_type="audio/wav",
        size_bytes=audio_path.stat().st_size,
    )
    monkeypatch.setattr(
        "app.main.download_audio_url",
        lambda *args, **kwargs: downloaded,
    )

    response = client.post(
        "/api/v1/calls/ingest-audio-url",
        json={
            "url": "https://example.com/call.wav",
            "scenario": "call_qa",
            "external_id": "ext-url-1",
        },
    )

    assert response.status_code == 200
    assert response.json()["meta"]["pii_masked"] is True
    assert stt.filename == "call.wav"
    assert not audio_path.exists()
    audit = service.get_audit(response.json()["request_id"])
    assert audit is not None
    assert audit["metadata"]["external_id"] == "ext-url-1"


def test_ingest_audio_url_rejects_unsafe_url(
    service_factory,
    monkeypatch,
) -> None:
    service = service_factory(FakeLLMClient([]))
    stt = FakeSTT()
    client = _client(service, stt)

    def fail(*args, **kwargs):
        raise AudioURLValidationError("Приватные IP запрещены")

    monkeypatch.setattr("app.main.download_audio_url", fail)

    response = client.post(
        "/api/v1/calls/ingest-audio-url",
        json={"url": "https://127.0.0.1/call.wav"},
    )

    assert response.status_code == 422
    assert stt.path is None
