"""initial schema

Revision ID: 20261116_0001
Revises:
Create Date: 2026-11-16

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "20261116_0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"
    blob = "BYTEA" if is_postgres else "BLOB"

    statements = [
        """
        CREATE TABLE IF NOT EXISTS processing_log (
            id TEXT PRIMARY KEY,
            scenario TEXT NOT NULL,
            source TEXT NOT NULL,
            input_text TEXT NOT NULL,
            input_hash TEXT NOT NULL,
            status TEXT NOT NULL,
            result_json TEXT NOT NULL,
            raw_response TEXT,
            error TEXT,
            model TEXT NOT NULL,
            temperature REAL NOT NULL,
            latency_ms INTEGER NOT NULL,
            usage_json TEXT NOT NULL,
            metadata_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_log_scenario ON processing_log(scenario)",
        "CREATE INDEX IF NOT EXISTS idx_log_status ON processing_log(status)",
        "CREATE INDEX IF NOT EXISTS idx_log_created ON processing_log(created_at)",
        """
        CREATE TABLE IF NOT EXISTS business_results (
            id TEXT PRIMARY KEY,
            log_id TEXT NOT NULL,
            scenario TEXT NOT NULL,
            status TEXT NOT NULL,
            category TEXT,
            priority TEXT,
            summary TEXT NOT NULL,
            next_action TEXT NOT NULL,
            fields_json TEXT NOT NULL,
            confidence TEXT NOT NULL,
            escalate INTEGER NOT NULL,
            escalate_reason TEXT,
            missing_fields_json TEXT NOT NULL,
            score INTEGER,
            result_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(log_id) REFERENCES processing_log(id)
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_result_scenario ON business_results(scenario)",
        "CREATE INDEX IF NOT EXISTS idx_result_status ON business_results(status)",
        "CREATE INDEX IF NOT EXISTS idx_result_created ON business_results(created_at)",
        """
        CREATE TABLE IF NOT EXISTS demo_calls (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            client TEXT NOT NULL,
            operator TEXT NOT NULL,
            transcript_json TEXT NOT NULL,
            audio_file TEXT,
            created_at TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'demo',
            external_id TEXT,
            duration_ms INTEGER NOT NULL DEFAULT 0,
            audio_mime TEXT,
            audio_deleted_at TEXT
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_demo_calls_external ON demo_calls(source, external_id)",
        """
        CREATE TABLE IF NOT EXISTS call_reviews (
            call_id TEXT PRIMARY KEY,
            request_id TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            reviewer TEXT,
            final_json TEXT,
            changes_json TEXT,
            reason TEXT,
            updated_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            payload TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            attempts INTEGER NOT NULL DEFAULT 0,
            available_at TEXT NOT NULL,
            locked_at TEXT,
            locked_by TEXT,
            last_error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_jobs_pick ON jobs(status, available_at, created_at)",
        f"""
        CREATE TABLE IF NOT EXISTS pii_vault (
            request_id TEXT PRIMARY KEY,
            payload {blob} NOT NULL,
            expires_at REAL NOT NULL,
            created_at REAL NOT NULL
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_pii_vault_expires ON pii_vault(expires_at)",
        """
        CREATE TABLE IF NOT EXISTS crm_webhook_outbox (
            request_id TEXT PRIMARY KEY,
            payload_json TEXT NOT NULL,
            status TEXT NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0,
            last_error TEXT,
            next_attempt_at TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_outbox_due ON crm_webhook_outbox(status, next_attempt_at)",
    ]
    for statement in statements:
        op.execute(statement)


def downgrade() -> None:
    tables = [
        "crm_webhook_outbox",
        "pii_vault",
        "jobs",
        "call_reviews",
        "demo_calls",
        "business_results",
        "processing_log",
    ]
    for table in tables:
        op.execute(f"DROP TABLE IF EXISTS {table}")
