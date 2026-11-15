from __future__ import annotations

import sys
import wave
from pathlib import Path

from fastapi.testclient import TestClient

from app.audio import STTResult, STTSegment
from app.config import Settings
from app.integrations import WebhookOutbox
from app.scenarios.registry import SCENARIOS
from app.service import ProcessService
from tests.conftest import FakeLLMClient
from tests.test_call_qa import _payload

CALL_CENTER_DIR = Path(__file__).resolve().parent.parent / "call-center"
sys.path.insert(0, str(CALL_CENTER_DIR))

from call_store import CallStore  # noqa: E402


def _wav(path: Path, seconds: float = 0.25) -> Path:
    with wave.open(str(path), "wb") as file:
        file.setnchannels(1)
        file.setsampwidth(2)
        file.setframerate(8000)
        file.writeframes(b"\x00\x00" * int(8000 * seconds))
    return path


class FakeSTT:
    def transcribe(self, path: Path, filename: str | None = None) -> STTResult:
        return STTResult(
            text="Здравствуйте, меня зовут Анна.",
            segments=[
                STTSegment("operator", 0, 1, "Здравствуйте, меня зовут Анна."),
                STTSegment("client", 1, 2, "Мой телефон +7 900 123-45-67."),
            ],
        )


def _store(tmp_path: Path) -> tuple[CallStore, Settings, dict]:
    settings = Settings(
        _env_file=None,
        aitunnel_api_key="sk-test",
        database_path=tmp_path / "call_center.db",
        crm_webhook_enabled=True,
        crm_outbox_path=tmp_path / "outbox.db",
    )
    store = CallStore(
        settings,
        settings.database_path,
        stt_client=FakeSTT(),
        audio_dir=tmp_path / "audio",
    )
    payload = _payload()
    payload["fields"] = {
        "client_name": "Анна",
        "contact": "+7 900 123-45-67",
        "order_id": "12345",
    }
    store.service = ProcessService(
        settings=settings,
        db=store.core_db,
        llm=FakeLLMClient([payload]),
        scenarios=SCENARIOS,
    )
    return store, settings, payload


def test_ingest_real_audio_adds_call_to_review_queue(tmp_path: Path) -> None:
    store, _settings, _payload_data = _store(tmp_path)
    audio = _wav(tmp_path / "call.wav")

    call_id = store.ingest_audio(
        audio,
        filename="call.wav",
        title="Тестовый звонок",
        external_id="ext-1",
    )

    call = store.get_call(call_id)
    assert call is not None
    assert call["source"] == "real"
    assert call["external_id"] == "ext-1"
    assert call["title"] == "Тестовый звонок"
    assert call["review_status"] == "pending"
    assert call["audio_url"] is not None
    assert call["duration_ms"] >= 200
    assert call["segments"][0]["start_ms"] == 0
    assert call["segments"][1]["start_ms"] == 1000
    assert "[PERSON_1]" in call["transcript"]
    assert "+7 900 123-45-67" not in call["transcript"]

    draft_fields = call["draft_result"]["fields"]
    assert draft_fields["client_name"] == "[PERSON_1]"
    assert draft_fields["contact"] == "[PHONE_1]"

    assert len(store.list_calls(source="real")) == 1
    assert len(store.list_calls(source="demo")) == 6


def test_confirm_real_call_enqueues_masked_crm_payload(tmp_path: Path) -> None:
    store, settings, _payload_data = _store(tmp_path)
    call_id = store.ingest_audio(
        _wav(tmp_path / "call.wav"),
        filename="call.wav",
        external_id="ext-2",
    )
    call = store.get_call(call_id)
    assert call is not None

    store.confirm_call(
        call_id,
        call["draft_result"],
        reviewer="QA",
        reason="Проверено",
    )

    outbox = WebhookOutbox(settings.crm_outbox_path)
    item = outbox.get(call["request_id"])
    assert item is not None
    payload = item["payload"]
    assert payload["client_fields"]["client_name"] == "[PERSON_1]"
    assert payload["client_fields"]["contact"] == "[PHONE_1]"
    assert "+7 900 123-45-67" not in str(payload)


def test_reset_demo_keeps_real_calls(tmp_path: Path) -> None:
    store, _settings, _payload_data = _store(tmp_path)
    call_id = store.ingest_audio(
        _wav(tmp_path / "call.wav"),
        filename="call.wav",
    )

    store.reset_demo()

    assert store.get_call(call_id) is not None
    assert len(store.list_calls(source="demo")) == 6


def test_upload_route_adds_real_call(tmp_path: Path, monkeypatch) -> None:
    store, settings, _payload_data = _store(tmp_path)
    import call_center_app

    monkeypatch.setattr(call_center_app, "store", store)
    monkeypatch.setattr(call_center_app, "settings", settings)
    client = TestClient(call_center_app.app)

    response = client.post(
        "/review/upload",
        files={
            "file": (
                "call.wav",
                _wav(tmp_path / "call.wav").read_bytes(),
                "audio/wav",
            )
        },
        data={"title": "Звонок с линии", "external_id": "ext-route"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    location = response.headers["location"]
    call_id = location.split("/calls/")[1].split("?")[0]
    call = store.get_call(call_id)
    assert call is not None
    assert call["source"] == "real"
    assert call["title"] == "Звонок с линии"
    assert call["external_id"] == "ext-route"
