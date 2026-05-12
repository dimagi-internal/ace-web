"""Test fixtures for ``apps/mobile/`` tests.

- ``fake_redis`` swaps the singleton module's sync Redis client for a
  fakeredis instance so lock semantics can be exercised without a real
  Redis. Auto-applied to every test file in this directory.
- ``stub_ec2`` / ``stub_ssm`` / ``stub_s3`` build pre-stubbed boto3
  clients via ``botocore.stub.Stubber``. They are wired into a fresh
  ``EmulatorController`` via the ``controller_factory`` fixture so each
  test gets a controller that talks only to its stubs.
- Settings overrides set the instance + bucket so ``_assert_configured``
  in views passes; tests can re-override per-case.

Also sets fake AWS env credentials for the test session — boto3's
``generate_presigned_url`` is *not* a wire call so Stubber can't
intercept it; it runs through the real SigV4 signer which requires
credentials present. We use obviously-fake values that won't accidentally
talk to a real account.
"""
from __future__ import annotations

import os
from typing import Any

import boto3
import fakeredis
import pytest
from botocore.stub import Stubber

from apps.mobile import jobs, singleton

os.environ.setdefault("AWS_ACCESS_KEY_ID", "test-access-key")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test-secret-key")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("AWS_SESSION_TOKEN", "test-session-token")


@pytest.fixture(autouse=True)
def fake_redis(monkeypatch):
    """Swap the singleton + jobs modules' Redis client for an in-memory
    fake. Both modules share the same backend in production (the
    cloud Redis URL) so tests use a single fakeredis instance for
    both, so a job's lifecycle and the singleton lock that wraps it
    are visible to each other within a test."""
    fake = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(singleton, "_sync_redis", None)
    monkeypatch.setattr(singleton, "_get_redis", lambda: fake)
    monkeypatch.setattr(jobs, "_sync_redis", None)
    monkeypatch.setattr(jobs, "_get_redis", lambda: fake)
    yield fake


@pytest.fixture(autouse=True)
def _clear_django_cache():
    """Reset Django's locmem cache between tests so cached probes
    (e.g. status's idle-marker cache) don't leak across cases."""
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def configured_settings(settings):
    settings.ACE_MOBILE_INSTANCE_ID = "i-0123456789abcdef0"
    settings.ACE_MOBILE_S3_BUCKET = "ace-mobile-artifacts-test"
    settings.ACE_MOBILE_AWS_REGION = "us-east-1"
    settings.ACE_MOBILE_AMI_VERSION = "v1"
    return settings


def _build_stub(service_name: str, region: str = "us-east-1") -> tuple[Any, Stubber]:
    client = boto3.client(service_name, region_name=region)
    stubber = Stubber(client)
    return client, stubber


@pytest.fixture
def stub_ec2():
    client, stubber = _build_stub("ec2")
    stubber.activate()
    yield client, stubber
    stubber.deactivate()


@pytest.fixture
def stub_ssm():
    client, stubber = _build_stub("ssm")
    stubber.activate()
    yield client, stubber
    stubber.deactivate()


@pytest.fixture
def stub_s3():
    client, stubber = _build_stub("s3")
    stubber.activate()
    yield client, stubber
    stubber.deactivate()


@pytest.fixture
def controller_factory(stub_ec2, stub_ssm, stub_s3):
    """Return a callable that builds an EmulatorController bound to the
    activated stubs. Tests queue responses on the matching stubber.
    """
    from apps.mobile.controller import EmulatorController

    ec2_client, ec2_stub = stub_ec2
    ssm_client, ssm_stub = stub_ssm
    s3_client, s3_stub = stub_s3

    def _make(
        *,
        instance_id: str = "i-0123456789abcdef0",
        s3_bucket: str = "ace-mobile-artifacts-test",
        region: str = "us-east-1",
        ami_version: str = "v1",
    ) -> EmulatorController:
        c = EmulatorController(
            instance_id=instance_id,
            region=region,
            s3_bucket=s3_bucket,
            ami_version=ami_version,
        )
        c._ec2 = ec2_client
        c._ssm = ssm_client
        c._s3 = s3_client
        return c

    _make.ec2_stub = ec2_stub  # type: ignore[attr-defined]
    _make.ssm_stub = ssm_stub  # type: ignore[attr-defined]
    _make.s3_stub = s3_stub  # type: ignore[attr-defined]
    return _make
