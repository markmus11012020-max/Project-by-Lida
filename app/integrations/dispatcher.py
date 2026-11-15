"""Deliver CRM webhook payloads from the outbox.

The outbox stores masked payloads. Before sending, only the allowed client
fields are restored from the PII vault; summaries and QA evidence stay
masked, so the CRM never receives more PII than the contract allows.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from app.integrations.crm_webhook import (
    CRMWebhookClient,
    WebhookOutbox,
    retry_at,
)
from app.security import PIIVault, VaultEntry

DEFAULT_ALLOWED_KINDS = {"PERSON", "PHONE", "EMAIL"}


def restore_client_fields(
    payload: dict[str, Any],
    entry: VaultEntry,
    allowed_kinds: Iterable[str] = DEFAULT_ALLOWED_KINDS,
) -> dict[str, Any]:
    allowed = {kind.upper() for kind in allowed_kinds}
    restored = dict(payload)
    fields = restored.get("client_fields")
    if not isinstance(fields, dict):
        return restored

    clean: dict[str, Any] = {}
    for key, value in fields.items():
        if not isinstance(value, str):
            clean[key] = value
            continue
        for token, original in entry.mapping.items():
            if entry.kinds.get(token) not in allowed:
                continue
            value = value.replace(token, original)
        clean[key] = value
    restored["client_fields"] = clean
    return restored


@dataclass(frozen=True)
class DispatchReport:
    sent: int = 0
    failed: int = 0
    skipped: int = 0


class OutboxDispatcher:
    def __init__(
        self,
        outbox: WebhookOutbox,
        client: CRMWebhookClient,
        vault: PIIVault,
        batch_size: int = 50,
        retry_delay_seconds: int = 60,
        allowed_kinds: Iterable[str] = DEFAULT_ALLOWED_KINDS,
    ) -> None:
        self.outbox = outbox
        self.client = client
        self.vault = vault
        self.batch_size = batch_size
        self.retry_delay_seconds = retry_delay_seconds
        self.allowed_kinds = set(allowed_kinds)

    def run_once(self) -> DispatchReport:
        sent = failed = skipped = 0
        for item in self.outbox.pending(limit=self.batch_size):
            request_id = item["request_id"]
            entry = self.vault.get(request_id)
            if entry is None:
                self.outbox.mark_failed(
                    request_id,
                    "PII mapping expired or missing",
                )
                skipped += 1
                continue

            payload = restore_client_fields(
                item["payload"],
                entry,
                allowed_kinds=self.allowed_kinds,
            )
            delivery = self.client.send(payload)
            if delivery.status == "sent":
                self.outbox.mark_sent(request_id)
                sent += 1
            else:
                self.outbox.mark_failed(
                    request_id,
                    delivery.error or "webhook delivery failed",
                    retry_at=retry_at(self.retry_delay_seconds),
                )
                failed += 1
        return DispatchReport(sent=sent, failed=failed, skipped=skipped)
