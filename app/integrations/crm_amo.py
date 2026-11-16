"""amoCRM adapter for API v4.

Setup:
1. Create a private integration in amoCRM.
2. Issue a long-lived access token with access to leads, contacts and notes.
3. Set ``CRM_PROVIDER=amo``, ``CRM_AMO_BASE_URL`` and ``CRM_AMO_TOKEN``.

The adapter uses ``POST /api/v4/leads/complex`` to create a lead together
with a contact, then adds a note with the QA summary. Custom field IDs are
optional and configured through ``CRM_FIELD_MAP``.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Iterable, Mapping

import httpx

from app.integrations.crm_common import (
    build_note,
    extract_entity_id,
    payload_value,
    post_json,
    validate_https,
)
from app.integrations.crm_webhook import WebhookDelivery


class AmoCRMClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        field_map: Mapping[str, str] | None = None,
        pipeline_id: int = 0,
        status_id: int = 0,
        responsible_user_id: int = 0,
        timeout: float = 10.0,
        max_attempts: int = 3,
        delays: Iterable[float] = (2.0, 5.0, 10.0),
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        allow_insecure: bool = False,
    ) -> None:
        validate_https(
            base_url,
            label="CRM_AMO_BASE_URL",
            allow_insecure=allow_insecure,
        )
        if not token.strip():
            raise ValueError("CRM_AMO_TOKEN is required")
        self.base_url = base_url.rstrip("/")
        self.token = token.strip()
        self.field_map = dict(field_map or {})
        self.pipeline_id = pipeline_id
        self.status_id = status_id
        self.responsible_user_id = responsible_user_id
        self.timeout = timeout
        self.max_attempts = max_attempts
        self.delays = tuple(delays)
        self.transport = transport
        self.sleep = sleep

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    def build_lead(self, payload: dict[str, Any]) -> dict[str, Any]:
        client_fields = payload.get("client_fields")
        client_fields = (
            client_fields if isinstance(client_fields, dict) else {}
        )
        request_id = str(payload.get("request_id") or "")
        name = (
            client_fields.get("client_name")
            or client_fields.get("contact_name")
            or "Клиент Call-Pilot"
        )
        title = f"Звонок: {name}"
        if request_id:
            title += f" · {request_id[:8]}"

        lead: dict[str, Any] = {"name": title[:255], "price": 0}
        if self.pipeline_id:
            lead["pipeline_id"] = self.pipeline_id
        if self.status_id:
            lead["status_id"] = self.status_id
        if self.responsible_user_id:
            lead["responsible_user_id"] = self.responsible_user_id

        contact: dict[str, Any] = {"first_name": str(name)[:150]}
        contact_fields: list[dict[str, Any]] = []
        phone = client_fields.get("phone") or client_fields.get("contact")
        if phone:
            contact_fields.append(
                {
                    "field_code": "PHONE",
                    "values": [
                        {"value": str(phone), "enum_code": "WORK"}
                    ],
                }
            )
        email = client_fields.get("email")
        if email:
            contact_fields.append(
                {
                    "field_code": "EMAIL",
                    "values": [
                        {"value": str(email), "enum_code": "WORK"}
                    ],
                }
            )
        if contact_fields:
            contact["custom_fields_values"] = contact_fields
        lead["_embedded"] = {"contacts": [contact]}

        custom_fields: list[dict[str, Any]] = []
        for key, field_id in self.field_map.items():
            value = payload_value(payload, client_fields, key)
            if value is None:
                continue
            try:
                numeric_id = int(field_id)
            except ValueError as exc:
                raise ValueError(
                    "amoCRM CRM_FIELD_MAP values must be numeric field IDs"
                ) from exc
            custom_fields.append(
                {
                    "field_id": numeric_id,
                    "values": [{"value": str(value)}],
                }
            )
        if custom_fields:
            lead["custom_fields_values"] = custom_fields

        return lead

    def send(self, payload: dict[str, Any]) -> WebhookDelivery:
        url = f"{self.base_url}/api/v4/leads/complex"
        result = post_json(
            url,
            [self.build_lead(payload)],
            headers=self._headers(),
            timeout=self.timeout,
            max_attempts=self.max_attempts,
            delays=self.delays,
            transport=self.transport,
            sleep=self.sleep,
        )
        if result.error:
            return WebhookDelivery(
                status="failed",
                attempts=result.attempts,
                status_code=result.status_code,
                error=result.error,
            )

        data = result.data
        if isinstance(data, dict):
            if data.get("status") == "fail" or data.get("errors"):
                message = data.get("detail") or data.get("title")
                return WebhookDelivery(
                    status="failed",
                    attempts=result.attempts,
                    status_code=result.status_code,
                    error=str(message or "amoCRM error"),
                )

        external_id = extract_entity_id(data)
        if external_id:
            self._add_note(external_id, payload)

        return WebhookDelivery(
            status="sent",
            attempts=result.attempts,
            status_code=result.status_code,
            external_id=external_id,
        )

    def _add_note(self, lead_id: str, payload: dict[str, Any]) -> None:
        note = build_note(payload)
        if not note:
            return
        url = f"{self.base_url}/api/v4/leads/{lead_id}/notes"
        # Notes are best-effort: the lead is already created, and a retry
        # here would duplicate the note. A missing note is not fatal.
        post_json(
            url,
            [{"note_type": "common", "params": {"text": note}}],
            headers=self._headers(),
            timeout=self.timeout,
            max_attempts=1,
            transport=self.transport,
            sleep=self.sleep,
        )
