from __future__ import annotations

import json

from tests.conftest import SUPPORT_OK, FakeLLMClient


def test_health_and_scenarios(api_client_factory) -> None:
    client = api_client_factory(FakeLLMClient([]))

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert health.json()["llm_configured"] is True

    scenarios = client.get("/scenarios")
    assert scenarios.status_code == 200
    keys = {item["key"] for item in scenarios.json()}
    assert keys == {"support", "sales", "documents", "call_qa"}


def test_ingest_and_read_endpoints(api_client_factory) -> None:
    client = api_client_factory(FakeLLMClient([SUPPORT_OK]))

    response = client.post(
        "/ingest",
        json={
            "scenario": "support",
            "text": "Оплатил заказ №12345, доставки нет. Анна, +7 900 123-45-67.",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "processed"
    request_id = payload["request_id"]

    result = client.get(f"/results/{request_id}")
    assert result.status_code == 200
    assert result.json()["result"]["category"] == "delivery"

    audit = client.get(f"/audit/{request_id}")
    assert audit.status_code == 200
    assert audit.json()["raw_response"] is None
    assert audit.json()["raw_response_available"] is True

    listing = client.get("/results")
    assert listing.status_code == 200
    assert len(listing.json()["items"]) == 1

    stats = client.get("/stats")
    assert stats.status_code == 200
    assert stats.json()["total_requests"] == 1


def test_ingest_validation_errors(api_client_factory) -> None:
    client = api_client_factory(FakeLLMClient([]))

    bad_scenario = client.post(
        "/ingest", json={"scenario": "unknown", "text": "Текст"}
    )
    assert bad_scenario.status_code == 422

    short_text = client.post(
        "/ingest", json={"scenario": "support", "text": "ok"}
    )
    assert short_text.status_code == 422


def test_ingest_with_pii_masking(api_client_factory) -> None:
    client = api_client_factory(FakeLLMClient([SUPPORT_OK]))
    response = client.post(
        "/ingest",
        json={
            "scenario": "support",
            "text": "Анна, +7 900 123-45-67. Оплатила заказ.",
            "anonymize": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["meta"]["pii_masked"] is True
    audit = client.get(f"/audit/{payload['request_id']}")
    assert audit.status_code == 200
    assert "+7 900 123-45-67" not in audit.json()["input_text"]


def test_missing_result_returns_404(api_client_factory) -> None:
    client = api_client_factory(FakeLLMClient([]))
    assert client.get("/results/does-not-exist").status_code == 404
    assert client.get("/audit/does-not-exist").status_code == 404


def test_exports(api_client_factory) -> None:
    client = api_client_factory(FakeLLMClient([SUPPORT_OK]))
    created = client.post(
        "/ingest",
        json={"scenario": "support", "text": "Оплатил заказ, доставки нет."},
    )
    assert created.status_code == 200

    csv_response = client.get("/export/results.csv")
    assert csv_response.status_code == 200
    assert "request_id" in csv_response.text
    assert "delivery" in csv_response.text

    audit_response = client.get("/export/audit.jsonl")
    assert audit_response.status_code == 200
    first_line = audit_response.text.strip().splitlines()[0]
    assert json.loads(first_line)["request_id"] == created.json()["request_id"]
