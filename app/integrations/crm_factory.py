"""Build a CRM client from application settings."""

from __future__ import annotations

from typing import Any

from app.integrations.crm_amo import AmoCRMClient
from app.integrations.crm_bitrix24 import Bitrix24Client
from app.integrations.crm_common import load_field_map
from app.integrations.crm_webhook import CRMWebhookClient


def build_crm_client(settings: Any) -> Any:
    provider = (settings.crm_provider or "webhook").strip().lower()
    field_map = load_field_map(settings.crm_field_map)
    common = {
        "timeout": settings.crm_timeout,
        "max_attempts": settings.crm_max_attempts,
    }

    if provider == "webhook":
        if not settings.crm_webhook_url or not settings.crm_webhook_secret:
            raise ValueError(
                "Для CRM_PROVIDER=webhook укажите "
                "CRM_WEBHOOK_URL и CRM_WEBHOOK_SECRET"
            )
        return CRMWebhookClient(
            settings.crm_webhook_url,
            settings.crm_webhook_secret,
            **common,
        )

    if provider == "bitrix24":
        if not settings.crm_bitrix24_webhook_url:
            raise ValueError(
                "Для CRM_PROVIDER=bitrix24 укажите "
                "CRM_BITRIX24_WEBHOOK_URL"
            )
        return Bitrix24Client(
            settings.crm_bitrix24_webhook_url,
            entity=settings.crm_bitrix24_entity,
            field_map=field_map,
            source_id=settings.crm_bitrix24_source_id,
            assigned_by_id=settings.crm_bitrix24_assigned_by_id,
            **common,
        )

    if provider in {"amo", "amocrm"}:
        if not settings.crm_amo_base_url or not settings.crm_amo_token:
            raise ValueError(
                "Для CRM_PROVIDER=amo укажите "
                "CRM_AMO_BASE_URL и CRM_AMO_TOKEN"
            )
        return AmoCRMClient(
            settings.crm_amo_base_url,
            settings.crm_amo_token,
            field_map=field_map,
            pipeline_id=settings.crm_amo_pipeline_id,
            status_id=settings.crm_amo_status_id,
            responsible_user_id=settings.crm_amo_responsible_user_id,
            **common,
        )

    raise ValueError(
        "CRM_PROVIDER должен быть webhook, bitrix24 или amo"
    )
