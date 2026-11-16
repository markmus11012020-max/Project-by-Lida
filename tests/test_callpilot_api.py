from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

from app.schemas import ProcessMeta, ProcessResponse, ProcessStatus
from tests.test_call_center_v2 import _store

CALL_CENTER_DIR = Path(__file__).resolve().parent.parent / "call-center"
sys.path.insert(0, str(CALL_CENTER_DIR))

import call_center_app  # noqa: E402

PAYLOAD = {
    "title": "Тестовый звонок",
    "transcript": (
        "Клиент просит вернуть деньги за бракованный товар. "
        "Оператор обещает возврат сегодня."
    ),
    "client": "Мария",
    "operator": "Анна",
}


def _client(tmp_path: Path, monkeypatch, demo_mode: bool = False):
    store, settings, _payload = _store(tmp_path)
    settings = settings.model_copy(update={"demo_mode": demo_mode})
    monkeypatch.setattr(call_center_app, "store", store)
    monkeypatch.setattr(call_center_app, "settings", settings)
    return store, TestClient(call_center_app.app)


def test_api_create_list_and_audit(tmp_path: Path, monkeypatch) -> None:
    store, client = _client(tmp_path, monkeypatch)

    created = client.post("/api/v1/calls", json=PAYLOAD)
    assert created.status_code == 201
    body = created.json()
    call_id = body["call_id"]
    assert call_id.startswith("api_")
    assert body["need_review"] is False
    assert body["status"] == "new"

    listed = client.get("/api/v1/calls?source=api")
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["call_id"] == call_id

    detail = client.get(f"/api/v1/calls/{call_id}")
    assert detail.status_code == 200
    assert "бракованный товар" in detail.json()["transcript"]
    assert detail.json()["need_review"] is False

    audit = client.get(f"/api/v1/audit?call_id={call_id}")
    assert audit.status_code == 200
    actions = [item["action"] for item in audit.json()["items"]]
    assert "create_call" in actions

    page = client.get("/audit")
    assert page.status_code == 200
    assert "Журнал аудита" in page.text
    assert call_id in page.text

    csv_export = client.get("/export/results.csv")
    assert csv_export.status_code == 200
    assert call_id in csv_export.text
    assert "need_review" in csv_export.text

    jsonl_export = client.get("/export/audit.jsonl")
    assert jsonl_export.status_code == 200
    assert "create_call" in jsonl_export.text


def test_api_process_sets_need_review(tmp_path: Path, monkeypatch) -> None:
    store, client = _client(tmp_path, monkeypatch)
    call_id = client.post("/api/v1/calls", json=PAYLOAD).json()["call_id"]

    def fake_process(**kwargs):
        return ProcessResponse(
            request_id="req-manual-1",
            scenario="call_qa",
            status=ProcessStatus.ESCALATED,
            result={
                "intent": "refund",
                "qa_score": 0,
                "auto_qa_status": "manual_review",
                "escalate": True,
                "escalate_reason": "critical_finding",
                "qa_findings": [],
            },
            meta=ProcessMeta(
                model="fake",
                temperature=0.2,
                latency_ms=1,
                created_at="2026-11-16T00:00:00+00:00",
            ),
        )

    monkeypatch.setattr(store.service, "process", fake_process)

    processed = client.post(f"/api/v1/calls/{call_id}/process")
    assert processed.status_code == 200
    body = processed.json()
    assert body["need_review"] is True
    assert body["review_reason"] == "critical_finding"
    assert body["result"]["qa_score"] == 0

    detail = client.get(f"/api/v1/calls/{call_id}")
    assert detail.json()["need_review"] is True
    assert detail.json()["review_reason"] == "critical_finding"

    audit = client.get(f"/api/v1/audit?call_id={call_id}")
    actions = [item["action"] for item in audit.json()["items"]]
    assert "process_call" in actions


def test_api_writes_are_blocked_in_demo_mode(tmp_path: Path, monkeypatch) -> None:
    _store_, client = _client(tmp_path, monkeypatch, demo_mode=True)

    created = client.post("/api/v1/calls", json=PAYLOAD)
    assert created.status_code == 403

    processed = client.post("/api/v1/calls/call_02/process")
    assert processed.status_code == 403
