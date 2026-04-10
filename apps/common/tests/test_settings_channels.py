"""Smoke tests that the channel-layer configuration is what we intend
for each settings module. These prevent silent regressions if someone
reinstates `InMemoryChannelLayer` on a production path."""
import importlib


def test_base_settings_use_redis_channel_layer(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    # Force a fresh import so env is read.
    import config.settings.base as base
    importlib.reload(base)
    assert base.CHANNEL_LAYERS["default"]["BACKEND"] == (
        "channels_redis.core.RedisChannelLayer"
    )
    hosts = base.CHANNEL_LAYERS["default"]["CONFIG"]["hosts"]
    assert hosts == ["redis://localhost:6379/0"]


def test_test_settings_override_back_to_inmemory():
    import config.settings.test as test_settings
    importlib.reload(test_settings)
    assert test_settings.CHANNEL_LAYERS["default"]["BACKEND"] == (
        "channels.layers.InMemoryChannelLayer"
    )
