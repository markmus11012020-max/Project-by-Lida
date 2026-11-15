"""Demo data, review workflow and metrics for CallPilot."""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import sys
import uuid
from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CALL_CENTER_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CALL_CENTER_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(CALL_CENTER_DIR))

from app.audio import (  # noqa: E402
    STTClient,
    STTError,
    STTResult,
    STTSegment,
    speaker_label,
    transcript_text,
    validate_audio_file,
)
from app.config import Settings  # noqa: E402
from app.db import Database  # noqa: E402
from app.llm import AITunnelClient  # noqa: E402
from app.scenarios.call_qa import call_qa_qc  # noqa: E402
from app.scenarios.registry import SCENARIOS  # noqa: E402
from app.schemas import CallResult, ScenarioKey  # noqa: E402
from app.service import ProcessService  # noqa: E402
from demo_data import DEMO_CALLS, transcript_text as demo_transcript_text  # noqa: E402

CALL_SCHEMA = """
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
    duration_ms INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS call_reviews (
    call_id TEXT PRIMARY KEY,
    request_id TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    reviewer TEXT,
    final_json TEXT,
    changes_json TEXT,
    reason TEXT,
    updated_at TEXT NOT NULL
);
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _json_loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


def _flatten(data: Any, prefix: str = "") -> dict[str, Any]:
    result: dict[str, Any] = {}
    if isinstance(data, dict):
        for key, value in data.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            result.update(_flatten(value, path))
    elif isinstance(data, list):
        result[prefix] = json.dumps(data, ensure_ascii=False, sort_keys=True)
    else:
        result[prefix] = data
    return result


def diff_results(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    old = _flatten(before)
    new = _flatten(after)
    changes: dict[str, Any] = {}
    for key in sorted(set(old) | set(new)):
        if old.get(key) != new.get(key):
            changes[key] = {"from": old.get(key), "to": new.get(key)}
    return changes


class CallStore:
    def __init__(
        self,
        settings: Settings,
        db_path: Path,
        stt_client: STTClient | None = None,
        audio_dir: Path | None = None,
    ) -> None:
        self.settings = settings
        self.db_path = Path(db_path)
        self.audio_dir = Path(audio_dir) if audio_dir else (
            CALL_CENTER_DIR / "static" / "audio"
        )
        self.core_db = Database(self.db_path)
        self.core_db.init()
        self._init_call_tables()
        self._seed_calls()
        self._seed_cached_results()
        self.service = ProcessService(
            settings=settings,
            db=self.core_db,
            llm=AITunnelClient(settings),
            scenarios=SCENARIOS,
        )
        self.stt_client = stt_client or (
            STTClient(
                settings.stt_api_url,
                api_key=settings.stt_api_key,
                model=settings.stt_model,
                timeout=settings.stt_timeout,
            )
            if settings.stt_configured
            else None
        )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.db_path), timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=5000")
        return connection

    def _init_call_tables(self) -> None:
        with closing(self._connect()) as connection, connection:
            connection.executescript(CALL_SCHEMA)
            self._ensure_columns(connection)

    @staticmethod
    def _ensure_columns(connection: sqlite3.Connection) -> None:
        existing = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(demo_calls)")
        }
        columns = {
            "source": "TEXT NOT NULL DEFAULT 'demo'",
            "external_id": "TEXT",
            "duration_ms": "INTEGER NOT NULL DEFAULT 0",
        }
        for name, definition in columns.items():
            if name not in existing:
                connection.execute(
                    f"ALTER TABLE demo_calls ADD COLUMN {name} {definition}"
                )

    def _seed_calls(self) -> None:
        with closing(self._connect()) as connection, connection:
            for call in DEMO_CALLS:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO demo_calls
                    (id, title, client, operator, transcript_json, audio_file, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        call["id"],
                        call["title"],
                        call["client"],
                        call["operator"],
                        json.dumps(call["segments"], ensure_ascii=False),
                        f"{call['id']}.mp3",
                        utc_now(),
                    ),
                )

    def _seed_cached_results(self) -> None:
        seed_path = CALL_CENTER_DIR / "data" / "seed_results.json"
        if not seed_path.exists():
            return
        with closing(self._connect()) as connection:
            existing = connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM call_reviews r
                JOIN demo_calls c ON c.id = r.call_id
                WHERE c.source = 'demo'
                """
            ).fetchone()["count"]
        if existing:
            return

        payload = json.loads(seed_path.read_text(encoding="utf-8"))
        for call_id, item in payload.items():
            input_text = item["input_text"]
            result = item["result"]
            meta = item["meta"]
            request_id = item["request_id"]
            log = {
                "id": request_id,
                "scenario": ScenarioKey.CALL_QA,
                "source": "demo",
                "input_text": input_text,
                "input_hash": hashlib.sha256(
                    input_text.encode("utf-8")
                ).hexdigest(),
                "status": "escalated" if result.get("escalate") else "processed",
                "raw_response": item.get("raw_response"),
                "error": item.get("error"),
                "model": meta.get("model", "demo"),
                "temperature": meta.get("temperature", 0.2),
                "latency_ms": meta.get("latency_ms", 0),
                "usage": meta.get("usage", {}),
                "metadata": {"call_id": call_id},
                "created_at": meta.get("created_at", utc_now()),
            }
            self.core_db.save(log, result)
            with closing(self._connect()) as connection, connection:
                connection.execute(
                    """
                    INSERT OR REPLACE INTO call_reviews
                    (call_id, request_id, status, reviewer, final_json,
                     changes_json, reason, updated_at)
                    VALUES (?, ?, 'pending', NULL, NULL, NULL, NULL, ?)
                    """,
                    (call_id, request_id, utc_now()),
                )

    def _audio_manifest(self) -> dict[str, Any]:
        path = CALL_CENTER_DIR / "data" / "audio_manifest.json"
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def _row_to_call(self, row: sqlite3.Row, manifest: dict[str, Any]) -> dict[str, Any]:
        transcript = _json_loads(row["transcript_json"], [])
        audio_meta = manifest.get(row["id"], {})
        timings = {
            segment["id"]: segment
            for segment in audio_meta.get("segments", [])
        }
        segments: list[dict[str, Any]] = []
        for segment in transcript:
            timing = timings.get(segment["id"], {})
            segments.append(
                {
                    **segment,
                    "start_ms": segment.get(
                        "start_ms", timing.get("start_ms", 0)
                    ),
                    "end_ms": segment.get(
                        "end_ms", timing.get("end_ms", 0)
                    ),
                }
            )

        draft = _json_loads(row["result_json"], None)
        final = _json_loads(row["final_json"], None)
        display = final or draft
        review_status = row["review_status"] or "new"
        audio_file = row["audio_file"]
        audio_path = self.audio_dir / (audio_file or "")
        return {
            "id": row["id"],
            "title": row["title"],
            "client": row["client"],
            "operator": row["operator"],
            "source": row["source"] or "demo",
            "external_id": row["external_id"],
            "segments": segments,
            "transcript": demo_transcript_text(
                {"segments": transcript}
            ) if transcript else "",
            "audio_file": audio_file,
            "audio_url": f"/static/audio/{audio_file}"
            if audio_file and audio_path.exists()
            else None,
            "duration_ms": row["duration_ms"] or audio_meta.get("duration_ms", 0),
            "review_status": review_status,
            "reviewer": row["reviewer"],
            "review_reason": row["reason"],
            "review_updated_at": row["updated_at"],
            "request_id": row["request_id"],
            "draft_result": draft,
            "final_result": final,
            "result": display,
            "meta": {
                "model": row["model"],
                "temperature": row["temperature"],
                "latency_ms": row["latency_ms"],
                "created_at": row["created_at"],
                "usage": _json_loads(row["usage_json"], {}),
                "processing_status": row["processing_status"],
                "error": row["error"],
            },
            "changes": _json_loads(row["changes_json"], {}),
            "qa_score": (display or {}).get("qa_score"),
            "auto_qa_status": (display or {}).get("auto_qa_status", "new"),
            "intent": (display or {}).get("intent"),
            "confidence": (display or {}).get("confidence"),
        }

    _SELECT = """
        SELECT c.id, c.title, c.client, c.operator, c.transcript_json, c.audio_file,
               c.source, c.external_id, c.duration_ms,
               r.request_id, r.status AS review_status, r.reviewer, r.final_json,
               r.changes_json, r.reason, r.updated_at,
               b.result_json, b.status AS processing_status,
               l.model, l.temperature, l.latency_ms, l.usage_json,
               l.created_at, l.error
        FROM demo_calls c
        LEFT JOIN call_reviews r ON r.call_id = c.id
        LEFT JOIN business_results b ON b.id = r.request_id
        LEFT JOIN processing_log l ON l.id = r.request_id
    """

    def list_calls(self, source: str | None = None) -> list[dict[str, Any]]:
        manifest = self._audio_manifest()
        query = self._SELECT
        params: tuple[Any, ...] = ()
        if source and source != "all":
            query += " WHERE c.source = ?"
            params = (source,)
        query += " ORDER BY c.created_at DESC, c.id"
        with closing(self._connect()) as connection:
            rows = connection.execute(query, params).fetchall()
        return [self._row_to_call(row, manifest) for row in rows]

    def get_call(self, call_id: str) -> dict[str, Any] | None:
        manifest = self._audio_manifest()
        with closing(self._connect()) as connection:
            row = connection.execute(
                self._SELECT + " WHERE c.id = ?", (call_id,)
            ).fetchone()
        return self._row_to_call(row, manifest) if row else None

    def _demo_transcript(self, call_id: str) -> str:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT transcript_json FROM demo_calls WHERE id = ?",
                (call_id,),
            ).fetchone()
        if not row:
            raise KeyError(call_id)
        segments = _json_loads(row["transcript_json"], [])
        return demo_transcript_text({"segments": segments})

    def ingest_audio(
        self,
        audio_path: Path,
        filename: str,
        title: str = "",
        external_id: str | None = None,
    ) -> str:
        """Transcribe a real recording, run QA and add it to the review queue."""

        if self.stt_client is None:
            raise RuntimeError("STT не настроен: укажите STT_API_URL")

        info = validate_audio_file(
            audio_path,
            filename=filename,
            max_bytes=self.settings.audio_max_bytes,
        )
        stt_result = self.stt_client.transcribe(audio_path, filename)
        segments = stt_result.segments
        if not segments:
            segments = [
                STTSegment(
                    speaker=None,
                    start=0.0,
                    end=info.duration_ms / 1000,
                    text=stt_result.text,
                )
            ]

        session = self.service.anonymizer.session()
        masked_segments: list[dict[str, Any]] = []
        stt_segments: list[STTSegment] = []
        for index, segment in enumerate(segments, start=1):
            masked_text = session.anonymize(segment.text).text
            start_ms = int((segment.start or 0) * 1000)
            end_ms = int((segment.end or 0) * 1000)
            masked_segments.append(
                {
                    "id": f"s{index}",
                    "speaker": speaker_label(segment.speaker),
                    "text": masked_text,
                    "start_ms": start_ms,
                    "end_ms": end_ms,
                }
            )
            stt_segments.append(
                STTSegment(
                    speaker=segment.speaker,
                    start=segment.start,
                    end=segment.end,
                    text=masked_text,
                )
            )

        transcript = transcript_text(
            STTResult(text=stt_result.text, segments=stt_segments)
        )
        response = self.service.process(
            scenario_key=ScenarioKey.CALL_QA,
            text=transcript,
            source="audio",
            metadata={
                "call_source": "real",
                "audio_filename": filename,
                "external_id": external_id or "",
            },
            masking_session=session,
        )

        stored = self.service.get_result(response.request_id)
        stored_result = (stored or {}).get("result") or {}
        fields = stored_result.get("fields") or {}
        client = str(
            fields.get("client_name")
            or fields.get("contact_name")
            or "—"
        )
        call_id = f"real_{uuid.uuid4().hex[:10]}"
        audio_dir = self.audio_dir / "real"
        audio_dir.mkdir(parents=True, exist_ok=True)
        audio_file = f"real/{call_id}{info.extension}"
        shutil.copyfile(audio_path, self.audio_dir / audio_file)

        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                INSERT INTO demo_calls (
                    id, title, client, operator, transcript_json, audio_file,
                    created_at, source, external_id, duration_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'real', ?, ?)
                """,
                (
                    call_id,
                    title or f"Звонок {external_id or call_id[-6:]}",
                    client,
                    "Оператор",
                    json.dumps(masked_segments, ensure_ascii=False),
                    audio_file,
                    utc_now(),
                    external_id,
                    info.duration_ms,
                ),
            )
            connection.execute(
                """
                INSERT INTO call_reviews
                (call_id, request_id, status, reviewer, final_json,
                 changes_json, reason, updated_at)
                VALUES (?, ?, 'pending', NULL, NULL, NULL, NULL, ?)
                """,
                (call_id, response.request_id, utc_now()),
            )
        return call_id

    def process_call(self, call_id: str, source: str = "call_center"):
        call = self.get_call(call_id)
        if call is None:
            raise KeyError(call_id)
        text = self._demo_transcript(call_id)
        response = self.service.process(
            scenario_key=ScenarioKey.CALL_QA,
            text=text,
            source=source,
            metadata={"call_id": call_id},
        )
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                INSERT INTO call_reviews
                (call_id, request_id, status, reviewer, final_json,
                 changes_json, reason, updated_at)
                VALUES (?, ?, 'pending', NULL, NULL, NULL, NULL, ?)
                ON CONFLICT(call_id) DO UPDATE SET
                    request_id = excluded.request_id,
                    status = 'pending',
                    reviewer = NULL,
                    final_json = NULL,
                    changes_json = NULL,
                    reason = NULL,
                    updated_at = excluded.updated_at
                """,
                (call_id, response.request_id, utc_now()),
            )
        return response

    def confirm_call(
        self,
        call_id: str,
        final_result: dict[str, Any],
        reviewer: str,
        reason: str = "",
    ) -> dict[str, Any]:
        call = self.get_call(call_id)
        if call is None:
            raise KeyError(call_id)
        if not call.get("draft_result"):
            raise ValueError("Сначала обработайте звонок моделью")
        already_confirmed = call.get("review_status") == "confirmed"
        validated = CallResult.model_validate(final_result)
        call_qa_qc(validated)
        final_json = validated.model_dump(mode="json")
        changes = diff_results(call["draft_result"], final_json)
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                UPDATE call_reviews
                SET status='confirmed', reviewer=?, final_json=?,
                    changes_json=?, reason=?, updated_at=?
                WHERE call_id=?
                """,
                (
                    reviewer or "Менеджер",
                    json.dumps(final_json, ensure_ascii=False),
                    json.dumps(changes, ensure_ascii=False),
                    reason.strip() or None,
                    utc_now(),
                    call_id,
                ),
            )
        if (
            not already_confirmed
            and call.get("source") == "real"
            and call.get("request_id")
            and call.get("draft_result")
        ):
            self.service.enqueue_crm(
                str(call["request_id"]),
                call["draft_result"],
            )
        return self.get_call(call_id) or call

    def reject_call(
        self,
        call_id: str,
        reviewer: str,
        reason: str,
    ) -> dict[str, Any]:
        call = self.get_call(call_id)
        if call is None:
            raise KeyError(call_id)
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                UPDATE call_reviews
                SET status='rejected', reviewer=?, reason=?, updated_at=?
                WHERE call_id=?
                """,
                (reviewer or "Менеджер", reason.strip(), utc_now(), call_id),
            )
        return self.get_call(call_id) or call

    def reset_demo(self) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                DELETE FROM business_results
                WHERE id IN (
                    SELECT r.request_id FROM call_reviews r
                    JOIN demo_calls c ON c.id = r.call_id
                    WHERE c.source = 'demo'
                )
                """
            )
            connection.execute(
                """
                DELETE FROM processing_log
                WHERE id IN (
                    SELECT r.request_id FROM call_reviews r
                    JOIN demo_calls c ON c.id = r.call_id
                    WHERE c.source = 'demo'
                )
                """
            )
            connection.execute(
                """
                DELETE FROM call_reviews
                WHERE call_id IN (
                    SELECT id FROM demo_calls WHERE source = 'demo'
                )
                """
            )
            connection.execute("DELETE FROM demo_calls WHERE source = 'demo'")
        self._seed_calls()
        self._seed_cached_results()

    def metrics(self) -> dict[str, Any]:
        calls = self.list_calls()
        processed = [call for call in calls if call.get("result")]
        total = len(calls)
        statuses = Counter(call["review_status"] for call in calls)
        auto_pass = sum(
            1
            for call in processed
            if (call.get("result") or {}).get("auto_qa_status") == "auto_pass"
        )
        manual = len(processed) - auto_pass
        scores = [
            call["qa_score"]
            for call in processed
            if isinstance(call.get("qa_score"), (int, float))
        ]
        intents = Counter(
            (call.get("result") or {}).get("intent") or "unknown"
            for call in processed
        )
        violations: Counter[str] = Counter()
        for call in processed:
            for finding in (call.get("result") or {}).get("qa_findings", []):
                if finding.get("status") == "fail":
                    violations[finding.get("criterion") or finding.get("criterion_id")] += 1

        confirmed = [call for call in calls if call["review_status"] == "confirmed"]
        edited = [
            call for call in confirmed
            if any((call.get("changes") or {}).values())
        ]
        latencies = [
            call["meta"]["latency_ms"]
            for call in processed
            if call.get("meta", {}).get("latency_ms")
        ]
        costs = [
            float((call["meta"].get("usage") or {}).get("cost_rub") or 0)
            for call in processed
        ]
        total_cost = sum(costs)
        return {
            "total": total,
            "processed": len(processed),
            "pending": statuses.get("pending", 0),
            "confirmed": statuses.get("confirmed", 0),
            "rejected": statuses.get("rejected", 0),
            "new": statuses.get("new", 0),
            "real": sum(1 for call in calls if call.get("source") == "real"),
            "demo": sum(1 for call in calls if call.get("source") != "real"),
            "auto_pass": auto_pass,
            "manual_review": manual,
            "qa_coverage": round(len(processed) / total * 100, 1) if total else 0,
            "auto_pass_rate": round(auto_pass / len(processed) * 100, 1)
            if processed
            else 0,
            "manual_review_rate": round(manual / len(processed) * 100, 1)
            if processed
            else 0,
            "avg_qa_score": round(sum(scores) / len(scores), 1) if scores else 0,
            "top_intents": intents.most_common(6),
            "top_violations": violations.most_common(6),
            "edit_rate": round(len(edited) / len(confirmed) * 100, 1)
            if confirmed
            else 0,
            "avg_latency_ms": round(sum(latencies) / len(latencies), 0)
            if latencies
            else 0,
            "total_cost_rub": round(total_cost, 4),
            "cost_per_call_rub": round(total_cost / len(processed), 4)
            if processed
            else 0,
            "flagged": [
                call
                for call in calls
                if call["review_status"] == "pending"
                and (call.get("result") or {}).get("auto_qa_status") == "manual_review"
            ],
        }
