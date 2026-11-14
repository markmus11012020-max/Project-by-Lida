from __future__ import annotations

import sys
from pathlib import Path

from app.config import Settings

CALL_CENTER_DIR = Path(__file__).resolve().parent.parent / "call-center"
sys.path.insert(0, str(CALL_CENTER_DIR))

from call_store import CallStore  # noqa: E402


def _store(tmp_path: Path) -> CallStore:
    settings = Settings(
        _env_file=None,
        aitunnel_api_key="sk-test",
        database_path=tmp_path / "call_center.db",
    )
    return CallStore(settings, settings.database_path)


def test_store_seeds_six_calls_and_cached_results(tmp_path: Path) -> None:
    store = _store(tmp_path)
    calls = store.list_calls()
    assert len(calls) == 6
    assert all(call["result"] for call in calls)
    metrics = store.metrics()
    assert metrics["total"] == 6
    assert metrics["processed"] == 6
    assert metrics["auto_pass"] >= 1
    assert metrics["manual_review"] >= 1


def test_confirm_and_reject_workflow(tmp_path: Path) -> None:
    store = _store(tmp_path)
    call = store.get_call("call_02")
    assert call is not None
    final = dict(call["draft_result"])
    final["next_action"] = final["next_action"] + " Проверено менеджером."

    confirmed = store.confirm_call(
        "call_02",
        final,
        reviewer="Тест",
        reason="Проверка демо",
    )
    assert confirmed["review_status"] == "confirmed"
    assert confirmed["reviewer"] == "Тест"
    assert confirmed["changes"]

    rejected = store.reject_call(
        "call_03",
        reviewer="Тест",
        reason="Неверный интент",
    )
    assert rejected["review_status"] == "rejected"
    assert rejected["review_reason"] == "Неверный интент"

    store.reset_demo()
    assert store.get_call("call_02")["review_status"] == "pending"
    assert store.get_call("call_03")["review_status"] == "pending"
