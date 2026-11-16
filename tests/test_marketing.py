from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

CALL_CENTER_DIR = Path(__file__).resolve().parent.parent / "call-center"
sys.path.insert(0, str(CALL_CENTER_DIR))

import call_center_app  # noqa: E402


def test_case_page_shows_before_after() -> None:
    client = TestClient(call_center_app.app)
    response = client.get("/case")

    assert response.status_code == 200
    assert "Один звонок" in response.text
    assert "Было" in response.text
    assert "Стало" in response.text
    assert "2 critical" in response.text
    assert "/static/audio/call_02.mp3" in response.text
    assert "HITL" in response.text
    assert "og:image" in response.text


def test_privacy_page_has_operator_and_legal_basis() -> None:
    client = TestClient(call_center_app.app)
    response = client.get("/privacy")

    assert response.status_code == 200
    assert "Мусина Гульназ Мягазовна" in response.text
    assert "631306493907" in response.text
    assert "152-ФЗ" in response.text
    assert "aillix@mail.ru" in response.text
    assert "og:image" in response.text


def test_landing_has_sales_blocks_and_contacts() -> None:
    client = TestClient(call_center_app.app)
    response = client.get("/")

    assert response.status_code == 200
    assert "+7 962 609-00-01" in response.text
    assert "20 000 ₽" in response.text
    assert "от 120 000 ₽" in response.text
    assert "от 300 000 ₽" in response.text
    assert "roi-calls" in response.text
    assert 'value="215"' in response.text
    assert "по всему объёму звонков" in response.text
    assert "не экономия на одном операторе" in response.text
    assert "AITUNNEL" in response.text
    assert "Bitrix24" in response.text
    assert "amoCRM" in response.text
    assert "/privacy" in response.text
    assert "og:image" in response.text
    assert "Мусина Гульназ Мягазовна" in response.text


def test_offer_has_price_range_and_phone() -> None:
    client = TestClient(call_center_app.app)
    response = client.get("/offer")

    assert response.status_code == 200
    assert "от 120 000 ₽" in response.text
    assert "+7 962 609-00-01" in response.text
    assert "Bitrix24" in response.text
    assert "og:image" in response.text
