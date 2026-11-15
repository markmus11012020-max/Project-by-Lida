from __future__ import annotations

import os
from typing import Any

import pytest

from app.db import Database
from app.db_compat import DBConnection


class FakeConnection:
    def __init__(self) -> None:
        self.executed: list[tuple[str, Any]] = []
        self.scripts: list[str] = []
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def execute(self, sql: str, params: Any = ()) -> "FakeConnection":
        self.executed.append((sql, params))
        return self

    def executescript(self, script: str) -> None:
        self.scripts.append(script)

    def fetchall(self):
        return []

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        self.closed = True


def test_postgres_placeholders_and_executescript() -> None:
    raw = FakeConnection()
    connection = DBConnection(raw, postgres=True)

    connection.execute("SELECT ? AS value", ("x",))
    assert raw.executed == [("SELECT %s AS value", ("x",))]

    connection.executescript("CREATE TABLE a (id TEXT); CREATE INDEX i ON a(id);")
    assert len(raw.executed) == 3
    assert "CREATE TABLE" in raw.executed[1][0]


def test_sqlite_uses_question_marks() -> None:
    raw = FakeConnection()
    connection = DBConnection(raw, postgres=False)

    connection.execute("SELECT ? AS value", ("x",))
    assert raw.executed == [("SELECT ? AS value", ("x",))]


def test_context_manager_commits_and_rolls_back() -> None:
    raw = FakeConnection()
    connection = DBConnection(raw, postgres=False)

    with connection:
        pass
    assert raw.commits == 1

    try:
        with connection:
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    assert raw.rollbacks == 1


@pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="TEST_DATABASE_URL is not set",
)
def test_postgres_database_init() -> None:
    database = Database(url=os.environ["TEST_DATABASE_URL"])
    database.init()
    assert database.health() is True

