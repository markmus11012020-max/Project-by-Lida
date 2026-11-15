from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path

import httpx

from app.integrations import (
    CRMWebhookClient,
    WebhookOutbox,
    retry_at,
    sign_payload,
)


def test_signature_matches_hmac() -> None:
    body = b'{"request_id":"abc"}'
    expected = hmac.new(b"secret", body, hashlib.sha256).hexdigest()

    assert sign_payload("secret", body) == expected


def test_send_success_signs_exact_body() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["signature"] = request.headers["X-Webhook-Signature"]
        captured["body"] = request.content
        return httpx.Response(200, json={"ok": True})

    payload = {"request_id": "req-1", "call_score": 91, "summary": "Готово"}
    client = CRMWebhookClient(
        "https://crm.example/webhook",
        "secret",
        transport=httpx.MockTransport(handler),
        sleep=lambda _: None,
    )
    delivery = client.send(payload)

    assert delivery.status == "sent"
    assert delivery.attempts == 1
    assert delivery.status_code == 200
    body = captured["body"]
    assert isinstance(body, bytes)
    assert json.loads(body) == payload
    assert captured["signature"] == sign_payload("secret", body)


def test_retry_on_500_then_success() -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            return httpx.Response(500)
        return httpx.Response(200)

    client = CRMWebhookClient(
        "https://crm.example/webhook",
        "secret",
        transport=httpx.MockTransport(handler),
        sleep=lambda _: None,
    )
    delivery = client.send({"request_id": "req-2"})

    assert delivery.status == "sent"
    assert delivery.attempts == 2
    assert calls["count"] == 2


def test_does_not_retry_on_400() -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(400)

    client = CRMWebhookClient(
        "https://crm.example/webhook",
        "secret",
        transport=httpx.MockTransport(handler),
        sleep=lambda _: None,
    )
    delivery = client.send({"request_id": "req-3"})

    assert delivery.status == "failed"
    assert delivery.attempts == 1
    assert calls["count"] == 1


def test_retry_exhausted() -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(503)

    client = CRMWebhookClient(
        "https://crm.example/webhook",
        "secret",
        transport=httpx.MockTransport(handler),
        max_attempts=3,
        sleep=lambda _: None,
    )
    delivery = client.send({"request_id": "req-4"})

    assert delivery.status == "failed"
    assert delivery.attempts == 3
    assert calls["count"] == 3


def test_disabled_client_does_not_send() -> None:
    client = CRMWebhookClient("https://crm.example/webhook", "", enabled=False)
    delivery = client.send({"request_id": "req-5"})

    assert delivery.status == "disabled"
    assert delivery.attempts == 0


def test_outbox_flow(tmp_path: Path) -> None:
    outbox = WebhookOutbox(tmp_path / "outbox.db")
    payload = {"request_id": "req-6", "summary": "Тест"}

    assert outbox.enqueue("req-6", payload) is True
    assert outbox.enqueue("req-6", payload) is False

    pending = outbox.pending()
    assert len(pending) == 1
    assert pending[0]["payload"] == payload
    assert pending[0]["status"] == "pending"

    outbox.mark_failed("req-6", "HTTP 503", retry_at(60))
    stored = outbox.get("req-6")
    assert stored is not None
    assert stored["status"] == "retry"
    assert stored["attempts"] == 1
    assert stored["last_error"] == "HTTP 503"

    outbox.mark_sent("req-6")
    stored = outbox.get("req-6")
    assert stored is not None
    assert stored["status"] == "sent"
    assert stored["attempts"] == 2
    assert outbox.pending() == []
