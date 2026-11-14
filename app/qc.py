"""JSON parsing, schema validation and escalation rules."""

from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from app.scenarios.base import ScenarioConfig, enum_value, find_missing_groups
from app.schemas import CommonResult, ProcessStatus, ScenarioKey


def extract_json_object(content: str) -> tuple[dict[str, Any] | None, str | None]:
    """Parse an LLM answer into a JSON object.

    Models occasionally wrap JSON in markdown fences or add a short prefix.
    We normalise those cases but still reject anything that is not a JSON object.
    """

    text = (content or "").lstrip("\ufeff").strip()
    if not text:
        return None, "LLM вернул пустой ответ"

    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None, "В ответе LLM не найден JSON-объект"
        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            return None, (
                f"Невалидный JSON: {exc.msg} "
                f"(строка {exc.lineno}, колонка {exc.colno})"
            )

    if not isinstance(data, dict):
        return None, "Корень JSON должен быть объектом"
    return data, None


def validate_result(
    data: dict[str, Any],
    model: type[CommonResult],
) -> tuple[CommonResult | None, list[str]]:
    try:
        return model.model_validate(data), []
    except ValidationError as exc:
        errors: list[str] = []
        for error in exc.errors():
            location = ".".join(str(part) for part in error["loc"]) or "root"
            errors.append(f"{location}: {error['msg']}")
        return None, errors


def apply_qc(
    result: CommonResult,
    scenario: ScenarioConfig,
) -> tuple[CommonResult, ProcessStatus, list[str]]:
    """Apply deterministic business rules after schema validation."""

    reasons: list[str] = []

    if enum_value(result.confidence) == "low":
        result.escalate = True
        reasons.append("low_confidence")

    category = enum_value(getattr(result, "category", ""))
    if category not in scenario.bypass_critical_categories:
        missing = find_missing_groups(result.fields, scenario.critical_groups)
        if missing:
            result.escalate = True
            reasons.append("missing_critical_fields")
            existing = list(result.missing_fields)
            for name in missing:
                if name not in existing:
                    existing.append(name)
            result.missing_fields = existing

    if not result.summary.strip():
        result.escalate = True
        reasons.append("empty_summary")

    if not result.next_action.strip():
        result.escalate = True
        reasons.append("empty_next_action")

    if scenario.extra_qc is not None:
        extra = scenario.extra_qc(result)
        if extra:
            result.escalate = True
            reasons.extend(extra)

    if result.escalate:
        all_reasons: list[str] = []
        if result.escalate_reason:
            all_reasons.extend(
                part.strip()
                for part in result.escalate_reason.split(";")
                if part.strip()
            )
        for reason in reasons:
            if reason not in all_reasons:
                all_reasons.append(reason)
        if not all_reasons:
            all_reasons.append("model_escalation")
        result.escalate_reason = "; ".join(all_reasons)
        return result, ProcessStatus.ESCALATED, all_reasons

    result.escalate_reason = None
    return result, ProcessStatus.PROCESSED, []


def fallback_result(
    scenario_key: ScenarioKey | str,
    reason: str,
) -> dict[str, Any]:
    """Business result for invalid/error cases: always hand over to a human."""

    key = enum_value(scenario_key)
    base: dict[str, Any] = {
        "summary": "Не удалось автоматически обработать входные данные.",
        "priority": "high",
        "next_action": "Передать оператору для ручной обработки.",
        "fields": {},
        "confidence": "low",
        "escalate": True,
        "escalate_reason": reason,
        "missing_fields": [],
    }

    if key == "sales":
        return {"category": "unknown", "score": 0, **base}
    if key == "documents":
        return {"category": "other", "draft_kp": None, **base}
    return {"category": "other", **base}
