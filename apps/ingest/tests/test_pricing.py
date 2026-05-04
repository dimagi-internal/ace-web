def test_compute_cost_opus_4_7_uses_new_rates():
    """Opus 4.5+ dropped to $5/$25 input/output (was $15/$75 for Opus 4.0/4.1)."""
    from apps.ingest.pricing import compute_cost
    cost = compute_cost(
        model="claude-opus-4-7",
        usage={"input_tokens": 1_000_000, "output_tokens": 0,
               "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0},
    )
    assert cost == 5.0


def test_compute_cost_opus_4_1_uses_legacy_rates():
    """Opus 4.0/4.1 stay at the original $15 input rate."""
    from apps.ingest.pricing import compute_cost
    cost = compute_cost(
        model="claude-opus-4-1-20250805",
        usage={"input_tokens": 1_000_000, "output_tokens": 0,
               "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0},
    )
    assert cost == 15.0


def test_compute_cost_opus_4_7_full_breakdown():
    """Opus 4.7: 0.1*5 + 0.05*25 + 0.2*6.25 + 1.0*0.5 = 0.5 + 1.25 + 1.25 + 0.5 = 3.5"""
    from apps.ingest.pricing import compute_cost
    cost = compute_cost(
        model="claude-opus-4-7",
        usage={"input_tokens": 100_000, "output_tokens": 50_000,
               "cache_creation_input_tokens": 200_000,
               "cache_read_input_tokens": 1_000_000},
    )
    assert round(cost, 4) == 3.5


def test_compute_cost_opus_4_7_with_1h_cache_tier():
    """When usage.cache_creation breaks out 5m vs 1h, charge each at its own
    rate. 5m=200k * $6.25/M = $1.25; 1h=100k * $10/M = $1.00. Total = $2.25."""
    from apps.ingest.pricing import compute_cost
    cost = compute_cost(
        model="claude-opus-4-7",
        usage={
            "input_tokens": 0, "output_tokens": 0,
            # legacy flat field, ignored when nested present
            "cache_creation_input_tokens": 300_000,
            "cache_read_input_tokens": 0,
            "cache_creation": {
                "ephemeral_5m_input_tokens": 200_000,
                "ephemeral_1h_input_tokens": 100_000,
            },
        },
    )
    assert round(cost, 4) == 2.25


def test_compute_cost_falls_back_to_5m_when_cache_creation_object_absent():
    """Older API responses without the nested object: treat all cache_creation
    as 5m-tier (preserves prior behavior)."""
    from apps.ingest.pricing import compute_cost
    cost = compute_cost(
        model="claude-opus-4-7",
        usage={"input_tokens": 0, "output_tokens": 0,
               "cache_creation_input_tokens": 1_000_000,
               "cache_read_input_tokens": 0},
    )
    # 1M * $6.25/M = $6.25 (5m rate, not 1h)
    assert round(cost, 4) == 6.25


def test_compute_cost_sonnet_uses_sonnet_rates():
    from apps.ingest.pricing import compute_cost
    cost = compute_cost(
        model="claude-sonnet-4-6",
        usage={"input_tokens": 1_000_000, "output_tokens": 0,
               "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0},
    )
    assert cost == 3.0


def test_compute_cost_haiku_uses_haiku_rates():
    from apps.ingest.pricing import compute_cost
    cost = compute_cost(
        model="claude-haiku-4-5-20251001",
        usage={"input_tokens": 1_000_000, "output_tokens": 0,
               "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0},
    )
    assert cost == 1.0


def test_compute_cost_unknown_model_returns_none():
    from apps.ingest.pricing import compute_cost
    cost = compute_cost(
        model="some-future-model",
        usage={"input_tokens": 1000, "output_tokens": 0,
               "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0},
    )
    assert cost is None


def test_compute_cost_missing_usage_returns_zero():
    from apps.ingest.pricing import compute_cost
    cost = compute_cost(model="claude-opus-4-7", usage={})
    assert cost == 0.0


def test_compute_cost_none_model_returns_none():
    from apps.ingest.pricing import compute_cost
    cost = compute_cost(model=None, usage={"input_tokens": 1000})
    assert cost is None


def test_resolve_rates_picks_longest_prefix():
    """claude-opus-4-7 should match claude-opus-4-7 (specific) over claude-opus-4 (broad)."""
    from apps.ingest.pricing import _resolve_rates
    rates = _resolve_rates("claude-opus-4-7-20251101")
    assert rates is not None
    assert rates["input"] == 5.0  # not 15.0
