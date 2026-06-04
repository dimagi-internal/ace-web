"""Smoke-test that config.settings.production imports + has the DB pool wired.

CI + local tests run on config.settings.test (sqlite), so production-only
config (the bounded psycopg pool, connect_timeout) is otherwise never
exercised until deploy — where a typo/missing-dep is a failed rollout. This
imports production settings in a subprocess with dummy env and asserts the
pool config, closing that gap."""
import json
import os
import subprocess
import sys


def test_production_settings_import_and_pool_config():
    env = {
        **os.environ,
        "DJANGO_SETTINGS_MODULE": "config.settings.production",
        "ACE_FIELD_ENCRYPTION_KEY": "x" * 32,
        "DJANGO_SECRET_KEY": "dummy-not-real",
        "DJANGO_ALLOWED_HOSTS": "localhost",
        "DATABASE_URL": "postgres://u:p@localhost:5432/db",
    }
    code = (
        "import django; django.setup();"
        "from django.conf import settings as s;"
        "o=s.DATABASES['default'];"
        "import json;"
        "print(json.dumps({'pool':o['OPTIONS'].get('pool'),"
        "'ct':o['OPTIONS'].get('connect_timeout'),"
        "'cma':o.get('CONN_MAX_AGE')}))"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code], env=env, capture_output=True, text=True,
    )
    assert proc.returncode == 0, f"production settings failed to import:\n{proc.stderr}"
    data = json.loads(proc.stdout.strip().splitlines()[-1])
    assert data["pool"] == {"min_size": 1, "max_size": 8, "timeout": 10}
    assert data["ct"] == 10
    assert data["cma"] == 0  # Django requires CONN_MAX_AGE=0 with a pool


def test_production_settings_pool_kill_switch():
    """DB_USE_POOL=false disables the pool (env kill-switch, no redeploy)."""
    env = {
        **os.environ,
        "DJANGO_SETTINGS_MODULE": "config.settings.production",
        "ACE_FIELD_ENCRYPTION_KEY": "x" * 32,
        "DJANGO_SECRET_KEY": "dummy-not-real",
        "DJANGO_ALLOWED_HOSTS": "localhost",
        "DATABASE_URL": "postgres://u:p@localhost:5432/db",
        "DB_USE_POOL": "false",
    }
    code = (
        "import django; django.setup();"
        "from django.conf import settings as s;"
        "print('pool' in s.DATABASES['default']['OPTIONS'])"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code], env=env, capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip().splitlines()[-1] == "False"
