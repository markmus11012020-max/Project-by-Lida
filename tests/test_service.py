from __future__ import annotations

from app.llm import LLMError
from app.schemas import ProcessStatus, ScenarioKey
from tests.conftest import (
    DOCUMENTS_OK,
    SALES_OK,
    SUPPORT_OK,
    FakeLLMClient,
)


def test_support_processed_and_audited(service_factory) -> None:
    service = service_factory(FakeLLMClient([SUPPORT_OK]))
    response = service.process(
        ScenarioKey.SUPPORT,
        "Оплатил заказ №12345, доставки нет.",
        source="test",
    )

    assert response.status == ProcessStatus.PROCESSED
    assert response.result["category"] == "delivery"
    assert response.error is None

    stored = service.get_result(response.request_id)
    assert stored is not None
    assert stored["status"] == "processed"
    assert stored["result"]["next_action"]

    audit = service.get_audit(response.request_id, include_raw=True)
    assert audit is not None
    assert audit["input_text"].startswith("Оплатил")
    assert "delivery" in (audit["raw_response"] or "")


def test_documents_builds_draft_kp(service_factory) -> None:
    service = service_factory(FakeLLMClient([DOCUMENTS_OK]))
    response = service.process(ScenarioKey.DOCUMENTS, "ТЗ на бота.")

    assert response.status == ProcessStatus.PROCESSED
    draft = response.result["draft_kp"]
    assert "ЧЕРНОВИК КОММЕРЧЕСКОГО ПРЕДЛОЖЕНИЯ" in draft
    assert "Telegram-бот" in draft
    assert "Стоимость" in draft


def test_sales_processed(service_factory) -> None:
    service = service_factory(FakeLLMClient([SALES_OK]))
    response = service.process(ScenarioKey.SALES, "Нужна автоматизация.")
    assert response.status == ProcessStatus.PROCESSED
    assert response.result["score"] == 85


def test_invalid_json_falls_back_and_audits(service_factory) -> None:
    service = service_factory(FakeLLMClient(["это не json"]))
    response = service.process(ScenarioKey.SUPPORT, "Текст обращения.")

    assert response.status == ProcessStatus.INVALID
    assert response.result["escalate"] is True
    assert response.result["next_action"] == "Передать оператору для ручной обработки."
    assert response.error

    audit = service.get_audit(response.request_id, include_raw=True)
    assert audit is not None
    assert audit["raw_response"] == "это не json"


def test_llm_error_falls_back(service_factory) -> None:
    service = service_factory(FakeLLMClient([LLMError("timeout")]))
    response = service.process(ScenarioKey.SALES, "Лид без ответа.")

    assert response.status == ProcessStatus.ERROR
    assert response.result["category"] == "unknown"
    assert response.result["escalate"] is True
    assert "timeout" in (response.error or "")


def test_low_confidence_is_escalated(service_factory) -> None:
    payload = {**SUPPORT_OK, "confidence": "low"}
    service = service_factory(FakeLLMClient([payload]))
    response = service.process(ScenarioKey.SUPPORT, "Не работает.")

    assert response.status == ProcessStatus.ESCALATED
    assert response.result["escalate"] is True
    assert "low_confidence" in response.result["escalate_reason"]


def test_stats_and_list(service_factory) -> None:
    service = service_factory(FakeLLMClient([SUPPORT_OK, SALES_OK]))
    service.process(ScenarioKey.SUPPORT, "Обращение.")
    service.process(ScenarioKey.SALES, "Лид.")

    items = service.list_results()
    assert len(items) == 2

    stats = service.stats()
    assert stats["total_requests"] == 2
    assert stats["by_status"]["processed"] == 2
    assert stats["total_cost_rub"] > 0
