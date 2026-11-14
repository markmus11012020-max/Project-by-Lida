"""Ruble cost estimates for AITUNNEL chat models.

AITUNNEL usually returns usage.cost_rub. When it is absent (for example in
tests or a different provider), fall back to the published per-million prices.
"""

from __future__ import annotations

from typing import Any

PRICES_RUB_PER_MILLION: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (30.0, 120.0),
    "gpt-4o-mini-2024-07-18": (30.0, 120.0),
    "gpt-4.1-mini": (80.0, 320.0),
    "gpt-5-mini": (50.0, 400.0),
    "deepseek-v4-flash": (18.2, 36.4),
    "deepseek-v4.1-flash": (9.0, 100.0),
    "deepseek-v4.1-flash-1017": (30.0, 120.0),
}


def estimate_cost_rub(
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
) -> float:
    prompt_price, completion_price = PRICES_RUB_PER_MILLION.get(
        model, (30.0, 120.0)
    )
    cost = (
        prompt_tokens / 1_000_000 * prompt_price
        + completion_tokens / 1_000_000 * completion_price
    )
    return round(cost, 6)


def cost_from_usage(usage: dict[str, Any], model: str) -> float:
    raw = usage.get("cost_rub")
    if raw is not None:
        try:
            return round(float(raw), 6)
        except (TypeError, ValueError):
            pass
    try:
        prompt_tokens = int(usage.get("prompt_tokens") or 0)
        completion_tokens = int(usage.get("completion_tokens") or 0)
    except (TypeError, ValueError):
        return 0.0
    return estimate_cost_rub(model, prompt_tokens, completion_tokens)
