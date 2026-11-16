from __future__ import annotations

import json

import httpx
import pytest

from app.config import Settings
from app.integrations import (
    AmoCRMClient,
    Bitrix24Client,
    build_crm_client,
    load_field_map,
)

PAYLOAD = {
    "request_id": "req-12345678",
    "status": "processed",
    "call_score": 42,
    "checklist_results": [
        {
            "criterion": "Точность информации",
            "status": "fail",
            "severity": "critical",
        },
        {
            "criterion": "Эмпатия",
            "status": "pass",
            "severity": "low",
        },
    ],
    "summary": "Клиент хочет вернуть деньги",
    "next_action": "Передать руководителю",
    "escalation_flag": True,
    "client_fields": {
        "client_name": "Анна",
        "phone": "+7 900 123-45-67",
        "email": "anna@example.ru",
    },
}


def test_bitrix_builds_lead_fields() -> None:
    client = Bitrix24Client(
        "https://example.bitrix24.ru/rest/1/token/",
        entity="lead",
        field_map={"qa_score": "UF_CRM_QA"},
        source_id="CALL",
        assigned_by_id=7,
    )

    fields = client.build_fields(PAYLOAD)

    assert fields["TITLE"].startswith("Звонок · Анна")
    assert fields["NAME"] == "Анна"
    assert fields["PHONE"] == [
        {"VALUE": "+7 900 123-45-67", "VALUE_TYPE": "WORK"}
    ]
    assert fields["EMAIL"] == [
        {"VALUE": "anna@example.ru", "VALUE_TYPE": "WORK"}
    ]
    assert fields["ORIGIN_ID"] == "req-12345678"
    assert fields["ORIGINATOR_ID"] == "call-pilot"
    assert fields["SOURCE_ID"] == "CALL"
    assert fields["ASSIGNED_BY_ID"] == 7
    assert fields["UF_CRM_QA"] == 42
    assert "QA-score: 42/100" in fields["COMMENTS"]
    assert "Нарушение (critical): Точность информации" in fields["COMMENTS"]
    assert "Требуется ручная проверка: да" in fields["COMMENTS"]
    assert "Call-Pilot ID: req-12345678" in fields["COMMENTS"]


def test_bitrix_sends_lead_and_returns_external_id() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"result": 42})

    client = Bitrix24Client(
        "https://example.bitrix24.ru/rest/1/token/",
        transport=httpx.MockTransport(handler),
        sleep=lambda _: None,
    )
    delivery = client.send(PAYLOAD)

    assert delivery.status == "sent"
    assert delivery.external_id == "42"
    assert captured["url"].endswith("/crm.lead.add.json")
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["fields"]["NAME"] == "Анна"
    assert body["params"]["REGISTER_SONET_EVENT"] == "Y"


def test_bitrix_returns_error_from_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "error": "ERROR_CORE",
                "error_description": "Access denied",
            },
        )

    client = Bitrix24Client(
        "https://example.bitrix24.ru/rest/1/token/",
        transport=httpx.MockTransport(handler),
        sleep=lambda _: None,
    )
    delivery = client.send(PAYLOAD)

    assert delivery.status == "failed"
    assert "Access denied" in (delivery.error or "")


def test_bitrix_retries_on_500() -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            return httpx.Response(500)
        return httpx.Response(200, json={"result": 1})

    client = Bitrix24Client(
        "https://example.bitrix24.ru/rest/1/token/",
        transport=httpx.MockTransport(handler),
        sleep=lambda _: None,
    )
    delivery = client.send(PAYLOAD)

    assert delivery.status == "sent"
    assert delivery.attempts == 2


