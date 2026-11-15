from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.queue import create_queue
from app.scheduler import Schedule, Scheduler


def test_tick_enqueues_and_respects_interval(tmp_path: Path) -> None:
    queue = create_queue(f"sqlite:///{tmp_path / 'queue.db'}")
    start = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)
    scheduler = Scheduler(
        queue,
        [Schedule("retention_cleanup", 60, {"days": 30}, start)],
    )

    first = scheduler.tick(start)
    assert len(first) == 1
    assert queue.stats() == {"pending": 1}

    assert scheduler.tick(start) == []
    queue.complete(first[0])

    assert scheduler.tick(start + timedelta(seconds=30)) == []
    second = scheduler.tick(start + timedelta(seconds=60))
    assert len(second) == 1


def test_tick_skips_if_same_kind_already_active(tmp_path: Path) -> None:
    queue = create_queue(f"sqlite:///{tmp_path / 'queue.db'}")
    start = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)
    scheduler = Scheduler(
        queue,
        [Schedule("oktell_sync", 10, {}, start)],
    )

    queue.enqueue("oktell_sync", {"old": True})
    assert scheduler.tick(start) == []
    assert queue.stats() == {"pending": 1}
