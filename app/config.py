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
    log_level: str = Field(default="INFO")
    debug: bool = Field(default=False)

    @field_validator("database_path", mode="after")
    @classmethod
    def resolve_database_path(cls, value: Path) -> Path:
        if value.is_absolute():
            return value
        return (BASE_DIR / value).resolve()

    @property
    def llm_configured(self) -> bool:
        key = self.aitunnel_api_key.strip()
        placeholders = {"", "sk-your-key-here", "sk-aitunnel-xxx"}
        return bool(key) and key not in placeholders


@lru_cache
def get_settings() -> Settings:
    return Settings()
