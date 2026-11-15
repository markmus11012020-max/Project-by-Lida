"""CallPilot background worker: audio, Oktell sync and CRM dispatch."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

CALL_CENTER_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = CALL_CENTER_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(CALL_CENTER_DIR))

from app.config import get_settings  # noqa: E402
from app.integrations import (  # noqa: E402
    CRMWebhookClient,
    OktellClient,
    OktellSync,
    OutboxDispatcher,
)
from app.queue import create_queue  # noqa: E402
from app.worker import Worker  # noqa: E402
from call_store import CallStore  # noqa: E402

logger = logging.getLogger("callpilot.worker")


def build_store() -> tuple[CallStore, object]:
    settings = get_settings()
    db_path = Path(
        os.getenv(
            "CALLPILOT_DB_PATH",
            str(CALL_CENTER_DIR / "data" / "call_center.db"),
        )
    )
    settings = settings.model_copy(update={"database_path": db_path})
    return CallStore(settings, db_path), settings


def build_handlers(store: CallStore, settings):
    def audio_ingest(payload: dict) -> None:
        path = Path(payload["path"])
        success = False
        try:
            store.ingest_audio(
                path,
                filename=payload.get("filename") or path.name,
                title=payload.get("title") or "",
                external_id=payload.get("external_id") or None,
            )
            success = True
        finally:
            if success:
                path.unlink(missing_ok=True)

    def oktell_sync(payload: dict) -> None:
        if not settings.oktell_configured:
            raise RuntimeError("Oktell не настроен")
        client = OktellClient.from_settings(settings)
        since_days = int(payload.get("since_days", 1))
        since = (
            datetime.now(timezone.utc) - timedelta(days=since_days)
            if since_days > 0
            else None
        )
        report = OktellSync(client, store).run(
            since=since,
            limit=int(payload.get("limit", 100)),
        )
        logger.info(
            "oktell sync: imported=%s skipped=%s failed=%s",
            report.imported,
            report.skipped,
            report.failed,
        )
        if report.failed:
            raise RuntimeError(
                "Oktell sync failures: " + "; ".join(report.errors[:5])
            )

    def crm_dispatch(payload: dict) -> None:
        if store.service.outbox is None:
            raise RuntimeError("CRM outbox не настроен")
        if not settings.crm_webhook_url or not settings.crm_webhook_secret:
            raise RuntimeError("CRM webhook не настроен")
        client = CRMWebhookClient(
            settings.crm_webhook_url,
            settings.crm_webhook_secret,
        )
        report = OutboxDispatcher(
            store.service.outbox,
            client,
            store.service.vault,
        ).run_once()
        logger.info(
            "crm dispatch: sent=%s failed=%s skipped=%s",
            report.sent,
            report.failed,
            report.skipped,
        )

    def retention_cleanup(payload: dict) -> None:
        deleted = store.purge_expired_audio(
            days=payload.get("days"),
        )
        logger.info("retention cleanup: deleted=%s", deleted)

    return {
        "audio_ingest": audio_ingest,
        "oktell_sync": oktell_sync,
        "crm_dispatch": crm_dispatch,
        "retention_cleanup": retention_cleanup,
    }


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    parser = argparse.ArgumentParser(description="CallPilot worker")
    parser.add_argument("--queue-url", default="")
    parser.add_argument("--worker-id", default=os.getenv("WORKER_ID", "callpilot-1"))
    parser.add_argument("--poll", type=float, default=1.0)
    parser.add_argument("--max-jobs", type=int, default=0)
    parser.add_argument("--once", action="store_true")
    parser.add_argument(
        "--enqueue",
        choices=["retention_cleanup", "oktell_sync", "crm_dispatch"],
        default="",
    )
    parser.add_argument("--payload", default="{}")
    args = parser.parse_args(argv)

    store, settings = build_store()
    queue_url = args.queue_url or os.getenv(
        "CALLPILOT_QUEUE_URL",
        settings.callpilot_queue_url,
    )
    queue = create_queue(queue_url)

    if args.enqueue:
        job_id = queue.enqueue(args.enqueue, json.loads(args.payload))
        print(json.dumps({"job_id": job_id, "kind": args.enqueue}, ensure_ascii=False))
        return 0

    worker = Worker(
        queue=queue,
        handlers=build_handlers(store, settings),
        worker_id=args.worker_id,
        poll_interval=args.poll,
        max_jobs=args.max_jobs,
    )
    if args.once:
        processed = 1 if worker.run_once() else 0
        print(json.dumps({"processed": processed}, ensure_ascii=False))
        return 0
    worker.run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
