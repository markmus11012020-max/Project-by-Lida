from __future__ import annotations

from app.qc import apply_qc
from app.scenarios.call_qa import QA_CRITERIA
from app.scenarios.registry import SCENARIOS
from app.schemas import CallResult, ProcessStatus, ScenarioKey


def _findings() -> list[dict]:
    return [
        {
            "criterion_id": criterion["id"],
            "criterion": criterion["name"],
            "status": "pass",
            "severity": criterion["severity"],
            "evidence": "цитата",
            "segment_id": "s1",
            "comment": None,
        }
        for criterion in QA_CRITERIA
    ]


def _payload(
    findings: list[dict] | None = None,
    confidence: str = "high",
    sentiment: str = "neutral",
    intent: str = "delivery",
) -> dict:
    return {
        "call_type": "inbound",
        "intent": intent,
        "summary": "Клиент обратился по заказу.",
        "resolution": "Оператор проверил заказ.",
        "next_action": "Перезвонить клиенту.",
        "priority": "medium",
        "fields": {"order_id": "12345"},
        "sentiment": sentiment,
        "qa_score": 0,
        "qa_findings": findings or _findings(),
        "confidence": confidence,
        "escalate": False,
        "escalate_reason": None,
        "missing_fields": [],
    }


def test_all_criteria_pass_is_auto_pass() -> None:
    result = CallResult.model_validate(_payload())
    checked, status, reasons = apply_qc(
        result, SCENARIOS[ScenarioKey.CALL_QA]
    )
    assert checked.qa_score == 100
    assert checked.auto_qa_status == "auto_pass"
    assert status == ProcessStatus.PROCESSED
    assert reasons == []


def test_critical_fail_overrides_model_severity_and_forces_manual() -> None:
    findings = _findings()
    findings[8]["status"] = "fail"
    findings[8]["severity"] = "low"  # model tries to downgrade compliance
    result = CallResult.model_validate(_payload(findings))
    checked, status, reasons = apply_qc(
        result, SCENARIOS[ScenarioKey.CALL_QA]
    )
    assert checked.qa_findings[8].severity == "critical"
    assert checked.qa_score == 60
    assert checked.auto_qa_status == "manual_review"
    assert status == ProcessStatus.ESCALATED
    assert "qa_violation" in reasons
    assert "qa_score_below_threshold" in reasons


def test_missing_criteria_are_filled_and_force_manual() -> None:
    result = CallResult.model_validate(_payload(findings=_findings()[:3]))
    checked, status, reasons = apply_qc(
        result, SCENARIOS[ScenarioKey.CALL_QA]
    )
    assert len(checked.qa_findings) == len(QA_CRITERIA)
    assert any(
        finding.status == "na" for finding in checked.qa_findings
    )
    assert checked.auto_qa_status == "manual_review"
    assert status == ProcessStatus.ESCALATED
    assert "qa_missing_criteria" in reasons


def test_negative_refund_is_manual_even_with_all_pass() -> None:
    result = CallResult.model_validate(
        _payload(sentiment="negative", intent="refund")
    )
    checked, status, reasons = apply_qc(
        result, SCENARIOS[ScenarioKey.CALL_QA]
    )
    assert checked.qa_score == 100
    assert checked.auto_qa_status == "manual_review"
    assert status == ProcessStatus.ESCALATED
    assert "negative_customer_contact" in reasons
