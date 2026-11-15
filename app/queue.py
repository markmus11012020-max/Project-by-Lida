"""Durable job queue with SQLite and PostgreSQL backends.

The same schema works on both databases: identifiers and timestamps are TEXT,
payload is JSON text. PostgreSQL uses FOR UPDATE SKIP LOCKED for multiple
workers; SQLite uses BEGIN IMMEDIATE and a single writer.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

JOB_STATUSES = {"pending", "running", "done", "failed"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _future(seconds: float) -> str:
    return (
        datetime.now(timezone.utc) + timedelta(seconds=seconds)
    ).isoformat(timespec="milliseconds")


@dataclass(frozen=True)
class Job:
    id: str
    kind: str
    payload: dict[str, Any]
    status: str
    attempts: int
    available_at: str
    locked_at: str | None
    locked_by: str | None
    last_error: str | None
    created_at: str
    updated_at: str


SCHEMA = """
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
);
CREATE INDEX IF NOT EXISTS idx_jobs_pick
    ON jobs(status, available_at, created_at);
"""


def _row_to_job(row: Mapping[str, Any]) -> Job:
    return Job(
        id=str(row["id"]),
        kind=str(row["kind"]),
        payload=json.loads(row["payload"] or "{}"),
        status=str(row["status"]),
        attempts=int(row["attempts"] or 0),
        available_at=str(row["available_at"]),
        locked_at=row["locked_at"],
        locked_by=row["locked_by"],
        last_error=row["last_error"],
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


class SQLiteJobQueue:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection, connection:
            connection.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.path), timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=10000")
        return connection

    def enqueue(
        self,
        kind: str,
        payload: dict[str, Any],
        delay_seconds: float = 0,
    ) -> str:
        job_id = str(uuid.uuid4())
        now = utc_now()
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                INSERT INTO jobs (
                    id, kind, payload, status, attempts, available_at,
                    locked_at, locked_by, last_error, created_at, updated_at
                ) VALUES (?, ?, ?, 'pending', 0, ?, NULL, NULL, NULL, ?, ?)
                """,
                (
                    job_id,
                    kind,
                    json.dumps(payload, ensure_ascii=False),
                    _future(delay_seconds),
                    now,
                    now,
                ),
            )
        return job_id

    def dequeue(
        self,
        worker_id: str,
        kinds: list[str] | None = None,
    ) -> Job | None:
        now = utc_now()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                kind_sql = ""
                params: list[Any] = [now]
                if kinds:
                    placeholders = ",".join("?" for _ in kinds)
                    kind_sql = f" AND kind IN ({placeholders})"
                    params.extend(kinds)
                row = connection.execute(
                    f"""
                    SELECT * FROM jobs
                    WHERE status = 'pending' AND available_at <= ?{kind_sql}
                    ORDER BY available_at, created_at
                    LIMIT 1
                    """,
                    params,
                ).fetchone()
                if row is None:
                    connection.commit()
                    return None
                connection.execute(
                    """
                    UPDATE jobs SET status='running', attempts=attempts + 1,
                        locked_at=?, locked_by=?, updated_at=?
                    WHERE id=?
                    """,
                    (now, worker_id, now, row["id"]),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            updated = connection.execute(
                "SELECT * FROM jobs WHERE id=?", (row["id"],)
            ).fetchone()
        return _row_to_job(updated) if updated else None

    def complete(self, job_id: str) -> None:
        now = utc_now()
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                UPDATE jobs SET status='done', locked_at=NULL, locked_by=NULL,
                    last_error=NULL, updated_at=?
                WHERE id=?
                """,
                (now, job_id),
            )

    def has_active(self, kind: str) -> bool:
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT 1 FROM jobs
                WHERE kind=? AND status IN ('pending', 'running')
                LIMIT 1
                """,
                (kind,),
            ).fetchone()
        return row is not None

    def fail(
        self,
        job_id: str,
        error: str,
        retry_seconds: float | None = None,
    ) -> None:
        now = utc_now()
        if retry_seconds is None:
            status = "failed"
            available = now
        else:
            status = "pending"
            available = _future(retry_seconds)
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                UPDATE jobs SET status=?, available_at=?, locked_at=NULL,
                    locked_by=NULL, last_error=?, updated_at=?
                WHERE id=?
                """,
                (status, available, error[:2000], now, job_id),
            )

    def reap_stale(self, older_than_seconds: int = 900) -> int:
        threshold = (
            datetime.now(timezone.utc) - timedelta(seconds=older_than_seconds)
        ).isoformat(timespec="milliseconds")
        with closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                """
                UPDATE jobs SET status='pending', locked_at=NULL,
                    locked_by=NULL, available_at=?, updated_at=?
                WHERE status='running' AND locked_at <= ?
                """,
                (utc_now(), utc_now(), threshold),
            )
        return cursor.rowcount

    def stats(self) -> dict[str, int]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT status, COUNT(*) AS count FROM jobs GROUP BY status"
            ).fetchall()
        return {row["status"]: int(row["count"]) for row in rows}


class PostgresJobQueue:
    def __init__(self, url: str) -> None:
        try:
            import psycopg  # noqa: F401
            from psycopg.rows import dict_row  # noqa: F401
        except ImportError as exc:
            raise RuntimeError(
                "Для PostgreSQL установите psycopg[binary]"
            ) from exc
        self.url = url
        self._psycopg = psycopg
        self._dict_row = dict_row
        with self._connect() as connection:
            for statement in SCHEMA.split(";"):
                if statement.strip():
                    connection.execute(statement)
            connection.commit()

    def _connect(self):
        return self._psycopg.connect(
            self.url,
            row_factory=self._dict_row,
        )

    def enqueue(
        self,
        kind: str,
        payload: dict[str, Any],
        delay_seconds: float = 0,
    ) -> str:
        job_id = str(uuid.uuid4())
        now = utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO jobs (
                    id, kind, payload, status, attempts, available_at,
                    locked_at, locked_by, last_error, created_at, updated_at
                ) VALUES (%s, %s, %s, 'pending', 0, %s, NULL, NULL, NULL, %s, %s)
                """,
                (
                    job_id,
                    kind,
                    json.dumps(payload, ensure_ascii=False),
                    _future(delay_seconds),
                    now,
                    now,
                ),
            )
        return job_id

    def dequeue(
        self,
        worker_id: str,
        kinds: list[str] | None = None,
    ) -> Job | None:
        now = utc_now()
        kind_sql = ""
        params: list[Any] = [now]
        if kinds:
            placeholders = ",".join("%s" for _ in kinds)
            kind_sql = f" AND kind IN ({placeholders})"
            params.extend(kinds)
        with self._connect() as connection:
            row = connection.execute(
                f"""
                WITH picked AS (
                    SELECT id FROM jobs
                    WHERE status='pending' AND available_at <= %s{kind_sql}
                    ORDER BY available_at, created_at
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                )
                UPDATE jobs SET status='running', attempts=attempts + 1,
                    locked_at=%s, locked_by=%s, updated_at=%s
                FROM picked WHERE jobs.id = picked.id
                RETURNING jobs.*
                """,
                [now, *params[1:], now, worker_id, now],
            ).fetchone()
        return _row_to_job(row) if row else None

    def complete(self, job_id: str) -> None:
        now = utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE jobs SET status='done', locked_at=NULL, locked_by=NULL,
                    last_error=NULL, updated_at=%s
                WHERE id=%s
                """,
                (now, job_id),
            )

    def has_active(self, kind: str) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT 1 FROM jobs
                WHERE kind=%s AND status IN ('pending', 'running')
                LIMIT 1
                """,
                (kind,),
            ).fetchone()
        return row is not None

    def fail(
        self,
        job_id: str,
        error: str,
        retry_seconds: float | None = None,
    ) -> None:
        now = utc_now()
        status = "failed" if retry_seconds is None else "pending"
        available = now if retry_seconds is None else _future(retry_seconds)
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE jobs SET status=%s, available_at=%s, locked_at=NULL,
                    locked_by=NULL, last_error=%s, updated_at=%s
                WHERE id=%s
                """,
                (status, available, error[:2000], now, job_id),
            )

    def reap_stale(self, older_than_seconds: int = 900) -> int:
        threshold = (
            datetime.now(timezone.utc) - timedelta(seconds=older_than_seconds)
        ).isoformat(timespec="milliseconds")
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE jobs SET status='pending', locked_at=NULL,
                    locked_by=NULL, available_at=%s, updated_at=%s
                WHERE status='running' AND locked_at <= %s
                """,
                (utc_now(), utc_now(), threshold),
            )
            return cursor.rowcount

    def stats(self) -> dict[str, int]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT status, COUNT(*) AS count FROM jobs GROUP BY status"
            ).fetchall()
        return {row["status"]: int(row["count"]) for row in rows}


def create_queue(url: str):
    if url.startswith(("postgres://", "postgresql://")):
        return PostgresJobQueue(url)
    if url.startswith("sqlite:///"):
        return SQLiteJobQueue(Path(url[10:]))
    return SQLiteJobQueue(Path(url))
