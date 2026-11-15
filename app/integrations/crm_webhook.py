"""Outgoing CRM webhook with HMAC signing, retries and a durable outbox."""

from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

import httpx

RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def sign_payload(secret: str, body: bytes) -> str:
    """Return the hex HMAC-SHA256 signature expected by the CRM."""

    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


@dataclass(frozen=True)
class WebhookDelivery:
    status: str  # sent | failed | retry | disabled
    attempts: int
    status_code: int | None = None
    error: str | None = None


class CRMWebhookClient:
    """Send one JSON payload to a CRM webhook.

    Retries are intentionally small and bounded. In production the client is
    called by an outbox worker, not inside the user's HTTP request.
    """

    def __init__(
        self,
        url: str,
        secret: str,
        enabled: bool = True,
        timeout: float = 10.0,
        max_attempts: int = 3,
        delays: Iterable[float] = (2.0, 5.0, 10.0),
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        allow_insecure: bool = False,
    ) -> None:
        if enabled and not url.startswith("https://") and not allow_insecure:
            raise ValueError("CRM webhook URL must use HTTPS")
        if enabled and not secret:
            raise ValueError("CRM webhook secret is required")
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        self.url = url
        self.secret = secret
        self.enabled = enabled
        self.timeout = timeout
        self.max_attempts = max_attempts
        self.delays = tuple(delays)
        self.transport = transport
        self.sleep = sleep
        self.allow_insecure = allow_insecure

    def send(self, payload: dict[str, Any]) -> WebhookDelivery:
        if not self.enabled:
            return WebhookDelivery(status="disabled", attempts=0)

        body = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "X-Webhook-Signature": sign_payload(self.secret, body),
        }

        last_error: str | None = None
        last_status: int | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                with httpx.Client(
                    timeout=self.timeout,
                    transport=self.transport,
                ) as client:
                    response = client.post(self.url, content=body, headers=headers)
                last_status = response.status_code
                if 200 <= response.status_code < 300:
                    return WebhookDelivery(
                        status="sent",
                        attempts=attempt,
                        status_code=response.status_code,
                    )
                if response.status_code not in RETRYABLE_STATUS:
                    return WebhookDelivery(
                        status="failed",
                        attempts=attempt,
                        status_code=response.status_code,
                        error=f"HTTP {response.status_code}",
                    )
                last_error = f"HTTP {response.status_code}"
            except httpx.HTTPError as exc:
                last_error = f"{type(exc).__name__}: {exc}"

            if attempt < self.max_attempts:
                index = min(attempt - 1, max(0, len(self.delays) - 1))
                delay = self.delays[index] if self.delays else 0.0
                if delay:
                    self.sleep(delay)

        return WebhookDelivery(
            status="failed",
            attempts=self.max_attempts,
            status_code=last_status,
            error=last_error or "webhook delivery failed",
        )


class WebhookOutbox:
    """SQLite-backed outbox so a CRM outage does not block processing."""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS crm_webhook_outbox (
        request_id TEXT PRIMARY KEY,
        payload_json TEXT NOT NULL,
        status TEXT NOT NULL,
        attempts INTEGER NOT NULL DEFAULT 0,
        last_error TEXT,
        next_attempt_at TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_outbox_due
        ON crm_webhook_outbox(status, next_attempt_at);
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection, connection:
            connection.executescript(self.SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.path), timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def enqueue(
        self,
        request_id: str,
        payload: dict[str, Any],
        next_attempt_at: str | None = None,
    ) -> bool:
        now = utc_now()
        due = next_attempt_at or now
        with closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO crm_webhook_outbox (
                    request_id, payload_json, status, attempts, last_error,
                    next_attempt_at, created_at, updated_at
                ) VALUES (?, ?, 'pending', 0, NULL, ?, ?, ?)
                """,
                (
                    request_id,
                    json.dumps(payload, ensure_ascii=False),
                    due,
                    now,
                    now,
                ),
            )
        return cursor.rowcount > 0

    def pending(self, limit: int = 50, now: str | None = None) -> list[dict[str, Any]]:
        moment = now or utc_now()
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT * FROM crm_webhook_outbox
                WHERE status IN ('pending', 'retry') AND next_attempt_at <= ?
                ORDER BY next_attempt_at ASC
                LIMIT ?
                """,
                (moment, max(1, limit)),
            ).fetchall()
        return [
            {
                "request_id": row["request_id"],
                "payload": json.loads(row["payload_json"]),
                "status": row["status"],
                "attempts": row["attempts"],
                "last_error": row["last_error"],
                "next_attempt_at": row["next_attempt_at"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    def mark_sent(self, request_id: str) -> None:
        now = utc_now()
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                UPDATE crm_webhook_outbox
                SET status='sent', attempts=attempts + 1, last_error=NULL,
                    updated_at=?
                WHERE request_id=?
                """,
                (now, request_id),
            )

    def mark_failed(
        self,
        request_id: str,
        error: str,
        retry_at: str | None = None,
    ) -> None:
        now = utc_now()
        status = "retry" if retry_at else "failed"
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                UPDATE crm_webhook_outbox
                SET status=?, attempts=attempts + 1, last_error=?,
                    next_attempt_at=COALESCE(?, next_attempt_at),
                    updated_at=?
                WHERE request_id=?
                """,
                (status, error[:2000], retry_at, now, request_id),
            )

    def get(self, request_id: str) -> dict[str, Any] | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM crm_webhook_outbox WHERE request_id = ?",
                (request_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "request_id": row["request_id"],
            "payload": json.loads(row["payload_json"]),
            "status": row["status"],
            "attempts": row["attempts"],
            "last_error": row["last_error"],
            "next_attempt_at": row["next_attempt_at"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }


def retry_at(seconds: float) -> str:
    return (
        datetime.now(timezone.utc) + timedelta(seconds=seconds)
    ).isoformat(timespec="milliseconds")
