"""Bitrix24 CRM adapter built on an inbound REST webhook.

Setup:
1. In Bitrix24 open Applications -> Webhooks -> Inbound webhook.
2. Grant the ``crm`` scope and copy the URL:
   ``https://<portal>.bitrix24.ru/rest/<user_id>/<token>/``
3. Set ``CRM_PROVIDER=bitrix24`` and ``CRM_BITRIX24_WEBHOOK_URL``.

The adapter creates a lead or deal via ``crm.lead.add`` / ``crm.deal.add``.
No OAuth application is required for a pilot.
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


class Bitrix24Client:
    def __init__(
        self,
        webhook_url: str,
        *,
        entity: str = "lead",
        field_map: Mapping[str, str] | None = None,
        source_id: str = "",
        assigned_by_id: int = 0,
        timeout: float = 10.0,
        max_attempts: int = 3,
        delays: Iterable[float] = (2.0, 5.0, 10.0),
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        allow_insecure: bool = False,
    ) -> None:
        validate_https(
            webhook_url,
            label="CRM_BITRIX24_WEBHOOK_URL",
            allow_insecure=allow_insecure,
        )
        if entity not in {"lead", "deal"}:
            raise ValueError("CRM_BITRIX24_ENTITY must be 'lead' or 'deal'")
        self.webhook_url = webhook_url.rstrip("/")
        self.entity = entity
        self.field_map = dict(field_map or {})
        self.source_id = source_id.strip()
        self.assigned_by_id = assigned_by_id
        self.timeout = timeout
        self.max_attempts = max_attempts
        self.delays = tuple(delays)
        self.transport = transport
        self.sleep = sleep

    def build_fields(self, payload: dict[str, Any]) -> dict[str, Any]:
        client_fields = payload.get("client_fields")
        client_fields = (
            client_fields if isinstance(client_fields, dict) else {}
        )
        request_id = str(payload.get("request_id") or "")
        name = (
            client_fields.get("client_name")
            or client_fields.get("contact_name")
            or ""
        )
        title_parts = ["Звонок"]
        if name:
            title_parts.append(str(name))
        if request_id:
            title_parts.append(f"#{request_id[:8]}")
        fields: dict[str, Any] = {
            "TITLE": " · ".join(title_parts)[:255],
            "ORIGINATOR_ID": "call-pilot",
        }
        if request_id:
            fields["ORIGIN_ID"] = request_id
        if name:
            fields["NAME"] = str(name)[:150]

        phone = client_fields.get("phone") or client_fields.get("contact")
        if phone:
            fields["PHONE"] = [
                {"VALUE": str(phone), "VALUE_TYPE": "WORK"}
            ]
        email = client_fields.get("email")
        if email:
            fields["EMAIL"] = [
                {"VALUE": str(email), "VALUE_TYPE": "WORK"}
            ]

        comments = build_note(payload)
        if comments:
            fields["COMMENTS"] = comments

        if self.source_id:
            fields["SOURCE_ID"] = self.source_id
        if self.assigned_by_id:
            fields["ASSIGNED_BY_ID"] = self.assigned_by_id

        for key, field_code in self.field_map.items():
            value = payload_value(payload, client_fields, key)
            if value is not None:
                fields[field_code] = value

        return fields

    def send(self, payload: dict[str, Any]) -> WebhookDelivery:
        url = f"{self.webhook_url}/crm.{self.entity}.add.json"
        result = post_json(
            url,
            {
                "fields": self.build_fields(payload),
                "params": {"REGISTER_SONET_EVENT": "Y"},
            },
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
        if isinstance(data, dict) and data.get("error"):
            message = (
                data.get("error_description")
                or data.get("error")
                or "Bitrix24 error"
            )
            return WebhookDelivery(
                status="failed",
                attempts=result.attempts,
                status_code=result.status_code,
                error=str(message),
            )

        return WebhookDelivery(
            status="sent",
            attempts=result.attempts,
            status_code=result.status_code,
            external_id=extract_entity_id(data),
        )
