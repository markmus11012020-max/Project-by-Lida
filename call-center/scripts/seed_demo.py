"""Process the six demo calls through the real LLM and cache the results.

Run from the project root:
    .venv\\Scripts\\python.exe call-center\\scripts\\seed_demo.py

The app can then start without spending API money: cached results are inserted
from call-center/data/seed_results.json on the first run.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

CALL_CENTER_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = CALL_CENTER_DIR.parent
sys.path.insert(0, str(CALL_CENTER_DIR))
sys.path.insert(0, str(PROJECT_ROOT))

from app.config import get_settings  # noqa: E402
from call_store import CallStore  # noqa: E402
from demo_data import DEMO_CALLS  # noqa: E402

DB_PATH = CALL_CENTER_DIR / "data" / "call_center.db"
SEED_PATH = CALL_CENTER_DIR / "data" / "seed_results.json"


def _configure_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def main() -> int:
    _configure_stdout()
    settings = get_settings().model_copy(update={"database_path": DB_PATH})
    if not settings.llm_configured:
        print("AITUNNEL_API_KEY не настроен. Заполните .env.")
        return 1

    store = CallStore(settings, DB_PATH)
    seed: dict[str, dict] = {}

    for call in DEMO_CALLS:
        print(f"Обрабатываю {call['id']} — {call['title']}...")
        response = store.process_call(call["id"], source="demo_seed")
        audit = store.core_db.get_audit(
            response.request_id,
            include_raw=True,
        ) or {}
        input_text = audit.get("input_text") or ""
        raw_response = audit.get("raw_response")
        result = response.result or {}
        seed[call["id"]] = {
            "request_id": response.request_id,
            "input_text": input_text,
            "raw_response": raw_response,
            "result": result,
            "meta": response.meta.model_dump(mode="json"),
            "error": response.error,
        }
        print(
            f"  status={response.status.value} "
            f"score={result.get('qa_score')} "
            f"auto={result.get('auto_qa_status')} "
            f"latency={response.meta.latency_ms} ms"
        )

    SEED_PATH.write_text(
        json.dumps(seed, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\nСохранено: {SEED_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
