import importlib
import sys

import pytest


def test_prod_settings_require_field_encryption_key(monkeypatch):
    monkeypatch.delenv("ACE_FIELD_ENCRYPTION_KEY", raising=False)
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "config.settings.production")
    # Make sure required env vars for production.py exist so we hit our
    # check, not an unrelated KeyError.
    monkeypatch.setenv("DJANGO_SECRET_KEY", "test")
    monkeypatch.setenv("DJANGO_ALLOWED_HOSTS", "x")
    for mod in list(sys.modules):
        if mod.startswith("config.settings"):
            del sys.modules[mod]
    with pytest.raises(RuntimeError, match="ACE_FIELD_ENCRYPTION_KEY"):
        importlib.import_module("config.settings.production")
