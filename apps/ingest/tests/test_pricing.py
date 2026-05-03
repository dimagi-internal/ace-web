def test_compute_cost_opus_basic():
    from apps.ingest.pricing import compute_cost
    cost = compute_cost(
        model="claude-opus-4-7",
        usage={"input_tokens": 1_000_000, "output_tokens": 0,
               "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0},
    )
    assert cost == 15.0


def test_compute_cost_opus_full_breakdown():
    from apps.ingest.pricing import compute_cost
    cost = compute_cost(
        model="claude-opus-4-7",
        usage={"input_tokens": 100_000, "output_tokens": 50_000,
               "cache_creation_input_tokens": 200_000,
               "cache_read_input_tokens": 1_000_000},
    )
    # 0.1 * 15 + 0.05 * 75 + 0.2 * 18.75 + 1.0 * 1.5 = 1.5 + 3.75 + 3.75 + 1.5 = 10.5
    assert round(cost, 4) == 10.5


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
