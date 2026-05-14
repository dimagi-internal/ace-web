"""Pydantic v2 schemas for the mobile emulator surface.

Shapes mirror the controller dataclasses in ``apps.mobile.controller``
and the response dicts built in ``apps.mobile.views``.  Controller
dataclasses are serialized via ``dataclasses.asdict`` before reaching
the view, so field names are a direct match.

``DiagnoseOut`` uses ``extra="allow"`` because ``Diagnostics.adb_devices``
contains ``AdbDevice`` dataclasses whose inner fields could grow across
AMI versions without a breaking schema change here.
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from pydantic import ConfigDict

from apps.common.schemas import StrictModel

JobStatus = Literal["running", "completed", "failed"]


# ── Status ────────────────────────────────────────────────────────────────────


class MobileStatusOut(StrictModel):
    """GET /api/mobile/status response — configuration snapshot.

    Does NOT probe the EC2 instance; just surfaces the Django settings.
    ``configured`` is True only when both instance_id and s3_bucket are set.
    """

    instance_id: str | None = None
    region: str
    s3_bucket: str | None = None
    ami_version: str | None = None
    configured: bool


# ── Run-recipe ────────────────────────────────────────────────────────────────


class RunRecipeIn(StrictModel):
    """POST /api/mobile/run-recipe — kick off a Maestro recipe.

    ``recipe_yaml`` is the YAML string; ``env`` overrides env vars inside
    the recipe; ``screenshot_prefix`` sets the S3 key namespace;
    ``state`` names the baked AVD snapshot to ensure is loaded before
    the recipe runs.
    """

    recipe_yaml: str
    env: dict[str, str] = {}
    screenshot_prefix: str | None = None
    state: str | None = None


class RunRecipeAcceptedOut(StrictModel):
    """202 response — recipe accepted, poll jobs/<job_id> for result."""

    job_id: str
    status: Literal["running"] = "running"


# ── Job polling ───────────────────────────────────────────────────────────────


class JobOut(StrictModel):
    """GET /api/mobile/jobs/<id> response — async job status.

    ``result`` is populated on ``status="completed"`` with the same
    shape ``run_recipe`` would have returned synchronously.
    ``error`` / ``error_code`` are populated on ``status="failed"``.
    Uses ``extra="allow"`` so future job fields don't require a schema bump.
    """

    model_config = ConfigDict(extra="allow", from_attributes=True, str_strip_whitespace=True)

    job_id: str
    operation: str
    status: JobStatus
    owner: str
    started_at: str   # ISO-8601 string (the jobs module stores strings)
    completed_at: str | None = None
    result: Any = None
    error: str | None = None
    error_code: str | None = None


# ── Diagnose ──────────────────────────────────────────────────────────────────


class DiagnoseOut(StrictModel):
    """GET /api/mobile/diagnose response — in-VM emulator diagnostics.

    Fields mirror ``Diagnostics`` dataclass in ``apps.mobile.controller``.
    ``extra="allow"`` so new fields added to the dataclass don't need a
    simultaneous schema update.
    """

    model_config = ConfigDict(extra="allow", from_attributes=True, str_strip_whitespace=True)

    ssm_ok: bool = True
    ssm_error: str | None = None
    adb_devices: list[dict[str, Any]] = []
    adb_visible_count: int = 0
    emulator_pid: int | None = None
    emulator_cmdline: str | None = None
    runner_service_state: str | None = None
    marker_present: bool = False
    marker_age_seconds: int | None = None
    runner_log_tail: str = ""
    emulator_log_tail: str = ""


# ── State catalog ─────────────────────────────────────────────────────────────


class StateOut(StrictModel):
    """One named state baked into the AMI."""

    name: str
    snapshot: str
    commcare_version: str
    description: str = ""


class StatesCatalogOut(StrictModel):
    """GET /api/mobile/states response."""

    default: str
    states: list[StateOut]
    active: str | None = None


# ── Snapshot ──────────────────────────────────────────────────────────────────


class SnapshotIn(StrictModel):
    """POST /api/mobile/save-snapshot and /api/mobile/load-snapshot body."""

    name: str


class SnapshotResultOut(StrictModel):
    """Response from save/load-snapshot operations."""

    name: str
    saved_at: str | None = None
    loaded_at: str | None = None


# ── Launch script patch ───────────────────────────────────────────────────────


class LaunchScriptPatchIn(StrictModel):
    """POST /api/mobile/admin/patch-launch-script body.

    ``restart_runner`` (default True) asks the controller to restart the
    in-VM ace-mobile-runner systemd unit immediately so the patch takes
    effect without a cold reboot.
    """

    script_body: str
    restart_runner: bool = True


class LaunchScriptPatchOut(StrictModel):
    """Audit row echoed back from a successful patch operation."""

    id: int
    created_at: dt.datetime
    user_id: int
    user_email: str
    sha256: str
    bytes_written: int
    restart_requested: bool
    instance_id: str
    ami_version: str = ""
