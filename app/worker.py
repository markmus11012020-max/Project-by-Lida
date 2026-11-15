"""Background worker for the durable job queue."""

from __future__ import annotations

import argparse
import logging
import signal
import time
from dataclasses import dataclass
from typing import Any, Callable

from app.queue import Job, create_queue

logger = logging.getLogger(__name__)

Handler = Callable[[dict[str, Any]], None]


def backoff_seconds(attempts: int) -> float:
    return float(min(300, 2 ** min(max(attempts, 1), 8)))


@dataclass
class Worker:
    queue: Any
    handlers: dict[str, Handler]
    worker_id: str = "worker"
    poll_interval: float = 1.0
    max_jobs: int = 0

    def run_once(self) -> bool:
        job = self.queue.dequeue(self.worker_id, kinds=list(self.handlers))
        if job is None:
            return False
        self._handle(job)
        return True

    def _handle(self, job: Job) -> None:
        handler = self.handlers.get(job.kind)
        if handler is None:
            self.queue.fail(job.id, f"Unknown job kind: {job.kind}")
            return
        try:
            handler(job.payload)
        except Exception as exc:  # noqa: BLE001 - a bad job must not stop worker
            logger.exception("Job %s failed", job.id)
            self.queue.fail(
                job.id,
                f"{type(exc).__name__}: {exc}",
                retry_seconds=backoff_seconds(job.attempts),
            )
        else:
            self.queue.complete(job.id)

    def run_forever(self) -> int:
        processed = 0
        stop = False

        def request_stop(signum, frame):  # noqa: ANN001, ARG001
            nonlocal stop
            stop = True

        try:
            signal.signal(signal.SIGINT, request_stop)
            signal.signal(signal.SIGTERM, request_stop)
        except ValueError:
            # Signal handlers can be installed only in the main thread.
            pass

        while not stop:
            if self.run_once():
                processed += 1
                if self.max_jobs and processed >= self.max_jobs:
                    break
                continue
            time.sleep(self.poll_interval)
        return processed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="CallPilot queue worker")
    parser.add_argument(
        "--queue-url",
        required=True,
        help="sqlite:///path/to/queue.db или postgresql://...",
    )
    parser.add_argument("--worker-id", default="worker-1")
    parser.add_argument("--poll", type=float, default=1.0)
    parser.add_argument("--max-jobs", type=int, default=0)
    parser.add_argument("--once", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    args = build_parser().parse_args(argv)
    queue = create_queue(args.queue_url)
    worker = Worker(
        queue=queue,
        handlers={},
        worker_id=args.worker_id,
        poll_interval=args.poll,
        max_jobs=args.max_jobs,
    )
    if args.once:
        worker.run_once()
        return 0
    worker.run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
