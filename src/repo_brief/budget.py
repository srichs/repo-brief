"""Cost and usage accounting for repo-brief runs."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

DEFAULT_PRICING_PER_1M = {
    "gpt-4.1-mini": {"in": 0.40, "out": 1.60, "cached_in": 0.10},
    "gpt-4.1": {"in": 2.00, "out": 8.00, "cached_in": 0.50},
    "_default": {"in": 1.00, "out": 4.00, "cached_in": 0.25},
}

ENV_PRICE_IN = os.getenv("PRICE_IN_PER_1M")
ENV_PRICE_OUT = os.getenv("PRICE_OUT_PER_1M")
ENV_PRICE_CACHED_IN = os.getenv("PRICE_CACHED_IN_PER_1M")


@dataclass
class Pricing:
    """Model pricing information used to estimate prompt/completion costs."""

    in_per_1m: float
    out_per_1m: float
    cached_in_per_1m: float

    @staticmethod
    def for_model(
        model: str,
        price_in: float | None,
        price_out: float | None,
        price_cached_in: float | None,
    ) -> Pricing:
        """Resolve pricing from CLI overrides, environment, or defaults."""
        if price_in is not None and price_out is not None:
            return Pricing(
                in_per_1m=price_in,
                out_per_1m=price_out,
                cached_in_per_1m=(
                    price_cached_in
                    if price_cached_in is not None
                    else DEFAULT_PRICING_PER_1M["_default"]["cached_in"]
                ),
            )

        if ENV_PRICE_IN and ENV_PRICE_OUT:
            return Pricing(
                in_per_1m=float(ENV_PRICE_IN),
                out_per_1m=float(ENV_PRICE_OUT),
                cached_in_per_1m=(
                    float(ENV_PRICE_CACHED_IN)
                    if ENV_PRICE_CACHED_IN
                    else DEFAULT_PRICING_PER_1M["_default"]["cached_in"]
                ),
            )

        entry = DEFAULT_PRICING_PER_1M.get(model, DEFAULT_PRICING_PER_1M["_default"])
        return Pricing(
            in_per_1m=entry["in"],
            out_per_1m=entry["out"],
            cached_in_per_1m=entry.get("cached_in", 0.0),
        )


def usage_totals(result: Any) -> dict[str, int]:
    """Aggregate token usage totals from an Agents SDK result object."""
    entries = result.context_wrapper.usage.request_usage_entries
    in_tokens = sum(getattr(entry, "input_tokens", 0) for entry in entries)
    out_tokens = sum(getattr(entry, "output_tokens", 0) for entry in entries)
    cached_in = sum(getattr(entry, "cached_input_tokens", 0) for entry in entries)
    return {
        "input_tokens": int(in_tokens),
        "output_tokens": int(out_tokens),
        "cached_input_tokens": int(cached_in),
        "total_tokens": int(in_tokens + out_tokens),
        "requests": len(entries),
    }


def estimate_cost_usd(result: Any, pricing: Pricing) -> float:
    """Estimate USD cost for a run result using configured pricing."""
    totals = usage_totals(result)
    in_cost = (totals["input_tokens"] / 1_000_000.0) * pricing.in_per_1m
    out_cost = (totals["output_tokens"] / 1_000_000.0) * pricing.out_per_1m
    cached_cost = (totals["cached_input_tokens"] / 1_000_000.0) * pricing.cached_in_per_1m
    return float(in_cost + out_cost + cached_cost)


def validate_price_overrides(price_in: float | None, price_out: float | None) -> None:
    """Ensure token price overrides are provided as a pair."""
    if (price_in is None) != (price_out is None):
        raise ValueError("--price-in and --price-out must be provided together")
