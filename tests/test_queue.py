from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.queue import create_queue
from app.worker import Worker


def test_enqueue_dequeue_and_complete(tmp_path: Path) -> None:
    queue = create_queue(f"sqlite:///{tmp_path / 'queue.db'}")
    job_id = queue.enqueue("demo", {"value": 1})

    assert queue.stats() == {"pending": 1}
    job = queue.dequeue("worker-1")
    assert job is not None
    assert job.id == job_id
    assert job.kind == "demo"
    assert job.payload == {"value": 1}
    assert job.attempts == 1
    assert queue.stats() == {"running": 1}

    queue.complete(job_id)
    assert queue.stats() == {"done": 1}


def test_queue_filters_kinds(tmp_path: Path) -> None:
    queue = create_queue(f"sqlite:///{tmp_path / 'queue.db'}")
    queue.enqueue("other", {})

    assert queue.dequeue("worker-1", kinds=["audio_ingest"]) is None


def test_retry_and_final_failure(tmp_path: Path) -> None:
    queue = create_queue(f"sqlite:///{tmp_path / 'queue.db'}")
    job_id = queue.enqueue("demo", {})

    job = queue.dequeue("worker-1")
    assert job is not None
    queue.fail(job.id, "temporary", retry_seconds=60)
    assert queue.stats() == {"pending": 1}
    assert queue.dequeue("worker-1") is None

    queue.fail(job_id, "permanent")
    assert queue.stats() == {"failed": 1}


def test_worker_runs_handler(tmp_path: Path) -> None:
    queue = create_queue(f"sqlite:///{tmp_path / 'queue.db'}")
    processed: list[dict] = []
    queue.enqueue("demo", {"value": 42})

    worker = Worker(
        queue=queue,
        handlers={"demo": lambda payload: processed.append(payload)},
        poll_interval=0,
    )
    assert worker.run_once() is True
    assert processed == [{"value": 42}]
    assert queue.stats() == {"done": 1}


def test_worker_retries_failed_handler(tmp_path: Path, monkeypatch) -> None:
    queue = create_queue(f"sqlite:///{tmp_path / 'queue.db'}")
    queue.enqueue("demo", {})
    monkeypatch.setattr("app.worker.backoff_seconds", lambda _: 0)

    attempts: list[int] = []

    def handler(payload):
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("temporary")

    worker = Worker(queue=queue, handlers={"demo": handler}, poll_interval=0)
    assert worker.run_once() is True
    assert queue.stats() == {"pending": 1}
    job = queue.dequeue("worker-1")
    assert job is not None
    assert job.attempts == 2
    queue.complete(job.id)

    assert queue.stats() == {"done": 1}
    assert len(attempts) == 1


def test_worker_unknown_job_fails(tmp_path: Path) -> None:
    queue = create_queue(f"sqlite:///{tmp_path / 'queue.db'}")
    queue.enqueue("unknown", {})
    worker = Worker(queue=queue, handlers={}, poll_interval=0)
    assert worker.run_once() is True
    assert queue.stats() == {"failed": 1}


@pytest.mark.skipif(
    not os.getenv("TEST_POSTGRES_URL"),
    reason="TEST_POSTGRES_URL is not set",
)
def test_postgres_queue_roundtrip() -> None:
    queue = create_queue(os.environ["TEST_POSTGRES_URL"])
    job_id = queue.enqueue("demo", {"postgres": True})
    job = queue.dequeue("worker-pg")
    assert job is not None
    assert job.id == job_id
    queue.complete(job_id)
