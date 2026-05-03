"""Per-model Anthropic pricing for cost-breakdown computation.

USD per million tokens. Source: anthropic.com/pricing.
**Last refreshed: 2026-05-03.**

Model id is matched by prefix — e.g. "claude-opus-4-7" matches the
"claude-opus-4" key, "claude-haiku-4-5-20251001" matches "claude-haiku-4".
Unknown model ids return None so the aggregator can flag the segment as
having partial pricing rather than silently zero-billing.
"""
from __future__ import annotations

from collections.abc import Mapping

PRICING: dict[str, dict[str, float]] = {
    "claude-opus-4":   {"input": 15.0, "output": 75.0, "cache_write": 18.75, "cache_read": 1.5},
    "claude-sonnet-4": {"input":  3.0, "output": 15.0, "cache_write":  3.75, "cache_read": 0.30},
    "claude-haiku-4":  {"input":  1.0, "output":  5.0, "cache_write":  1.25, "cache_read": 0.10},
}


def _resolve_rates(model: str | None) -> dict[str, float] | None:
    if not model:
        return None
    for prefix, rates in PRICING.items():
        if model.startswith(prefix):
            return rates
    return None


def compute_cost(model: str | None, usage: Mapping[str, int] | None) -> float | None:
    """Compute USD cost for one usage block.

    Returns None when ``model`` is unknown or missing.
    Returns 0.0 when ``usage`` is empty (known model, no tokens).
    """
    rates = _resolve_rates(model)
    if rates is None:
        return None
    if not usage:
        return 0.0
    inp = usage.get("input_tokens", 0) or 0
    out = usage.get("output_tokens", 0) or 0
    cw = usage.get("cache_creation_input_tokens", 0) or 0
    cr = usage.get("cache_read_input_tokens", 0) or 0
    return (
        inp / 1_000_000 * rates["input"]
        + out / 1_000_000 * rates["output"]
        + cw / 1_000_000 * rates["cache_write"]
        + cr / 1_000_000 * rates["cache_read"]
    )
