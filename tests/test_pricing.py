from __future__ import annotations

from app.pricing import cost_from_usage, estimate_cost_rub


def test_cost_estimate_for_default_model() -> None:
    assert estimate_cost_rub("gpt-4o-mini", 1_000_000, 1_000_000) == 150.0


def test_cost_estimate_for_prefixed_deepseek_model() -> None:
    assert (
        estimate_cost_rub(
            "deepseek/deepseek-v4.1-flash-1017",
            1_000_000,
            1_000_000,
        )
        == 150.0
    )


def test_cost_from_usage_prefers_reported_cost() -> None:
    usage = {
        "prompt_tokens": 1_000_000,
        "completion_tokens": 1_000_000,
        "cost_rub": 0.42,
    }
    assert cost_from_usage(usage, "gpt-4o-mini") == 0.42


def test_cost_from_usage_falls_back_to_estimate() -> None:
    usage = {"prompt_tokens": 1_000_000, "completion_tokens": 0}
    assert cost_from_usage(usage, "gpt-4o-mini") == 30.0
