"""External integrations for the V2 pipeline."""

from app.integrations.crm_amo import AmoCRMClient
from app.integrations.crm_bitrix24 import Bitrix24Client
from app.integrations.crm_common import build_note, load_field_map
from app.integrations.crm_factory import build_crm_client
from app.integrations.crm_webhook import (
    CRMWebhookClient,
    WebhookDelivery,
    WebhookOutbox,
    retry_at,
    sign_payload,
)
from app.integrations.dispatcher import (
    DEFAULT_ALLOWED_KINDS,
    DispatchReport,
    OutboxDispatcher,
    restore_client_fields,
)
from app.integrations.oktell import (
    OktellCall,
    OktellClient,
    OktellError,
    OktellSync,
    OktellSyncReport,
)

__all__ = [
    "AmoCRMClient",
    "Bitrix24Client",
    "CRMWebhookClient",
    "DEFAULT_ALLOWED_KINDS",
    "build_crm_client",
    "build_note",
    "load_field_map",
    "DispatchReport",
    "OktellCall",
    "OktellClient",
    "OktellError",
    "OktellSync",
    "OktellSyncReport",
    "OutboxDispatcher",
    "WebhookDelivery",
    "WebhookOutbox",
    "restore_client_fields",
    "retry_at",
    "sign_payload",
]
