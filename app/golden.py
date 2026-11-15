"""Golden-set evaluation for QA quality and calibration."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.schemas import ProcessResponse, ScenarioKey


@dataclass(frozen=True)
class GoldenCase:
    id: str
    scenario: ScenarioKey
    text: str
    expected: dict[str, Any]


@dataclass
class GoldenReport:
    total: int = 0
    status_accuracy: float = 0.0
    auto_accuracy: float = 0.0
    criterion_accuracy: float = 0.0
    critical_recall: float = 0.0
    false_critical: int = 0
    score_mae: float = 0.0
    cases: list[dict[str, Any]] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "status_accuracy": round(self.status_accuracy, 4),
            "auto_accuracy": round(self.auto_accuracy, 4),
            "criterion_accuracy": round(self.criterion_accuracy, 4),
            "critical_recall": round(self.critical_recall, 4),
            "false_critical": self.false_critical,
            "score_mae": round(self.score_mae, 2),
            "failures": self.failures,
            "cases": self.cases,
        }


def load_cases(path: Path) -> list[GoldenCase]:
    cases: list[GoldenCase] = []
    for line_number, line in enumerate(
        Path(path).read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Ошибка JSONL в {path}, строка {line_number}: {exc}"
            ) from exc
        if not isinstance(payload, dict):
            raise ValueError(f"Строка {line_number}: ожидался объект")
        case_id = str(payload.get("id") or f"case-{line_number}")
        text = str(payload.get("text") or "").strip()
        if not text:
            raise ValueError(f"Строка {line_number}: пустой text")
        scenario = ScenarioKey(str(payload.get("scenario") or "call_qa"))
        expected = payload.get("expected") or {}
        if not isinstance(expected, dict):
            raise ValueError(f"Строка {line_number}: expected должен быть объектом")
        cases.append(
            GoldenCase(
                id=case_id,
                scenario=scenario,
                text=text,
                expected=expected,
            )
        )
    if not cases:
        raise ValueError(f"В {path} нет golden-кейсов")
    return cases


def _findings(result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    findings = result.get("qa_findings") or []
    return {
        str(item.get("criterion_id")): item
        for item in findings
        if isinstance(item, dict) and item.get("criterion_id")
    }


def evaluate_response(
    response: ProcessResponse,
    case: GoldenCase,
) -> dict[str, Any]:
    expected = case.expected
    result = response.result or {}
    actual_status = response.status.value
    actual_auto = result.get("auto_qa_status")
    findings = _findings(result)
    actual_criteria = {
        criterion_id: finding.get("status")
        for criterion_id, finding in findings.items()
    }
    expected_criteria = expected.get("criteria") or {}

    matches = 0
    for criterion_id, expected_status in expected_criteria.items():
        if actual_criteria.get(criterion_id) == expected_status:
            matches += 1

    expected_critical = {
        str(item) for item in (expected.get("critical_fail") or [])
    }
    actual_critical = {
        criterion_id
        for criterion_id, finding in findings.items()
        if finding.get("status") == "fail"
        and finding.get("severity") == "critical"
    }

    expected_status = expected.get("status")
    expected_auto = expected.get("auto_qa_status")
    expected_score = expected.get("qa_score")
    actual_score = result.get("qa_score")

    score_error = None
    if isinstance(expected_score, (int, float)) and isinstance(
        actual_score, (int, float)
    ):
        score_error = abs(float(expected_score) - float(actual_score))

    status_ok = (
        None if expected_status is None else actual_status == expected_status
    )
    auto_ok = (
        None if expected_auto is None else actual_auto == expected_auto
    )
    criteria_ok = (
        matches == len(expected_criteria) if expected_criteria else None
    )
    critical_ok = (
        expected_critical <= actual_critical
        if expected_critical
        else None
    )

    case_ok = all(
        item is not False
        for item in (status_ok, auto_ok, criteria_ok, critical_ok)
    )
    return {
        "id": case.id,
        "scenario": case.scenario.value,
        "ok": case_ok,
        "expected_status": expected_status,
        "actual_status": actual_status,
        "status_ok": status_ok,
        "expected_auto": expected_auto,
        "actual_auto": actual_auto,
        "auto_ok": auto_ok,
        "criteria_matches": matches,
        "criteria_total": len(expected_criteria),
        "criteria_ok": criteria_ok,
        "expected_critical": sorted(expected_critical),
        "actual_critical": sorted(actual_critical),
        "critical_recall_hit": len(expected_critical & actual_critical),
        "critical_expected_total": len(expected_critical),
        "false_critical": len(actual_critical - expected_critical),
        "score_expected": expected_score,
        "score_actual": actual_score,
        "score_error": score_error,
        "request_id": response.request_id,
        "status": response.status.value,
        "error": response.error,
    }


def run_golden_set(service, cases: list[GoldenCase]) -> GoldenReport:
    evaluations: list[dict[str, Any]] = []
    for case in cases:
        response = service.process(
            scenario_key=case.scenario,
            text=case.text,
            source="golden",
            metadata={"golden_id": case.id},
            anonymize=True,
        )
        evaluations.append(evaluate_response(response, case))

    total = len(evaluations)
    with_status = [
        item for item in evaluations if item["status_ok"] is not None
    ]
    with_auto = [
        item for item in evaluations if item["auto_ok"] is not None
    ]
    criteria_matches = sum(item["criteria_matches"] for item in evaluations)
    criteria_total = sum(item["criteria_total"] for item in evaluations)
    critical_hits = sum(
        item["critical_recall_hit"] for item in evaluations
    )
    critical_total = sum(
        item["critical_expected_total"] for item in evaluations
    )
    score_errors = [
        item["score_error"]
        for item in evaluations
        if item["score_error"] is not None
    ]
    report = GoldenReport(
        total=total,
        status_accuracy=(
            sum(1 for item in with_status if item["status_ok"])
            / len(with_status)
            if with_status
            else 0.0
        ),
        auto_accuracy=(
            sum(1 for item in with_auto if item["auto_ok"])
            / len(with_auto)
            if with_auto
            else 0.0
        ),
        criterion_accuracy=(
            criteria_matches / criteria_total if criteria_total else 0.0
        ),
        critical_recall=(
            critical_hits / critical_total if critical_total else 1.0
        ),
        false_critical=sum(
            item["false_critical"] for item in evaluations
        ),
        score_mae=(
            sum(score_errors) / len(score_errors) if score_errors else 0.0
        ),
        cases=evaluations,
        failures=[item["id"] for item in evaluations if not item["ok"]],
    )
    return report
