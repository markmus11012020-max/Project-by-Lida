"""Small periodic scheduler that enqueues maintenance jobs."""

from __future__ import annotations

import signal
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any


@dataclass
class Schedule:
    kind: str
    interval_seconds: int
    payload: dict[str, Any]
    next_run: datetime


class Scheduler:
    def __init__(self, queue: Any, schedules: list[Schedule]) -> None:
        self.queue = queue
        self.schedules = schedules

    @classmethod
    def from_settings(cls, queue: Any, settings) -> "Scheduler":
        now = datetime.now(timezone.utc)
        schedules: list[Schedule] = []
        if settings.oktell_enabled and settings.oktell_configured:
            schedules.append(
                Schedule(
                    kind="oktell_sync",
                    interval_seconds=settings.oktell_sync_interval_seconds,
                    payload={"since_days": 1, "limit": settings.oktell_page_size},
                    next_run=now,
                )
            )
        if settings.crm_outbox_enabled:
            schedules.append(
                Schedule(
                    kind="crm_dispatch",
                    interval_seconds=settings.crm_dispatch_interval_seconds,
                    payload={},
                    next_run=now,
                )
            )
        schedules.append(
            Schedule(
                kind="retention_cleanup",
                interval_seconds=settings.retention_interval_seconds,
                payload={"days": settings.audio_retention_days},
                next_run=now,
            )
        )
        return cls(queue, schedules)

    def tick(self, now: datetime | None = None) -> list[str]:
        moment = now or datetime.now(timezone.utc)
        enqueued: list[str] = []
        for schedule in self.schedules:
            if moment < schedule.next_run:
                continue
            if not self.queue.has_active(schedule.kind):
                enqueued.append(
                    self.queue.enqueue(schedule.kind, schedule.payload)
                )
            schedule.next_run = moment + timedelta(
                seconds=schedule.interval_seconds
            )
        return enqueued

    def run_forever(self, poll_seconds: float = 5.0) -> None:
        stop = False

        def request_stop(signum, frame):  # noqa: ANN001, ARG001
            nonlocal stop
            stop = True

        try:
            signal.signal(signal.SIGINT, request_stop)
            signal.signal(signal.SIGTERM, request_stop)
        except ValueError:
            pass

        while not stop:
            self.tick()
            time.sleep(poll_seconds)
