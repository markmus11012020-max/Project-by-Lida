from __future__ import annotations

from pathlib import Path

from app.integrations import (
    OutboxDispatcher,
    WebhookDelivery,
    WebhookOutbox,
)
from app.security import InMemoryPIIVault


class FakeClient:
    def __init__(self, delivery: WebhookDelivery | None = None) -> None:
        self.delivery = delivery or WebhookDelivery(status="sent", attempts=1)
        self.payloads: list[dict] = []

    def send(self, payload: dict) -> WebhookDelivery:
        self.payloads.append(payload)
        return self.delivery


def test_dispatcher_restores_only_client_fields(tmp_path: Path) -> None:
    outbox = WebhookOutbox(tmp_path / "outbox.db")
    vault = InMemoryPIIVault()
    mapping = {
        "[PERSON_1]": "Анна",
        "[PHONE_1]": "+7 900 123-45-67",
        "[EMAIL_1]": "anna@example.ru",
    }
    kinds = {
        "[PERSON_1]": "PERSON",
        "[PHONE_1]": "PHONE",
        "[EMAIL_1]": "EMAIL",
    }
    vault.put("req-1", mapping, kinds, ttl_seconds=60)
    outbox.enqueue(
        "req-1",
        {
            "request_id": "req-1",
            "client_fields": {
                "client_name": "[PERSON_1]",
                "contact": "[PHONE_1]",
                "email": "[EMAIL_1]",
            },
            "summary": "Звонок [PERSON_1]",
        },
    )

    client = FakeClient()
    report = OutboxDispatcher(outbox, client, vault).run_once()

    assert report.sent == 1
    assert len(client.payloads) == 1
    payload = client.payloads[0]
    assert payload["client_fields"]["client_name"] == "Анна"
    assert payload["client_fields"]["contact"] == "+7 900 123-45-67"
    assert payload["client_fields"]["email"] == "anna@example.ru"
    assert payload["summary"] == "Звонок [PERSON_1]"
    assert outbox.get("req-1")["status"] == "sent"


def test_dispatcher_skips_missing_mapping(tmp_path: Path) -> None:
    outbox = WebhookOutbox(tmp_path / "outbox.db")
    vault = InMemoryPIIVault()
    outbox.enqueue("req-1", {"request_id": "req-1", "client_fields": {}})

    client = FakeClient()
    report = OutboxDispatcher(outbox, client, vault).run_once()

    assert report.skipped == 1
    assert client.payloads == []
    assert outbox.get("req-1")["status"] == "failed"


def test_dispatcher_marks_retry_on_failure(tmp_path: Path) -> None:
    outbox = WebhookOutbox(tmp_path / "outbox.db")
    vault = InMemoryPIIVault()
    vault.put("req-1", {}, {}, ttl_seconds=60)
    outbox.enqueue("req-1", {"request_id": "req-1", "client_fields": {}})

    client = FakeClient(
        WebhookDelivery(status="failed", attempts=3, error="HTTP 503")
    )
    report = OutboxDispatcher(outbox, client, vault).run_once()

    assert report.failed == 1
    stored = outbox.get("req-1")
    assert stored is not None
    assert stored["status"] == "retry"
    assert stored["attempts"] == 1
    assert stored["last_error"] == "HTTP 503"
