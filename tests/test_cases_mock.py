from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from app.scenarios.registry import SCENARIOS
from app.schemas import EvalCase, ProcessStatus
from app.service import ProcessService
from tests.conftest import DOCUMENTS_OK, SALES_OK, SUPPORT_OK, FakeLLMClient

CASES_PATH = Path(__file__).resolve().parent.parent / "data" / "test_cases.jsonl"


def _load_cases() -> list[EvalCase]:
    cases: list[EvalCase] = []
    for line in CASES_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        cases.append(EvalCase.model_validate(json.loads(line)))
    return cases


def _fake_payload(case: EvalCase) -> dict:
    if case.scenario.value == "support":
        payload = copy.deepcopy(SUPPORT_OK)
        if case.expected_status == ProcessStatus.ESCALATED:
            payload["confidence"] = "low"
            payload["fields"]["client_name"] = None
            payload["fields"]["contact"] = None
            payload["fields"]["issue"] = None
    elif case.scenario.value == "sales":
        payload = copy.deepcopy(SALES_OK)
        if case.expected_status == ProcessStatus.ESCALATED:
            payload["confidence"] = "low"
            payload["fields"]["need"] = None
            payload["fields"]["contact"] = None
            payload["fields"]["company"] = None
    else:
        payload = copy.deepcopy(DOCUMENTS_OK)
        if case.expected_status == ProcessStatus.ESCALATED:
            payload["confidence"] = "low"
            payload["fields"]["project"] = None
            payload["fields"]["scope"] = None
    return payload


@pytest.mark.parametrize("case", _load_cases(), ids=lambda case: case.id)
def test_case_routing(case: EvalCase, service_factory) -> None:
    service: ProcessService = service_factory(
        FakeLLMClient([_fake_payload(case)])
    )
    response = service.process(
        scenario_key=case.scenario,
        text=case.text,
        source="test",
        metadata={"case_id": case.id},
    )

    assert response.status in {
        ProcessStatus.PROCESSED,
        ProcessStatus.ESCALATED,
    }
    if case.expected_status is not None:
        assert response.status == case.expected_status

    scenario = SCENARIOS[case.scenario]
    scenario.result_model.model_validate(response.result)
