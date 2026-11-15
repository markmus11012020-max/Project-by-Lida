"""Periodic enqueue of Oktell sync, CRM dispatch and retention jobs."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

CALL_CENTER_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = CALL_CENTER_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.config import get_settings  # noqa: E402
from app.queue import create_queue  # noqa: E402
from app.scheduler import Scheduler  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    parser = argparse.ArgumentParser(description="CallPilot scheduler")
    parser.add_argument("--queue-url", default="")
    parser.add_argument("--poll", type=float, default=5.0)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args(argv)

    settings = get_settings()
    queue_url = args.queue_url or os.getenv(
        "CALLPILOT_QUEUE_URL",
        settings.callpilot_queue_url,
    )
    queue = create_queue(queue_url)
    scheduler = Scheduler.from_settings(queue, settings)

    if args.once:
        jobs = scheduler.tick()
        print(json.dumps({"enqueued": jobs}, ensure_ascii=False))
        return 0

    scheduler.run_forever(poll_seconds=args.poll)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
