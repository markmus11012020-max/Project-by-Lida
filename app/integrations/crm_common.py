"""Shared helpers for native CRM clients (Bitrix24, amoCRM)."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping

import httpx

RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}


@dataclass(frozen=True)
class JSONResult:
    status_code: int | None
    data: Any | None
    error: str | None
    attempts: int


def validate_https(
    url: str,
    *,
    label: str = "CRM URL",
    allow_insecure: bool = False,
) -> None:
    if not url:
        raise ValueError(f"{label} is required")
    if not url.startswith("https://") and not allow_insecure:
        raise ValueError(f"{label} must use HTTPS")


def load_field_map(raw: str) -> dict[str, str]:
    """Parse a JSON object mapping Call-Pilot keys to CRM field codes.

    Bitrix24 expects field codes such as ``UF_CRM_1712345678``. amoCRM
    expects numeric custom-field IDs. Values are kept as strings; the
    amoCRM adapter converts them to int when building the request.
    """

    if not raw or not raw.strip():
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("CRM_FIELD_MAP must be valid JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("CRM_FIELD_MAP must be a JSON object")
    result: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not key.strip():
            raise ValueError("CRM_FIELD_MAP keys must be non-empty strings")
        if isinstance(item, bool) or not isinstance(item, (str, int)):
            raise ValueError(
                "CRM_FIELD_MAP values must be strings or integers"
            )
        result[key.strip()] = str(item).strip()
    return result


def post_json(
    url: str,
    payload: Any,
    *,
    headers: Mapping[str, str] | None = None,
    timeout: float = 10.0,
    max_attempts: int = 3,
    delays: Iterable[float] = (2.0, 5.0, 10.0),
    transport: httpx.BaseTransport | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> JSONResult:
    """POST JSON with bounded retries on transient failures."""

    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")
    body = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    request_headers = {"Content-Type": "application/json"}
    if headers:
        request_headers.update(headers)
    delay_values = tuple(delays)
    last_status: int | None = None
    last_error: str | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            with httpx.Client(timeout=timeout, transport=transport) as client:
                response = client.post(
                    url,
                    content=body,
                    headers=request_headers,
                )
            last_status = response.status_code
            data: Any | None
            try:
                data = response.json()
            except ValueError:
                data = None
            if 200 <= response.status_code < 300:
                return JSONResult(
                    status_code=response.status_code,
                    data=data,
                    error=None,
                    attempts=attempt,
                )
            last_error = f"HTTP {response.status_code}"
            if response.status_code not in RETRYABLE_STATUS:
                return JSONResult(
                    status_code=response.status_code,
                    data=data,
                    error=last_error,
                    attempts=attempt,
                )
        except httpx.HTTPError as exc:
            last_error = f"{type(exc).__name__}: {exc}"

        if attempt < max_attempts:
            index = min(attempt - 1, max(0, len(delay_values) - 1))
            delay = delay_values[index] if delay_values else 0.0
            if delay:
                sleep(delay)

    return JSONResult(
        status_code=last_status,
        data=None,
        error=last_error or "CRM request failed",
        attempts=max_attempts,
    )


def payload_value(
    payload: dict[str, Any],
    client_fields: dict[str, Any],
    key: str,
) -> Any:
    """Read a mapped value, supporting the call_score/qa_score aliases."""

    if payload.get(key) is not None:
        return payload[key]
    aliases = {
        "qa_score": ("call_score", "score"),
        "call_score": ("qa_score", "score"),
        "score": ("call_score", "qa_score"),
    }
    for alias in aliases.get(key, ()):
        if payload.get(alias) is not None:
            return payload[alias]
    return client_fields.get(key)


def build_note(payload: dict[str, Any]) -> str:
    """Build a human-readable CRM comment from a Call-Pilot payload."""

    lines: list[str] = []
    summary = payload.get("summary")
    if summary:
        lines.append(str(summary))

    next_action = payload.get("next_action")
    if next_action:
        lines.append(f"Следующий шаг: {next_action}")

    score = payload.get("call_score")
    if score is not None:
        lines.append(f"QA-score: {score}/100")

    findings = payload.get("checklist_results")
    if isinstance(findings, list):
        shown = 0
        for finding in findings:
            if not isinstance(finding, dict):
                continue
            if finding.get("status") != "fail":
                continue
            severity = str(finding.get("severity") or "")
            if severity not in {"critical", "high"}:
                continue
            criterion = finding.get("criterion") or finding.get(
                "criterion_id"
            )
            if not criterion:
                continue
            lines.append(f"Нарушение ({severity}): {criterion}")
            shown += 1
            if shown >= 3:
                break

    if payload.get("escalation_flag"):
        lines.append("Требуется ручная проверка: да")

    request_id = payload.get("request_id")
    if request_id:
        lines.append(f"Call-Pilot ID: {request_id}")

    return "\n".join(lines)[:4000]


def extract_entity_id(data: Any) -> str | None:
    """Extract an entity id from common Bitrix24/amoCRM response shapes."""

    if isinstance(data, list) and data:
        data = data[0]
    if not isinstance(data, dict):
        return None
    if data.get("id") is not None:
        return str(data["id"])
    result = data.get("result")
    if isinstance(result, (int, str)):
        return str(result)
    if isinstance(result, dict):
        value = result.get("ID") or result.get("id")
        if value is not None:
            return str(value)
    embedded = data.get("_embedded")
    if isinstance(embedded, dict):
        for key in ("leads", "contacts", "items"):
            items = embedded.get(key)
            if isinstance(items, list) and items:
                return extract_entity_id(items[0])
    return None
