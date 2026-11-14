"""Shared test fixtures with a deterministic fake LLM."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import Database
from app.llm import LLMResponse
from app.main import create_app
from app.scenarios.registry import SCENARIOS
from app.service import ProcessService

SUPPORT_OK: dict[str, Any] = {
    "category": "delivery",
    "summary": "Клиент оплатил заказ №12345, но доставка не пришла.",
    "priority": "high",
    "next_action": "Проверить статус заказа №12345 и связаться с клиентом.",
    "fields": {
        "client_name": "Анна",
        "contact": "+7 900 123-45-67",
        "order_id": "12345",
        "product": None,
        "issue": "заказ не доставлен",
        "desired_outcome": "получить заказ",
    },
    "confidence": "high",
    "escalate": False,
    "escalate_reason": None,
    "missing_fields": ["product"],
}

SALES_OK: dict[str, Any] = {
    "category": "hot",
    "score": 85,
    "summary": "ООО Ромашка хочет автоматизировать заявки за месяц.",
    "priority": "high",
    "next_action": "Позвонить Ивану и назначить встречу.",
    "fields": {
        "contact_name": "Иван",
        "company": "ООО Ромашка",
        "contact": "+7 900 111-22-33",
        "need": "автоматизация заявок",
        "budget": "до 300 000",
        "urgency": "в течение месяца",
        "source": None,
    },
    "confidence": "high",
    "escalate": False,
    "escalate_reason": None,
    "missing_fields": ["source"],
}

DOCUMENTS_OK: dict[str, Any] = {
    "category": "tz",
    "summary": "ООО Вектор просит разработать Telegram-бота за 30 дней.",
    "priority": "medium",
    "next_action": "Согласовать черновик КП и уточнить интеграцию с CRM.",
    "fields": {
        "customer": "ООО Вектор",
        "project": "Telegram-бот для приёма заявок",
        "deadline": "30 дней",
        "budget": "250 000",
        "scope": "приём заявок, уведомления, выгрузка в CRM",
        "acceptance_criteria": "бот работает, заявки приходят",
    },
    "confidence": "high",
    "escalate": False,
    "escalate_reason": None,
    "missing_fields": [],
}


class FakeLLMClient:
    def __init__(self, responses: list[Any]) -> None:
        self.responses = list(responses)
        self.calls: list[list[dict[str, str]]] = []

    def complete_json(self, messages: list[dict[str, str]]) -> LLMResponse:
        self.calls.append(messages)
        if not self.responses:
            raise AssertionError("FakeLLMClient: no responses left")
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        if isinstance(item, dict):
            content = json.dumps(item, ensure_ascii=False)
        else:
            content = str(item)
        return LLMResponse(
            content=content,
            model="fake-model",
            usage={
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "cost_rub": 0.003,
            },
            latency_ms=10,
        )


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        aitunnel_api_key="sk-test",
        aitunnel_model="fake-model",
        database_path=tmp_path / "test.db",
    )


@pytest.fixture
def db(settings: Settings) -> Database:
    database = Database(settings.database_path)
    database.init()
    return database


@pytest.fixture
def service_factory(settings: Settings, db: Database):
    def factory(llm) -> ProcessService:
        return ProcessService(settings, db, llm, SCENARIOS)

    return factory


@pytest.fixture
def api_client_factory(settings: Settings, db: Database):
    def factory(llm) -> TestClient:
        service = ProcessService(settings, db, llm, SCENARIOS)
        app = create_app(settings=settings, service=service)
        return TestClient(app)

    return factory
