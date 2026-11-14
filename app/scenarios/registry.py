"""Scenario registry: one pipeline, three process configurations."""

from __future__ import annotations

from app.scenarios.base import ScenarioConfig
from app.scenarios.documents import SCENARIO as DOCUMENTS
from app.scenarios.sales import SCENARIO as SALES
from app.scenarios.support import SCENARIO as SUPPORT
from app.schemas import ScenarioKey

SCENARIOS: dict[ScenarioKey, ScenarioConfig] = {
    ScenarioKey.SUPPORT: SUPPORT,
    ScenarioKey.SALES: SALES,
    ScenarioKey.DOCUMENTS: DOCUMENTS,
}


def get_scenario(key: ScenarioKey | str) -> ScenarioConfig:
    normalized = key if isinstance(key, ScenarioKey) else ScenarioKey(key)
    return SCENARIOS[normalized]
