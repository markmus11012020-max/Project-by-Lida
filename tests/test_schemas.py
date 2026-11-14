from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas import (
    DocumentResult,
    LeadCategory,
    ProcessRequest,
    SalesResult,
    SupportResult,
)
from tests.conftest import SUPPORT_OK


def test_support_result_normalizes_enums_and_null_fields() -> None:
    payload = {
        **SUPPORT_OK,
        "priority": "HIGH",
        "confidence": "Medium",
        "category": "Delivery",
        "fields": None,
        "missing_fields": None,
        "extra_key": "ignored",
    }
    result = SupportResult.model_validate(payload)
    assert result.priority == "high"
    assert result.confidence == "medium"
    assert result.category == "delivery"
    assert result.fields == {}
    assert result.missing_fields == []
    assert "extra_key" not in result.model_dump()


def test_sales_score_must_be_in_range() -> None:
    payload = {
        "category": "hot",
        "score": 101,
        "summary": "Тестовый лид.",
        "priority": "high",
        "next_action": "Позвонить",
        "fields": {},
        "confidence": "high",
    }
    with pytest.raises(ValidationError):
        SalesResult.model_validate(payload)


def test_sales_accepts_unknown_category_for_fallback() -> None:
    payload = {
        "category": "unknown",
        "score": 0,
        "summary": "Не удалось обработать.",
        "priority": "high",
        "next_action": "Передать оператору.",
        "fields": {},
        "confidence": "low",
        "escalate": True,
    }
    result = SalesResult.model_validate(payload)
    assert result.category == LeadCategory.UNKNOWN.value


def test_documents_draft_is_optional() -> None:
    payload = {
        "category": "tz",
        "summary": "Проект.",
        "priority": "medium",
        "next_action": "Согласовать.",
        "fields": {},
        "confidence": "high",
    }
    result = DocumentResult.model_validate(payload)
    assert result.draft_kp is None


def test_process_request_validates_scenario_and_text() -> None:
    request = ProcessRequest(scenario="support", text="Нужна помощь")
    assert request.scenario.value == "support"

    with pytest.raises(ValidationError):
        ProcessRequest(scenario="unknown", text="Нужна помощь")

    with pytest.raises(ValidationError):
        ProcessRequest(scenario="support", text="ok")
