"""Round-trip tests for apps.mobile.schemas."""
from __future__ import annotations

import datetime as dt

from apps.mobile.schemas import (
    ClearAppDataIn,
    ClearAppDataOut,
    DiagnoseOut,
    InstallDriverOut,
    JobOut,
    LaunchScriptPatchIn,
    LaunchScriptPatchOut,
    MobileStatusOut,
    RegisterTestUserAcceptedOut,
    RegisterTestUserIn,
    RegisterTestUserResultOut,
    RepairDriverOut,
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


def test_clear_app_data_in_default_package():
    body = ClearAppDataIn()
    assert body.package == "org.commcare.dalvik"


def test_clear_app_data_in_accepts_valid_package():
    body = ClearAppDataIn(package="com.example.thing")
    assert body.package == "com.example.thing"


def test_clear_app_data_in_rejects_shell_unsafe_package():
    import pytest
    from pydantic import ValidationError

    for bad in ["foo;rm -rf /", "$(id)", "com.foo bar", "-flag"]:
        with pytest.raises(ValidationError, match="package must match"):
            ClearAppDataIn(package=bad)


def test_clear_app_data_out():
    out = ClearAppDataOut(package="org.commcare.dalvik", cleared=True)
    assert out.cleared is True


def test_repair_driver_out_empty():
    out = RepairDriverOut(uninstalled_packages=[])
    assert out.uninstalled_packages == []


def test_repair_driver_out_with_packages():
    out = RepairDriverOut(
        uninstalled_packages=["dev.mobile.maestro", "dev.mobile.maestro.test"]
    )
    assert len(out.uninstalled_packages) == 2


def test_install_driver_out_warm_path():
    out = InstallDriverOut(actions=["already-installed"])
    assert out.actions == ["already-installed"]


def test_install_driver_out_cold_path():
    out = InstallDriverOut(
        actions=["pm-ready", "extracted", "installed:app", "installed:test", "verified"]
    )
    assert len(out.actions) == 5
    assert out.actions[-1] == "verified"


# ── RegisterTestUser ─────────────────────────────────────────────────


_REGISTER_IN = {
    "phone": "+74260000100",
    "phone_local": "4260000100",
    "country_code": "+7",
    "pin": "111111",
    "backup_code": "222222",
    "name": "ACE Test",
    "palette_tar_b64": "ZmFrZS10YXJiYWxs",
    "to_otp_recipe": "connect-register-to-otp.yaml",
    "from_otp_recipe": "connect-register-from-otp.yaml",
}


def test_register_test_user_in_accepts_valid_demo_credentials():
    body = RegisterTestUserIn(**_REGISTER_IN)
    assert body.phone == "+74260000100"
    assert body.to_otp_recipe == "connect-register-to-otp.yaml"


def test_register_test_user_in_rejects_path_traversal_recipe_name():
    import pytest
    from pydantic import ValidationError

    for bad in [
        "../../etc/passwd",
        "subdir/recipe.yaml",
        "recipe.yml.sh",
        "no-extension",
        "recipe",
    ]:
        body = dict(_REGISTER_IN, to_otp_recipe=bad)
        with pytest.raises(ValidationError):
            RegisterTestUserIn(**body)


def test_register_test_user_in_accepts_both_yaml_extensions():
    body_yaml = RegisterTestUserIn(**dict(_REGISTER_IN, to_otp_recipe="recipe.yaml"))
    body_yml = RegisterTestUserIn(**dict(_REGISTER_IN, to_otp_recipe="recipe.yml"))
    assert body_yaml.to_otp_recipe == "recipe.yaml"
    assert body_yml.to_otp_recipe == "recipe.yml"


def test_register_test_user_in_rejects_oversized_palette():
    import pytest
    from pydantic import ValidationError

    body = dict(_REGISTER_IN, palette_tar_b64="A" * (256 * 1024 + 1))
    with pytest.raises(ValidationError, match="palette_tar_b64 exceeds 256 KB"):
        RegisterTestUserIn(**body)


def test_register_test_user_in_rejects_non_digit_phone():
    import pytest
    from pydantic import ValidationError

    body = dict(_REGISTER_IN, phone_local="+74260000100")  # leading + not allowed on phone_local
    with pytest.raises(ValidationError):
        RegisterTestUserIn(**body)


def test_register_test_user_in_rejects_country_code_without_plus():
    import pytest
    from pydantic import ValidationError

    body = dict(_REGISTER_IN, country_code="7")
    with pytest.raises(ValidationError):
        RegisterTestUserIn(**body)


def test_register_test_user_in_rejects_non_digit_pin():
    import pytest
    from pydantic import ValidationError

    for bad in [("pin", "abc123"), ("backup_code", "12;34")]:
        with pytest.raises(ValidationError):
            RegisterTestUserIn(**dict(_REGISTER_IN, **{bad[0]: bad[1]}))


def test_register_test_user_accepted_out_default_status():
    out = RegisterTestUserAcceptedOut(job_id="job-abc")
    assert out.status == "running"


def test_register_test_user_result_out_already_registered_omits_backup():
    out = RegisterTestUserResultOut(already_registered=True, phone="+74260000100")
    assert out.backup_code is None


def test_register_test_user_result_out_fresh_carries_backup():
    out = RegisterTestUserResultOut(
        already_registered=False, phone="+74260000100", backup_code="222222"
    )
    assert out.backup_code == "222222"