def test_amo_builds_complex_lead() -> None:
    client = AmoCRMClient(
        "https://example.amocrm.ru",
        "token",
        field_map={"qa_score": "12345"},
        pipeline_id=1,
        status_id=2,
        responsible_user_id=3,
    )

    lead = client.build_lead(PAYLOAD)

    assert lead["name"].startswith("Звонок: Анна")
    assert lead["pipeline_id"] == 1
    assert lead["status_id"] == 2
    assert lead["responsible_user_id"] == 3
    contact = lead["_embedded"]["contacts"][0]
    assert contact["first_name"] == "Анна"
    phone = contact["custom_fields_values"][0]
    assert phone["field_code"] == "PHONE"
    assert phone["values"][0]["value"] == "+7 900 123-45-67"
    assert lead["custom_fields_values"] == [
        {"field_id": 12345, "values": [{"value": "42"}]}
    ]


def test_amo_sends_lead_and_note() -> None:
    captured: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(
            {
                "url": str(request.url),
                "body": json.loads(request.content),
                "auth": request.headers.get("Authorization"),
            }
        )
        if request.url.path.endswith("/leads/complex"):
            return httpx.Response(200, json=[{"id": 77}])
        return httpx.Response(200, json={"id": 1})

    client = AmoCRMClient(
        "https://example.amocrm.ru",
        "token",
        transport=httpx.MockTransport(handler),
        sleep=lambda _: None,
    )
    delivery = client.send(PAYLOAD)

    assert delivery.status == "sent"
    assert delivery.external_id == "77"
    assert len(captured) == 2
    lead_request = captured[0]
    assert lead_request["auth"] == "Bearer token"
    assert lead_request["url"].endswith("/api/v4/leads/complex")
    lead = lead_request["body"][0]
    assert lead["_embedded"]["contacts"][0]["first_name"] == "Анна"

    note_request = captured[1]
    assert note_request["url"].endswith("/api/v4/leads/77/notes")
    note = note_request["body"][0]
    assert note["note_type"] == "common"
    assert "QA-score: 42/100" in note["params"]["text"]


def test_amo_does_not_add_note_on_error() -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(401, json={"detail": "Unauthorized"})

    client = AmoCRMClient(
        "https://example.amocrm.ru",
        "token",
        transport=httpx.MockTransport(handler),
        sleep=lambda _: None,
    )
    delivery = client.send(PAYLOAD)

    assert delivery.status == "failed"
    assert calls["count"] == 1


def test_load_field_map() -> None:
    assert load_field_map('{"qa_score": "UF_CRM_1"}') == {
        "qa_score": "UF_CRM_1"
    }
    assert load_field_map('{"qa_score": 123}') == {"qa_score": "123"}
    assert load_field_map("") == {}
    with pytest.raises(ValueError):
        load_field_map("{bad json")
    with pytest.raises(ValueError):
        load_field_map('["not", "object"]')


def test_factory_builds_native_clients() -> None:
    bitrix = build_crm_client(
        Settings(
            _env_file=None,
            crm_enabled=True,
            crm_provider="bitrix24",
            crm_bitrix24_webhook_url=(
                "https://example.bitrix24.ru/rest/1/token/"
            ),
            crm_field_map='{"qa_score": "UF_CRM_QA"}',
        )
    )
    assert isinstance(bitrix, Bitrix24Client)
    assert bitrix.field_map == {"qa_score": "UF_CRM_QA"}

    amo = build_crm_client(
        Settings(
            _env_file=None,
            crm_enabled=True,
            crm_provider="amo",
            crm_amo_base_url="https://example.amocrm.ru",
            crm_amo_token="token",
        )
    )
    assert isinstance(amo, AmoCRMClient)


def test_factory_requires_credentials() -> None:
    with pytest.raises(ValueError, match="CRM_BITRIX24_WEBHOOK_URL"):
        build_crm_client(
            Settings(
                _env_file=None,
                crm_enabled=True,
                crm_provider="bitrix24",
            )
        )
    with pytest.raises(ValueError, match="CRM_AMO_BASE_URL"):
        build_crm_client(
            Settings(
                _env_file=None,
                crm_enabled=True,
                crm_provider="amo",
            )
        )
    with pytest.raises(ValueError, match="CRM_PROVIDER"):
        build_crm_client(
            Settings(
                _env_file=None,
                crm_enabled=True,
                crm_provider="unknown",
            )
        )
