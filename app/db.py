"""SQLite storage: audit journal plus business results."""

from __future__ import annotations

import json
from contextlib import closing
from pathlib import Path
from typing import Any

from app.db_compat import DBConnection, connect_db
from app.pricing import cost_from_usage

SCHEMA = """
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
);

CREATE INDEX IF NOT EXISTS idx_log_scenario ON processing_log(scenario);
CREATE INDEX IF NOT EXISTS idx_log_status ON processing_log(status);
CREATE INDEX IF NOT EXISTS idx_log_created ON processing_log(created_at);

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
);

CREATE INDEX IF NOT EXISTS idx_result_scenario ON business_results(scenario);
CREATE INDEX IF NOT EXISTS idx_result_status ON business_results(status);
CREATE INDEX IF NOT EXISTS idx_result_created ON business_results(created_at);
"""


def _loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


def _text(value: Any) -> str:
    return str(getattr(value, "value", value))


class Database:
    def __init__(
        self,
        path: Path | None = None,
        url: str | None = None,
    ) -> None:
        self.path = Path(path) if path is not None else None
        self.url = url or None

    def _connect(self) -> DBConnection:
        return connect_db(self.path, self.url)

    def init(self) -> None:
        with closing(self._connect()) as connection, connection:
            connection.executescript(SCHEMA)

    def health(self) -> bool:
        with closing(self._connect()) as connection:
            row = connection.execute("SELECT 1 AS ok").fetchone()
        return bool(row and row["ok"] == 1)

    def save(
        self,
        log: dict[str, Any],
        result: dict[str, Any],
    ) -> None:
        if not isinstance(result, dict):
            raise ValueError("result must be a dictionary")

        result_json = json.dumps(result, ensure_ascii=False)
        fields_json = json.dumps(result.get("fields") or {}, ensure_ascii=False)
        missing_fields_json = json.dumps(
            result.get("missing_fields") or [], ensure_ascii=False
        )
        score = result.get("score")
        score = int(score) if isinstance(score, (int, float)) else None

        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                INSERT INTO processing_log (
                    id, scenario, source, input_text, input_hash, status,
                    result_json, raw_response, error, model, temperature,
                    latency_ms, usage_json, metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    log["id"],
                    _text(log["scenario"]),
                    log.get("source", "api"),
                    log["input_text"],
                    log["input_hash"],
                    _text(log["status"]),
                    result_json,
                    log.get("raw_response"),
                    log.get("error"),
                    log.get("model", ""),
                    float(log.get("temperature", 0.2)),
                    int(log.get("latency_ms", 0)),
                    json.dumps(log.get("usage") or {}, ensure_ascii=False),
                    json.dumps(log.get("metadata") or {}, ensure_ascii=False),
                    log["created_at"],
                ),
            )
            connection.execute(
                """
                INSERT INTO business_results (
                    id, log_id, scenario, status, category, priority, summary,
                    next_action, fields_json, confidence, escalate,
                    escalate_reason, missing_fields_json, score, result_json,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    log["id"],
                    log["id"],
                    _text(log["scenario"]),
                    _text(log["status"]),
                    _text(result.get("category")) if result.get("category") else None,
                    _text(result.get("priority")) if result.get("priority") else None,
                    str(result.get("summary") or ""),
                    str(result.get("next_action") or ""),
                    fields_json,
                    _text(result.get("confidence")) if result.get("confidence") else "",
                    1 if result.get("escalate") else 0,
                    result.get("escalate_reason"),
                    missing_fields_json,
                    score,
                    result_json,
                    log["created_at"],
                ),
            )

    @staticmethod
    def _result_from_row(row: Any) -> dict[str, Any]:
        return {
            "request_id": row["id"],
            "scenario": row["scenario"],
            "status": row["status"],
            "result": _loads(row["result_json"], {}),
            "meta": {
                "model": row["model"],
                "temperature": row["temperature"],
                "latency_ms": row["latency_ms"],
                "created_at": row["created_at"],
                "usage": _loads(row["usage_json"], {}),
            },
            "error": row["error"],
        }

    def list_results(
        self,
        scenario: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        where: list[str] = []
        params: list[Any] = []
        if scenario:
            where.append("b.scenario = ?")
            params.append(scenario)
        if status:
            where.append("b.status = ?")
            params.append(status)

        clause = ("WHERE " + " AND ".join(where)) if where else ""
        params.extend([max(1, min(limit, 200)), max(0, offset)])
        query = f"""
            SELECT b.id, b.scenario, b.status, b.result_json, b.created_at,
                   l.model, l.temperature, l.latency_ms, l.usage_json, l.error
            FROM business_results b
            JOIN processing_log l ON l.id = b.log_id
            {clause}
            ORDER BY b.created_at DESC
            LIMIT ? OFFSET ?
        """
        with closing(self._connect()) as connection:
            rows = connection.execute(query, params).fetchall()
        return [self._result_from_row(row) for row in rows]

    def get_result(self, request_id: str) -> dict[str, Any] | None:
        query = """
            SELECT b.id, b.scenario, b.status, b.result_json, b.created_at,
                   l.model, l.temperature, l.latency_ms, l.usage_json, l.error
            FROM business_results b
            JOIN processing_log l ON l.id = b.log_id
            WHERE b.id = ?
        """
        with closing(self._connect()) as connection:
            row = connection.execute(query, (request_id,)).fetchone()
        return self._result_from_row(row) if row else None

    def get_audit(
        self,
        request_id: str,
        include_raw: bool = False,
    ) -> dict[str, Any] | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM processing_log WHERE id = ?", (request_id,)
            ).fetchone()
        if row is None:
            return None
        return {
            "request_id": row["id"],
            "scenario": row["scenario"],
            "source": row["source"],
            "input_text": row["input_text"],
            "input_hash": row["input_hash"],
            "status": row["status"],
            "result": _loads(row["result_json"], {}),
            "raw_response": row["raw_response"] if include_raw else None,
            "raw_response_available": bool(row["raw_response"]),
            "error": row["error"],
            "model": row["model"],
            "temperature": row["temperature"],
            "latency_ms": row["latency_ms"],
            "usage": _loads(row["usage_json"], {}),
            "metadata": _loads(row["metadata_json"], {}),
            "created_at": row["created_at"],
        }

    def stats(self) -> dict[str, Any]:
        with closing(self._connect()) as connection:
            total = connection.execute(
                "SELECT COUNT(*) AS count FROM processing_log"
            ).fetchone()["count"]
            rows = connection.execute(
                """
                SELECT scenario, status, COUNT(*) AS count
                FROM processing_log
                GROUP BY scenario, status
                ORDER BY scenario, status
                """
            ).fetchall()
            avg_latency = connection.execute(
                "SELECT AVG(latency_ms) AS avg_latency FROM processing_log"
            ).fetchone()["avg_latency"]
            usage_rows = connection.execute(
                "SELECT model, usage_json FROM processing_log"
            ).fetchall()

        by_scenario: dict[str, dict[str, int]] = {}
        by_status: dict[str, int] = {}
        for row in rows:
            scenario = row["scenario"]
            status = row["status"]
            count = int(row["count"])
            by_scenario.setdefault(scenario, {})[status] = count
            by_status[status] = by_status.get(status, 0) + count

        total_cost = 0.0
        prompt_tokens = 0
        completion_tokens = 0
        for row in usage_rows:
            usage = _loads(row["usage_json"], {})
            total_cost += cost_from_usage(usage, row["model"])
            try:
                prompt_tokens += int(usage.get("prompt_tokens") or 0)
                completion_tokens += int(usage.get("completion_tokens") or 0)
            except (TypeError, ValueError):
                pass

        processed = by_status.get("processed", 0)
        return {
            "total_requests": int(total),
            "by_scenario": by_scenario,
            "by_status": by_status,
            "avg_latency_ms": round(float(avg_latency or 0), 1),
            "total_cost_rub": round(total_cost, 6),
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "automation_rate": round(processed / total, 4) if total else 0.0,
            "escalation_rate": round((total - processed) / total, 4)
            if total
            else 0.0,
        }

    def export_results(self) -> list[dict[str, Any]]:
        query = """
            SELECT b.id, b.scenario, b.status, b.result_json, b.created_at,
                   l.model, l.temperature, l.latency_ms, l.usage_json, l.error
            FROM business_results b
            JOIN processing_log l ON l.id = b.log_id
            ORDER BY b.created_at ASC
        """
        with closing(self._connect()) as connection:
            rows = connection.execute(query).fetchall()
        return [self._result_from_row(row) for row in rows]

    def export_audit(self) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT * FROM processing_log ORDER BY created_at ASC"
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            result.append(
                {
                    "request_id": row["id"],
                    "scenario": row["scenario"],
                    "source": row["source"],
                    "input_text": row["input_text"],
                    "input_hash": row["input_hash"],
                    "status": row["status"],
                    "result": _loads(row["result_json"], {}),
                    "raw_response": row["raw_response"],
                    "error": row["error"],
                    "model": row["model"],
                    "temperature": row["temperature"],
                    "latency_ms": row["latency_ms"],
                    "usage": _loads(row["usage_json"], {}),
                    "metadata": _loads(row["metadata_json"], {}),
                    "created_at": row["created_at"],
                }
            )
        return result
