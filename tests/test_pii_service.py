from __future__ import annotations

from app.schemas import ScenarioKey
from tests.conftest import SUPPORT_OK, FakeLLMClient


def test_service_masks_input_before_llm_and_audit(service_factory) -> None:
    llm = FakeLLMClient([SUPPORT_OK])
    service = service_factory(llm)

    response = service.process(
        ScenarioKey.SUPPORT,
        "Анна, +7 900 123-45-67, anna@example.ru. Оплатила заказ.",
        source="audio",
        anonymize=True,
    )

    assert response.meta.pii_masked is True
    assert response.meta.pii_entities == {"PERSON": 1, "PHONE": 1, "EMAIL": 1}

    prompt = llm.calls[0][-1]["content"]
    assert "[PERSON_1]" in prompt
    assert "[PHONE_1]" in prompt
    assert "[EMAIL_1]" in prompt
    assert "Анна" not in prompt
    assert "+7 900 123-45-67" not in prompt
    assert "anna@example.ru" not in prompt

    audit = service.get_audit(response.request_id)
    assert audit is not None
    assert audit["input_text"].startswith("[PERSON_1]")
    assert "+7 900 123-45-67" not in audit["input_text"]
    assert "anna@example.ru" not in audit["input_text"]


def test_service_does_not_mask_by_default(service_factory) -> None:
    llm = FakeLLMClient([SUPPORT_OK])
    service = service_factory(llm)

    response = service.process(
        ScenarioKey.SUPPORT,
        "Анна, +7 900 123-45-67. Оплатила заказ.",
    )

    assert response.meta.pii_masked is False
    assert response.meta.pii_entities == {}
    prompt = llm.calls[0][-1]["content"]
    assert "+7 900 123-45-67" in prompt
