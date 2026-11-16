"""landing leads

Revision ID: 20261116_0002
Revises: 20261116_0001
Create Date: 2026-11-16

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "20261116_0002"
down_revision: Union[str, Sequence[str], None] = "20261116_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS leads (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            company TEXT,
            contact TEXT NOT NULL,
            volume TEXT,
            phone_system TEXT,
            comment TEXT,
            consent INTEGER NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS leads")
