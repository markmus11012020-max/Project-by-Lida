from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

CALL_CENTER_DIR = Path(__file__).resolve().parent.parent / "call-center"
sys.path.insert(0, str(CALL_CENTER_DIR))

import call_center_app  # noqa: E402
from tests.test_call_center_v2 import _store  # noqa: E402


def test_landing_contains_hitl_and_services() -> None:
    client = TestClient(call_center_app.app)
    response = client.get("/")

    assert response.status_code == 200
    assert "Call-Pilot" in response.text
    assert "AI заполняет карточку" in response.text
    assert "Human-in-the-loop" in response.text
    assert "Экспресс-аудит QA и CRM" in response.text
    assert "aillix@mail.ru" in response.text


def test_lead_form_saves_lead(tmp_path: Path, monkeypatch) -> None:
    store, _settings, _payload = _store(tmp_path)
    monkeypatch.setattr(call_center_app, "store", store)
    client = TestClient(call_center_app.app)

    response = client.post(
        "/lead",
        data={
            "name": "Иван",
            "company": "ООО Тест",
            "contact": "+7 900 000-00-00",
            "volume": "100–500",
            "phone_system": "Oktell",
            "comment": "Хотим пилот",
            "consent": "yes",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/?sent=1#lead"
    with store._connect() as connection:
        row = connection.execute("SELECT * FROM leads").fetchone()
    assert row is not None
    assert row["name"] == "Иван"
    assert row["contact"] == "+7 900 000-00-00"
    assert row["consent"] == 1


def test_lead_form_requires_consent(tmp_path: Path, monkeypatch) -> None:
    store, _settings, _payload = _store(tmp_path)
    monkeypatch.setattr(call_center_app, "store", store)
    client = TestClient(call_center_app.app)

    response = client.post(
        "/lead",
        data={
            "name": "Иван",
            "contact": "test@example.ru",
            "consent": "",
        },
    )

    assert response.status_code == 422
    with store._connect() as connection:
        count = connection.execute("SELECT COUNT(*) AS c FROM leads").fetchone()["c"]
    assert count == 0
