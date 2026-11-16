from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config


def _config(url: str) -> Config:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    return config


def test_sqlite_upgrade_creates_core_tables(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("CALLPILOT_DB_URL", raising=False)
    path = tmp_path / "migrations.db"

    command.upgrade(_config(f"sqlite:///{path}"), "head")

    with sqlite3.connect(path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(demo_calls)")
        }

    assert {
        "alembic_version",
        "processing_log",
        "business_results",
        "demo_calls",
        "call_reviews",
        "jobs",
        "pii_vault",
        "crm_webhook_outbox",
        "leads",
    } <= tables
    assert {"source", "audio_mime", "audio_deleted_at"} <= columns


@pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="TEST_DATABASE_URL is not set",
)
def test_postgres_upgrade() -> None:
    command.upgrade(_config(os.environ["TEST_DATABASE_URL"]), "head")
