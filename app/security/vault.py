"""Encrypted storage for PII token mappings.

The vault is separate from business tables: call transcripts and LLM results
store tokens, while original values live here for a limited time. In-memory
storage is fine for tests and a single pilot process; production should use
the encrypted SQLite implementation or a Redis/Postgres adapter.
"""

from __future__ import annotations

import base64
import hashlib
import json
import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from cryptography.fernet import Fernet, InvalidToken


@dataclass(frozen=True)
class VaultEntry:
    request_id: str
    mapping: dict[str, str]
    kinds: dict[str, str]
    expires_at: float


class PIIVault(Protocol):
    def put(
        self,
        request_id: str,
        mapping: dict[str, str],
        kinds: dict[str, str],
        ttl_seconds: int,
    ) -> None: ...

    def get(self, request_id: str) -> VaultEntry | None: ...

    def delete(self, request_id: str) -> None: ...

    def purge_expired(self) -> None: ...


class InMemoryPIIVault:
    def __init__(self) -> None:
        self._entries: dict[str, VaultEntry] = {}

    def put(
        self,
        request_id: str,
        mapping: dict[str, str],
        kinds: dict[str, str],
        ttl_seconds: int,
    ) -> None:
        self._entries[request_id] = VaultEntry(
            request_id=request_id,
            mapping=dict(mapping),
            kinds=dict(kinds),
            expires_at=time.time() + ttl_seconds,
        )

    def get(self, request_id: str) -> VaultEntry | None:
        entry = self._entries.get(request_id)
        if entry is None:
            return None
        if entry.expires_at <= time.time():
            self._entries.pop(request_id, None)
            return None
        return entry

    def delete(self, request_id: str) -> None:
        self._entries.pop(request_id, None)

    def purge_expired(self) -> None:
        now = time.time()
        expired = [
            key for key, entry in self._entries.items() if entry.expires_at <= now
        ]
        for key in expired:
            self._entries.pop(key, None)


class EncryptedSQLitePIIVault:
    SCHEMA = """
    CREATE TABLE IF NOT EXISTS pii_vault (
        request_id TEXT PRIMARY KEY,
        payload BLOB NOT NULL,
        expires_at REAL NOT NULL,
        created_at REAL NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_pii_vault_expires ON pii_vault(expires_at);
    """

    def __init__(self, path: Path, secret: str) -> None:
        if not secret.strip():
            raise ValueError("PII_VAULT_KEY is required")
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(secret.encode("utf-8")).digest()
        self._fernet = Fernet(base64.urlsafe_b64encode(digest))
        with closing(self._connect()) as connection, connection:
            connection.executescript(self.SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.path), timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def put(
        self,
        request_id: str,
        mapping: dict[str, str],
        kinds: dict[str, str],
        ttl_seconds: int,
    ) -> None:
        payload = json.dumps(
            {"mapping": mapping, "kinds": kinds},
            ensure_ascii=False,
        ).encode("utf-8")
        encrypted = self._fernet.encrypt(payload)
        now = time.time()
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                INSERT INTO pii_vault (request_id, payload, expires_at, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(request_id) DO UPDATE SET
                    payload=excluded.payload,
                    expires_at=excluded.expires_at,
                    created_at=excluded.created_at
                """,
                (request_id, encrypted, now + ttl_seconds, now),
            )

    def get(self, request_id: str) -> VaultEntry | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM pii_vault WHERE request_id = ?",
                (request_id,),
            ).fetchone()
        if row is None:
            return None
        if row["expires_at"] <= time.time():
            self.delete(request_id)
            return None
        try:
            payload = json.loads(
                self._fernet.decrypt(row["payload"]).decode("utf-8")
            )
        except (InvalidToken, ValueError, TypeError):
            return None
        return VaultEntry(
            request_id=row["request_id"],
            mapping=payload.get("mapping") or {},
            kinds=payload.get("kinds") or {},
            expires_at=float(row["expires_at"]),
        )

    def delete(self, request_id: str) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute(
                "DELETE FROM pii_vault WHERE request_id = ?",
                (request_id,),
            )

    def purge_expired(self) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute(
                "DELETE FROM pii_vault WHERE expires_at <= ?",
                (time.time(),),
            )
