"""Per-model Anthropic pricing for cost-breakdown computation.

USD per million tokens. Source: platform.claude.com/docs/en/about-claude/pricing.
**Last refreshed: 2026-05-04.**

Rate tiers tracked per model family:

- ``input``         — base input rate
- ``output``        — output rate
- ``cache_write_5m``— prompt-caching write, 5-minute TTL  (1.25× input)
- ``cache_write_1h``— prompt-caching write, 1-hour TTL    (2.0×  input)
- ``cache_read``    — prompt-caching read                 (0.10× input)

Anthropic exposes the 5m vs 1h split inside ``usage.cache_creation`` as
``ephemeral_5m_input_tokens`` / ``ephemeral_1h_input_tokens``. The top-level
``cache_creation_input_tokens`` is the sum of both. ``compute_cost`` reads
the nested object when present and falls back to the flat field × 5m rate
otherwise.

Model id is matched by prefix; longest prefix wins. Order matters in PRICING
so that more-specific keys (e.g. ``claude-opus-4-5``) preempt broader ones
(``claude-opus-4-1``). Opus 4.0/4.1 used the older $15/$75 rates; Opus 4.5+
dropped to $5/$25 — index both.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

_OPUS_45_PLUS = {
    "input": 5.0, "output": 25.0,
    "cache_write_5m": 6.25, "cache_write_1h": 10.0, "cache_read": 0.50,
}
_OPUS_LEGACY = {
    "input": 15.0, "output": 75.0,
    "cache_write_5m": 18.75, "cache_write_1h": 30.0, "cache_read": 1.50,
}
_SONNET_4 = {
    "input": 3.0, "output": 15.0,
    "cache_write_5m": 3.75, "cache_write_1h": 6.0, "cache_read": 0.30,
}
_HAIKU_4 = {
    "input": 1.0, "output": 5.0,
    "cache_write_5m": 1.25, "cache_write_1h": 2.0, "cache_read": 0.10,
}

PRICING: dict[str, dict[str, float]] = {
    # Opus 4.5+ (current premium tier). Listed before "claude-opus-4" so the
    # longest-prefix matcher selects them ahead of the 4.0/4.1 fallback.
    "claude-opus-4-5": _OPUS_45_PLUS,
    "claude-opus-4-6": _OPUS_45_PLUS,
    "claude-opus-4-7": _OPUS_45_PLUS,
    # Opus 4.0 / 4.1 — original Opus 4.x family pricing.
    "claude-opus-4":   _OPUS_LEGACY,
    # Sonnet 4 / 4.5 / 4.6 — same rates across the family.
    "claude-sonnet-4": _SONNET_4,
    # Haiku 4.5 (only member of the 4.x Haiku family today).
    "claude-haiku-4":  _HAIKU_4,
}


def _resolve_rates(model: str | None) -> dict[str, float] | None:
    """Longest-prefix match. Returns None for unknown models."""
    if not model:
        return None
    best_prefix: str | None = None
    for prefix in PRICING:
        if model.startswith(prefix) and (best_prefix is None or len(prefix) > len(best_prefix)):
            best_prefix = prefix
    return PRICING.get(best_prefix) if best_prefix else None


def _split_cache_write(usage: Mapping[str, Any]) -> tuple[int, int]:
    """Return (5m_tokens, 1h_tokens) from a usage block.

    Prefer the nested ``cache_creation`` object if present (newer API
    responses). Otherwise fall back to the flat ``cache_creation_input_tokens``
    treated as 5m-tier (the historical default before the 1h TTL shipped).
    """
    nested = usage.get("cache_creation")
    if isinstance(nested, dict):
        five_m = int(nested.get("ephemeral_5m_input_tokens", 0) or 0)
        one_h = int(nested.get("ephemeral_1h_input_tokens", 0) or 0)
        return five_m, one_h
    flat = int(usage.get("cache_creation_input_tokens", 0) or 0)
    return flat, 0


def compute_cost(model: str | None, usage: Mapping[str, Any] | None) -> float | None:
    """Compute USD cost for one usage block.

    Returns None when ``model`` is unknown or missing.
    Returns 0.0 when ``usage`` is empty (known model, no tokens).
    """
    rates = _resolve_rates(model)
    if rates is None:
        return None
    if not usage:
        return 0.0
    inp = int(usage.get("input_tokens", 0) or 0)
    out = int(usage.get("output_tokens", 0) or 0)
    cw_5m, cw_1h = _split_cache_write(usage)
    cr = int(usage.get("cache_read_input_tokens", 0) or 0)
    return (
        inp / 1_000_000 * rates["input"]
        + out / 1_000_000 * rates["output"]
        + cw_5m / 1_000_000 * rates["cache_write_5m"]
        + cw_1h / 1_000_000 * rates["cache_write_1h"]
        + cr / 1_000_000 * rates["cache_read"]
    )
