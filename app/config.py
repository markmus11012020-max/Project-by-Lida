"""Application settings loaded from environment variables and .env."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Runtime configuration.

    Environment variable names are case-insensitive: aitunnel_api_key
    is read from AITUNNEL_API_KEY, database_path from DATABASE_PATH, etc.
    """

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "LLM Process Automation MVP"
    app_version: str = "1.0.0"

    aitunnel_api_key: str = Field(default="")
    aitunnel_base_url: str = Field(default="https://api.aitunnel.ru/v1/")
    aitunnel_model: str = Field(default="gpt-4o-mini")
    aitunnel_temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    aitunnel_max_tokens: int = Field(default=2500, ge=1, le=32000)
    aitunnel_timeout: float = Field(default=60.0, gt=0)

    database_path: Path = Field(default=BASE_DIR / "data" / "app.db")
    database_url: str = Field(default="")
    callpilot_db_url: str = Field(default="")
    log_level: str = Field(default="INFO")
    debug: bool = Field(default=False)

    stt_api_url: str = Field(default="")
    stt_api_key: str = Field(default="")
    stt_model: str = Field(default="whisper-1")
    stt_timeout: float = Field(default=120.0, gt=0)
    audio_max_bytes: int = Field(default=50 * 1024 * 1024, ge=1)
    audio_url_allowlist: str = Field(default="")

    audio_encryption_key: str = Field(default="")
    audio_key_path: Path = Field(default=BASE_DIR / "data" / "audio.key")
    audio_retention_days: int = Field(default=30, ge=0)

    schema_auto_create: bool = Field(default=True)
    demo_mode: bool = Field(default=False)

    pii_vault_key: str = Field(default="")
    pii_vault_path: Path = Field(default=BASE_DIR / "data" / "pii_vault.db")
    pii_vault_ttl_seconds: int = Field(default=86400, ge=60)

    crm_enabled: bool = Field(default=False)
    crm_provider: str = Field(default="webhook")
    crm_timeout: float = Field(default=10.0, gt=0)
    crm_max_attempts: int = Field(default=3, ge=1, le=10)
    crm_field_map: str = Field(default="")

    crm_webhook_enabled: bool = Field(default=False)
    crm_webhook_url: str = Field(default="")
    crm_webhook_secret: str = Field(default="")
    crm_outbox_path: Path = Field(default=BASE_DIR / "data" / "crm_outbox.db")

    crm_bitrix24_webhook_url: str = Field(default="")
    crm_bitrix24_entity: str = Field(default="lead")
    crm_bitrix24_source_id: str = Field(default="")
    crm_bitrix24_assigned_by_id: int = Field(default=0, ge=0)

    crm_amo_base_url: str = Field(default="")
    crm_amo_token: str = Field(default="")
    crm_amo_pipeline_id: int = Field(default=0, ge=0)
    crm_amo_status_id: int = Field(default=0, ge=0)
    crm_amo_responsible_user_id: int = Field(default=0, ge=0)

    oktell_enabled: bool = Field(default=False)
    oktell_base_url: str = Field(default="")
    oktell_api_key: str = Field(default="")
    oktell_username: str = Field(default="")
    oktell_password: str = Field(default="")
    oktell_calls_path: str = Field(default="/api/v1/calls")
    oktell_page_size: int = Field(default=100, ge=1, le=1000)
    oktell_timeout: float = Field(default=30.0, gt=0)
    oktell_recording_allowlist: str = Field(default="")
    oktell_since_param: str = Field(default="from")
    oktell_verify_ssl: bool = Field(default=True)

    callpilot_async_upload: bool = Field(default=False)
    callpilot_queue_url: str = Field(
        default="sqlite:///call-center/data/queue.db"
    )

    mail_enabled: bool = Field(default=False)
    smtp_host: str = Field(default="smtp.mail.ru")
    smtp_port: int = Field(default=465, ge=1, le=65535)
    smtp_username: str = Field(default="")
    smtp_password: str = Field(default="")
    smtp_from: str = Field(default="")
    lead_notify_to: str = Field(default="aillix@mail.ru")
    smtp_use_ssl: bool = Field(default=True)
    smtp_starttls: bool = Field(default=False)
    smtp_timeout: float = Field(default=15.0, gt=0)

    oktell_sync_interval_seconds: int = Field(default=300, ge=10)
    crm_dispatch_interval_seconds: int = Field(default=60, ge=10)
    retention_interval_seconds: int = Field(default=86400, ge=60)

    @field_validator("database_path", "pii_vault_path", "crm_outbox_path", "audio_key_path", mode="after")
    @classmethod
    def resolve_path(cls, value: Path) -> Path:
        if value.is_absolute():
            return value
        return (BASE_DIR / value).resolve()

    @property
    def llm_configured(self) -> bool:
        key = self.aitunnel_api_key.strip()
        placeholders = {"", "sk-your-key-here", "sk-aitunnel-xxx"}
        return bool(key) and key not in placeholders

    @property
    def stt_configured(self) -> bool:
        return bool(self.stt_api_url.strip())

    @property
    def oktell_configured(self) -> bool:
        return bool(self.oktell_base_url.strip())

    @property
    def crm_outbox_enabled(self) -> bool:
        """True when any CRM provider is enabled.

        ``crm_webhook_enabled`` is kept for backward compatibility with
        the original webhook-only configuration.
        """

        return bool(self.crm_enabled or self.crm_webhook_enabled)


@lru_cache
def get_settings() -> Settings:
    return Settings()
