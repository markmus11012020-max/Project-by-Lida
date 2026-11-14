from __future__ import annotations

from app.qc import (
    apply_qc,
    extract_json_object,
    fallback_result,
    validate_result,
)
from app.scenarios.registry import SCENARIOS
from app.schemas import ProcessStatus, ScenarioKey, SupportResult
from tests.conftest import SALES_OK, SUPPORT_OK


def test_extract_plain_json() -> None:
    data, error = extract_json_object('{"ok": true}')
    assert error is None
    assert data == {"ok": True}


def test_extract_json_from_fence_and_prefix() -> None:
    content = 'Вот результат:\n```json\n{"category": "other"}\n```'
    data, error = extract_json_object(content)
    assert error is None
    assert data == {"category": "other"}


def test_extract_rejects_array_root() -> None:
    data, error = extract_json_object("[1, 2, 3]")
    assert data is None
    assert error is not None


def test_extract_rejects_invalid_json() -> None:
    data, error = extract_json_object("не json")
    assert data is None
    assert "JSON" in (error or "")


def test_validate_result_reports_field_errors() -> None:
    result, errors = validate_result({"category": "delivery"}, SupportResult)
    assert result is None
    assert errors
    assert any("summary" in item for item in errors)


def test_low_confidence_forces_escalation() -> None:
    payload = {**SUPPORT_OK, "confidence": "low"}
    result = SupportResult.model_validate(payload)
    checked, status, reasons = apply_qc(
        result, SCENARIOS[ScenarioKey.SUPPORT]
    )
    assert checked.escalate is True
    assert status == ProcessStatus.ESCALATED
    assert "low_confidence" in reasons


def test_missing_critical_fields_force_escalation() -> None:
    payload = {
        **SALES_OK,
        "fields": {
            **SALES_OK["fields"],
            "need": None,
            "contact": None,
            "company": None,
        },
        "confidence": "high",
    }
    result = validate_result(payload, SCENARIOS[ScenarioKey.SALES].result_model)[0]
    assert result is not None
    checked, status, reasons = apply_qc(
        result, SCENARIOS[ScenarioKey.SALES]
    )
    assert checked.escalate is True
    assert status == ProcessStatus.ESCALATED
    assert "missing_critical_fields" in reasons
    assert "need" in checked.missing_fields


def test_model_escalation_is_respected() -> None:
    payload = {
        **SUPPORT_OK,
        "escalate": True,
        "escalate_reason": "manual_review",
    }
    result = SupportResult.model_validate(payload)
    checked, status, reasons = apply_qc(
        result, SCENARIOS[ScenarioKey.SUPPORT]
    )
    assert checked.escalate is True
    assert status == ProcessStatus.ESCALATED
    assert any("manual_review" in reason for reason in reasons)


def test_clear_spam_is_rejected_without_human_escalation() -> None:
    payload = {
        **SALES_OK,
        "category": "spam",
        "score": 0,
        "confidence": "high",
        "fields": {
            **SALES_OK["fields"],
            "need": None,
            "contact": None,
            "company": None,
        },
    }
    result = validate_result(payload, SCENARIOS[ScenarioKey.SALES].result_model)[0]
    assert result is not None
    checked, status, reasons = apply_qc(
        result, SCENARIOS[ScenarioKey.SALES]
    )
    assert checked.escalate is False
    assert status == ProcessStatus.PROCESSED
    assert reasons == []


def test_sales_score_category_mismatch_escalates() -> None:
    payload = {**SALES_OK, "category": "hot", "score": 20}
    result = validate_result(payload, SCENARIOS[ScenarioKey.SALES].result_model)[0]
    assert result is not None
    checked, status, reasons = apply_qc(
        result, SCENARIOS[ScenarioKey.SALES]
    )
    assert checked.escalate is True
    assert status == ProcessStatus.ESCALATED
    assert "inconsistent_score" in reasons


def test_processed_result_clears_stale_reason() -> None:
    payload = {
        **SUPPORT_OK,
        "escalate": False,
        "escalate_reason": "stale_reason",
    }
    result = SupportResult.model_validate(payload)
    checked, status, reasons = apply_qc(
        result, SCENARIOS[ScenarioKey.SUPPORT]
    )
    assert checked.escalate is False
    assert checked.escalate_reason is None
    assert status == ProcessStatus.PROCESSED
    assert reasons == []


def test_fallback_matches_scenario_shape() -> None:
    support = fallback_result(ScenarioKey.SUPPORT, "invalid_json")
    assert support["category"] == "other"
    assert support["escalate"] is True

    sales = fallback_result(ScenarioKey.SALES, "llm_error")
    assert sales["category"] == "unknown"
    assert sales["score"] == 0

    documents = fallback_result(ScenarioKey.DOCUMENTS, "validation_error")
    assert documents["category"] == "other"
    assert documents["draft_kp"] is None
