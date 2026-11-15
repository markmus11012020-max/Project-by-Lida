from __future__ import annotations

import json
from pathlib import Path

from app.golden import (
    GoldenCase,
    evaluate_response,
    load_cases,
    run_golden_set,
)
from app.scenarios.call_qa import QA_CRITERIA
from app.schemas import (
    ProcessMeta,
    ProcessResponse,
    ProcessStatus,
    ScenarioKey,
)
from tests.conftest import FakeLLMClient
from tests.test_call_qa import _payload


def _all_pass() -> dict:
    return _payload()


def _response(result: dict, status: ProcessStatus = ProcessStatus.PROCESSED) -> ProcessResponse:
    return ProcessResponse(
        request_id="test",
        scenario="call_qa",
        status=status,
        result=result,
        meta=ProcessMeta(
            model="test",
            temperature=0.2,
            latency_ms=1,
            created_at="2026-11-16T00:00:00+00:00",
        ),
    )


def test_load_cases(tmp_path: Path) -> None:
    path = tmp_path / "golden.jsonl"
    path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "id": "g1",
                        "scenario": "call_qa",
                        "text": "Оператор: Здравствуйте.",
                        "expected": {"status": "processed"},
                    },
                    ensure_ascii=False,
                ),
                "# comment",
                json.dumps(
                    {
                        "id": "g2",
                        "text": "Клиент: Помогите.",
                        "expected": {},
                    },
                    ensure_ascii=False,
                ),
            ]
        ),
        encoding="utf-8",
    )

    cases = load_cases(path)
    assert [case.id for case in cases] == ["g1", "g2"]
    assert cases[0].scenario == ScenarioKey.CALL_QA
    assert cases[1].scenario == ScenarioKey.CALL_QA


def test_evaluate_response_detects_critical_miss() -> None:
    expected = {
        "status": "escalated",
        "auto_qa_status": "manual_review",
        "qa_score": 60,
        "criteria": {
            "compliance": "fail",
            "greeting": "pass",
        },
        "critical_fail": ["compliance"],
    }
    case = GoldenCase(
        id="g1",
        scenario=ScenarioKey.CALL_QA,
        text="text",
        expected=expected,
    )
    payload = _all_pass()  # all pass, so the critical finding is missed
    evaluation = evaluate_response(_response(payload), case)

    assert evaluation["critical_recall_hit"] == 0
    assert evaluation["critical_expected_total"] == 1
    assert evaluation["false_critical"] == 0
    assert evaluation["ok"] is False
    assert evaluation["criteria_matches"] == 1  # greeting matches


def test_evaluate_response_flags_false_critical() -> None:
    expected = {
        "status": "processed",
        "auto_qa_status": "auto_pass",
        "criteria": {"greeting": "pass"},
        "critical_fail": [],
    }
    case = GoldenCase(
        id="g1",
        scenario=ScenarioKey.CALL_QA,
        text="text",
        expected=expected,
    )
    payload = _all_pass()
    payload["qa_findings"][0]["status"] = "fail"
    payload["qa_findings"][0]["severity"] = "critical"
    evaluation = evaluate_response(_response(payload), case)

    assert evaluation["false_critical"] == 1
    assert evaluation["critical_recall_hit"] == 0


def test_run_golden_set_with_fake_llm(service_factory) -> None:
    service = service_factory(FakeLLMClient([_all_pass()]))
    case = GoldenCase(
        id="g1",
        scenario=ScenarioKey.CALL_QA,
        text="Оператор: Здравствуйте, чем помочь?",
        expected={
            "status": "processed",
            "auto_qa_status": "auto_pass",
            "qa_score": 100,
            "criteria": {
                criterion["id"]: "pass" for criterion in QA_CRITERIA
            },
            "critical_fail": [],
        },
    )

    report = run_golden_set(service, [case])

    assert report.total == 1
    assert report.status_accuracy == 1.0
    assert report.auto_accuracy == 1.0
    assert report.criterion_accuracy == 1.0
    assert report.critical_recall == 1.0
    assert report.false_critical == 0
    assert report.score_mae == 0
    assert report.failures == []
