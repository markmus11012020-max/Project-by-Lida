"""Import new calls from Oktell into the CallPilot review queue.

Run from the project root:
    .venv\\Scripts\\python.exe call-center\\scripts\\sync_oktell.py --since-days 1
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

CALL_CENTER_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = CALL_CENTER_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(CALL_CENTER_DIR))

from app.config import get_settings  # noqa: E402
from app.integrations import OktellClient, OktellSync  # noqa: E402
from call_store import CallStore  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Синхронизация звонков из Oktell")
    parser.add_argument("--since-days", type=int, default=1)
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()

    settings = get_settings()
    if not settings.oktell_enabled or not settings.oktell_configured:
        print(
            "Oktell не включён: задайте OKTELL_ENABLED=true и OKTELL_BASE_URL",
            file=sys.stderr,
        )
        return 2

    db_path = Path(
        os.getenv(
            "CALLPILOT_DB_PATH",
            str(CALL_CENTER_DIR / "data" / "call_center.db"),
        )
    )
    settings = settings.model_copy(update={"database_path": db_path})
    store = CallStore(settings, db_path)
    client = OktellClient.from_settings(settings)
    since = (
        datetime.now(timezone.utc) - timedelta(days=args.since_days)
        if args.since_days > 0
        else None
    )
    report = OktellSync(client, store).run(since=since, limit=args.limit)
    print(
        json.dumps(
            {
                "imported": report.imported,
                "skipped": report.skipped,
                "failed": report.failed,
                "errors": report.errors[:20],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 1 if report.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
