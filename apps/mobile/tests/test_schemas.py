"""Round-trip tests for apps.mobile.schemas."""
from __future__ import annotations

import datetime as dt

from apps.mobile.schemas import (
    DiagnoseOut,
    JobOut,
    LaunchScriptPatchIn,
    LaunchScriptPatchOut,
    MobileStatusOut,
    RunRecipeAcceptedOut,
    RunRecipeIn,
    SnapshotIn,
    StatesCatalogOut,
)


def test_mobile_status_out_unconfigured():
    s = MobileStatusOut(
        instance_id=None,
        region="us-east-1",
        s3_bucket=None,
        ami_version=None,
        configured=False,
    )
    assert s.configured is False
    assert s.instance_id is None


def test_mobile_status_out_configured():
    s = MobileStatusOut(
        instance_id="i-abc123",
        region="us-east-1",
        s3_bucket="ace-mobile-bucket",
        ami_version="v7",
        configured=True,
    )
    assert s.configured is True


def test_run_recipe_in_defaults():
    r = RunRecipeIn(recipe_yaml="appId: com.example\n---\n- tapOn: Submit")
    assert r.env == {}
    assert r.screenshot_prefix is None
    assert r.state is None
    assert r.palette_tar_b64 is None


def test_run_recipe_in_accepts_palette():
    r = RunRecipeIn(
        recipe_yaml="appId: com.example\n---\n- tapOn: Submit",
        palette_tar_b64="dGVzdA==",
    )
    assert r.palette_tar_b64 == "dGVzdA=="


def test_run_recipe_in_rejects_oversized_palette():
    import pytest
    from pydantic import ValidationError

    huge = "A" * (256 * 1024 + 1)
    with pytest.raises(ValidationError, match="palette_tar_b64 exceeds 256 KB"):
        RunRecipeIn(recipe_yaml="appId: x\n", palette_tar_b64=huge)


def test_run_recipe_accepted_out():
    out = RunRecipeAcceptedOut(job_id="deadbeef01234567")
    assert out.status == "running"
    assert len(out.job_id) == 16


def test_job_out_running():
    job = JobOut(
        job_id="abc",
        operation="run_recipe",
        status="running",
        owner="owner-1",
        started_at="2026-05-14T10:00:00+00:00",
    )
    assert job.completed_at is None
    assert job.result is None


def test_job_out_completed_extra_fields_allowed():
    job = JobOut(
        job_id="abc",
        operation="run_recipe",
        status="completed",
        owner="owner-1",
        started_at="2026-05-14T10:00:00+00:00",
        completed_at="2026-05-14T10:05:00+00:00",
        result={"exit_code": 0, "steps": []},
        some_future_field="hello",  # type: ignore[call-arg]
    )
    assert job.status == "completed"
    assert job.model_extra.get("some_future_field") == "hello"  # type: ignore[union-attr]


def test_diagnose_out_minimal():
    diag = DiagnoseOut()
    assert diag.ssm_ok is True
    assert diag.adb_devices == []


def test_states_catalog_out():
    from apps.mobile.schemas import StateOut
    cat = StatesCatalogOut(
        default="7plus",
        states=[StateOut(name="7plus", snapshot="snap-001", commcare_version="2.57.1")],
        active="7plus",
    )
    assert cat.active == "7plus"
    assert cat.states[0].commcare_version == "2.57.1"


def test_launch_script_patch_in_defaults():
    patch = LaunchScriptPatchIn(script_body="#!/bin/bash\necho ok\n")
    assert patch.restart_runner is True


def test_launch_script_patch_out_round_trip():
    _NOW = dt.datetime(2026, 5, 14, 10, 0, 0, tzinfo=dt.UTC)
    out = LaunchScriptPatchOut(
        id=42,
        created_at=_NOW,
        user_id=7,
        user_email="admin@dimagi.com",
        sha256="abc" * 21 + "a",  # 64 chars
        bytes_written=7168,
        restart_requested=True,
        instance_id="i-abc123",
        ami_version="v7",
    )
    assert out.id == 42
    assert out.bytes_written == 7168


def test_snapshot_in():
    s = SnapshotIn(name="7plus")
    assert s.name == "7plus"
