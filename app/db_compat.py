"""Small SQLite/PostgreSQL compatibility layer.

The existing repositories use ``?`` placeholders and ``executescript``.
This wrapper keeps their SQL mostly unchanged while allowing a PostgreSQL
connection through DATABASE_URL / CALLPILOT_DB_URL.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Sequence


class DBConnection:
    def __init__(self, connection: Any, postgres: bool) -> None:
        self.connection = connection
        self.postgres = postgres

    def execute(
        self,
        sql: str,
        params: Sequence[Any] = (),
    ):
        if self.postgres:
            sql = sql.replace("?", "%s")
            if params:
                return self.connection.execute(sql, params)
            return self.connection.execute(sql)
        return self.connection.execute(sql, params)

    def executescript(self, script: str) -> None:
        if not self.postgres:
            self.connection.executescript(script)
            return
        for statement in script.split(";"):
            if statement.strip():
                self.connection.execute(statement)

    def columns(self, table: str) -> set[str]:
        if self.postgres:
            rows = self.connection.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = %s AND table_schema = current_schema()
                """,
                (table,),
            ).fetchall()
            return {row["column_name"] for row in rows}
        rows = self.connection.execute(
            f"PRAGMA table_info({table})"
        ).fetchall()
        return {row["name"] for row in rows}

    def commit(self) -> None:
        self.connection.commit()

    def rollback(self) -> None:
        self.connection.rollback()

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "DBConnection":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc_type is None:
            self.commit()
        else:
            self.rollback()


def connect_db(
    path: Path | None = None,
    url: str | None = None,
) -> DBConnection:
    if url:
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError(
                "Для PostgreSQL установите psycopg[binary]"
            ) from exc
        connection = psycopg.connect(
            url,
            row_factory=dict_row,
            connect_timeout=10,
        )
        return DBConnection(connection, True)

    if path is None:
        raise ValueError("Нужен path или url базы данных")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(path), timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA busy_timeout=5000")
    return DBConnection(connection, False)


def is_postgres_url(value: str) -> bool:
    return value.startswith(("postgres://", "postgresql://"))
