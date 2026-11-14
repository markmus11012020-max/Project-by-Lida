"""Shared scenario configuration and helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Sequence

from app.schemas import CommonResult, ScenarioKey


def is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, dict, set)):
        return len(value) == 0
    return False


def find_missing_groups(
    fields: dict[str, Any],
    groups: Sequence[Sequence[str]],
) -> list[str]:
    """Return field names for groups where every alternative is empty.

    Each group is an OR-group: for ("contact", "company") at least one
    value must be present. Groups themselves are ANDed.
    """

    missing: list[str] = []
    for group in groups:
        if not any(not is_empty(fields.get(name)) for name in group):
            missing.extend(group)
    return missing


def enum_value(value: Any) -> str:
    return str(getattr(value, "value", value))


@dataclass(frozen=True)
class ScenarioConfig:
    key: ScenarioKey
    title: str
    description: str
    result_model: type[CommonResult]
    system_prompt: str
    schema_hint: str
    example_input: str
    critical_groups: tuple[tuple[str, ...], ...]
    postprocess: Callable[[CommonResult], CommonResult] | None = None
    extra_qc: Callable[[CommonResult], list[str]] | None = None
    bypass_critical_categories: tuple[str, ...] = ()

    def build_messages(self, text: str) -> list[dict[str, str]]:
        return [
            {"role": "system", "content": self.system_prompt},
            {
                "role": "user",
                "content": f"<input>\n{text.strip()}\n</input>",
            },
        ]
