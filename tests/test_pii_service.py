from __future__ import annotations

import json
from pathlib import Path

from app.config import Settings
from app.db import Database
from app.integrations import WebhookOutbox
from app.scenarios.registry import SCENARIOS
from app.schemas import ScenarioKey
from app.security import (
    Anonymizer,
    EncryptedSQLitePIIVault,
    InMemoryPIIVault,
)
from app.service import ProcessService
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


def test_result_is_masked_in_db_but_restored_in_response(service_factory) -> None:
    service = service_factory(FakeLLMClient([SUPPORT_OK]))

    response = service.process(
        ScenarioKey.SUPPORT,
        "Анна, +7 900 123-45-67. Оплатила заказ.",
        anonymize=True,
    )

    stored = service.get_result(response.request_id)
    assert stored is not None
    stored_fields = stored["result"]["fields"]
    assert stored_fields["client_name"] == "[PERSON_1]"
    assert stored_fields["contact"] == "[PHONE_1]"

    assert response.result["fields"]["client_name"] == "Анна"
    assert response.result["fields"]["contact"] == "+7 900 123-45-67"

    entry = service.get_pii(response.request_id)
    assert entry is not None
    assert entry.mapping["[PERSON_1]"] == "Анна"
    assert entry.mapping["[PHONE_1]"] == "+7 900 123-45-67"


def test_masking_session_shares_tokens_between_input_and_result() -> None:
    session = Anonymizer().session()
    first = session.anonymize("Анна, +7 900 123-45-67")
    masked = session.mask_value(
        {"name": "Анна", "phone": "+7 900 123-45-67", "score": 91}
    )

    assert "[PERSON_1]" in first.text
    assert masked == {
        "name": "[PERSON_1]",
        "phone": "[PHONE_1]",
        "score": 91,
    }
    assert session.restore_value(masked) == {
        "name": "Анна",
        "phone": "+7 900 123-45-67",
        "score": 91,
    }


def test_session_load_reuses_existing_tokens() -> None:
    base = Anonymizer().anonymize("Анна, +7 900 123-45-67")
    session = Anonymizer().session()
    session.load(base.mapping, base.kinds)

    masked = session.mask_value(
        {"name": "Анна", "phone": "+7 900 111-22-33"}
    )

    assert masked["name"] == "[PERSON_1]"
    assert masked["phone"] == "[PHONE_2]"
    assert session.restore_value(masked)["phone"] == "+7 900 111-22-33"


def test_encrypted_vault_persists_and_hides_mapping(tmp_path: Path) -> None:
    path = tmp_path / "vault.db"
    mapping = {"[PERSON_1]": "Анна", "[PHONE_1]": "+7 900 123-45-67"}
    kinds = {"[PERSON_1]": "PERSON", "[PHONE_1]": "PHONE"}

    vault = EncryptedSQLitePIIVault(path, "secret")
    vault.put("req-1", mapping, kinds, ttl_seconds=60)

    entry = vault.get("req-1")
    assert entry is not None
    assert entry.mapping == mapping

    reopened = EncryptedSQLitePIIVault(path, "secret")
    assert reopened.get("req-1").mapping == mapping

    wrong_key = EncryptedSQLitePIIVault(path, "other-secret")
    assert wrong_key.get("req-1") is None

    vault.put("expired", mapping, kinds, ttl_seconds=-1)
    assert vault.get("expired") is None


def test_in_memory_vault_expires() -> None:
    vault = InMemoryPIIVault()
    vault.put("req-1", {"[PERSON_1]": "Анна"}, {"[PERSON_1]": "PERSON"}, 60)
    assert vault.get("req-1") is not None

    vault.put("req-2", {"[PERSON_1]": "Анна"}, {"[PERSON_1]": "PERSON"}, -1)
    assert vault.get("req-2") is None


def test_crm_outbox_gets_masked_payload(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        aitunnel_api_key="sk-test",
        database_path=tmp_path / "app.db",
        crm_webhook_enabled=True,
        crm_outbox_path=tmp_path / "outbox.db",
    )
    db = Database(settings.database_path)
    db.init()
    service = ProcessService(
        settings=settings,
        db=db,
        llm=FakeLLMClient([SUPPORT_OK]),
        scenarios=SCENARIOS,
    )

    response = service.process(
        ScenarioKey.SUPPORT,
        "Анна, +7 900 123-45-67. Оплатила заказ.",
        anonymize=True,
    )

    outbox = WebhookOutbox(settings.crm_outbox_path)
    item = outbox.get(response.request_id)
    assert item is None

    stored = service.get_result(response.request_id)
    assert stored is not None
    assert service.enqueue_crm(response.request_id, stored["result"]) is True

    item = outbox.get(response.request_id)
    assert item is not None
    payload = item["payload"]
    assert payload["client_fields"]["client_name"] == "[PERSON_1]"
    assert payload["client_fields"]["contact"] == "[PHONE_1]"
    serialized = json.dumps(payload, ensure_ascii=False)
    assert "Анна" not in serialized
    assert "+7 900 123-45-67" not in serialized
