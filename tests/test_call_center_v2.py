from __future__ import annotations

import os
import sqlite3
import sys
import uuid
import wave
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.audio import STTResult, STTSegment
from app.config import Settings
from app.integrations import WebhookOutbox
from app.queue import create_queue
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

    duplicate = store.ingest_audio(
        audio,
        filename="call.wav",
        title="Тестовый звонок",
        external_id="ext-1",
    )
    assert duplicate == call_id

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

    final = dict(call["draft_result"])
    final["next_action"] = "Финальное действие после ревью"
    store.confirm_call(
        call_id,
        final,
        reviewer="QA",
        reason="Проверено",
    )

    outbox = WebhookOutbox(settings.crm_outbox_path)
    item = outbox.get(call["request_id"])
    assert item is not None
    payload = item["payload"]
    assert payload["next_action"] == "Финальное действие после ревью"
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


def test_old_demo_calls_table_is_migrated(tmp_path: Path) -> None:
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE demo_calls (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                client TEXT NOT NULL,
                operator TEXT NOT NULL,
                transcript_json TEXT NOT NULL,
                audio_file TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO demo_calls
            (id, title, client, operator, transcript_json, audio_file, created_at)
            VALUES ('legacy', 'Старый звонок', 'Клиент', 'Оператор', '[]', NULL, '2026-01-01')
            """
        )

    settings = Settings(
        _env_file=None,
        aitunnel_api_key="sk-test",
        database_path=path,
    )
    store = CallStore(
        settings,
        path,
        stt_client=FakeSTT(),
        audio_dir=tmp_path / "audio",
    )

    call = store.get_call("legacy")
    assert call is not None
    assert call["source"] == "demo"
    assert call["duration_ms"] == 0

    with sqlite3.connect(path) as connection:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(demo_calls)")
        }
    assert {"source", "external_id", "duration_ms"} <= columns


def test_upload_route_enqueues_when_async_enabled(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store, settings, _payload_data = _store(tmp_path)
    settings = settings.model_copy(
        update={
            "callpilot_async_upload": True,
            "callpilot_queue_url": f"sqlite:///{tmp_path / 'queue.db'}",
        }
    )
    queue = create_queue(settings.callpilot_queue_url)
    queue_dir = tmp_path / "queue" / "audio"

    import call_center_app

    monkeypatch.setattr(call_center_app, "store", store)
    monkeypatch.setattr(call_center_app, "settings", settings)
    monkeypatch.setattr(call_center_app, "QUEUE_DIR", queue_dir)
    monkeypatch.setattr(call_center_app, "_queue", queue)
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
        data={"title": "Асинхронный звонок", "external_id": "ext-async"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/dashboard?queued=1"
    assert queue.stats() == {"pending": 1}
    job = queue.dequeue("test")
    assert job is not None
    assert job.kind == "audio_ingest"
    assert job.payload["title"] == "Асинхронный звонок"
    assert job.payload["external_id"] == "ext-async"
    queued_path = Path(job.payload["path"])
    assert queued_path.exists()
    queued_path.unlink()


def test_worker_audio_handler_ingests_call(tmp_path: Path) -> None:
    store, settings, _payload_data = _store(tmp_path)
    scripts_dir = CALL_CENTER_DIR / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    import worker as callpilot_worker

    handlers = callpilot_worker.build_handlers(store, settings)
    audio = _wav(tmp_path / "worker.wav")
    handlers["audio_ingest"](
        {
            "path": str(audio),
            "filename": "worker.wav",
            "title": "Из очереди",
            "external_id": "ext-worker",
        }
    )

    assert not audio.exists()
    call = store.find_by_external_id("ext-worker")
    assert call is not None
    assert call["title"] == "Из очереди"


@pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="TEST_DATABASE_URL is not set",
)
def test_call_store_postgres_roundtrip(tmp_path: Path) -> None:
    url = os.environ["TEST_DATABASE_URL"]
    settings = Settings(
        _env_file=None,
        aitunnel_api_key="sk-test",
        database_path=tmp_path / "unused.db",
        database_url=url,
        callpilot_db_url=url,
        crm_webhook_enabled=True,
        crm_outbox_path=tmp_path / "outbox.db",
    )
    store = CallStore(
        settings,
        tmp_path / "unused.db",
        stt_client=FakeSTT(),
        audio_dir=tmp_path / "audio",
    )
    payload = _payload()
    payload["fields"] = {
        "client_name": "Анна",
        "contact": "+7 900 123-45-67",
    }
    store.service = ProcessService(
        settings=settings,
        db=store.core_db,
        llm=FakeLLMClient([payload]),
        scenarios=SCENARIOS,
    )

    external_id = f"pg-{uuid.uuid4().hex[:10]}"
    call_id = store.ingest_audio(
        _wav(tmp_path / "pg.wav"),
        filename="pg.wav",
        title="PostgreSQL звонок",
        external_id=external_id,
    )

    call = store.get_call(call_id)
    assert call is not None
    assert call["source"] == "real"
    assert call["draft_result"]["fields"]["client_name"] == "[PERSON_1]"
    assert store.find_by_external_id(external_id)["id"] == call_id

    store.confirm_call(call_id, call["draft_result"], "QA")
    outbox = WebhookOutbox(settings.crm_outbox_path)
    assert outbox.get(call["request_id"]) is not None
