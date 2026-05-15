"""Django Ninja v2 router for the mobile emulator surface."""
from __future__ import annotations

import logging
import threading
from typing import Annotated

from django.conf import settings
from django.http import HttpRequest, HttpResponse
from ninja import Path, Router

from apps.api.auth import session_auth
from apps.api.deps import require_write_global
from apps.api.errors import TYPE_NOT_FOUND, TYPE_VALIDATION, ProblemError

from .schemas import (
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

log = logging.getLogger(__name__)

router = Router(auth=session_auth, tags=["mobile"])


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _assert_configured() -> None:

    if not settings.ACE_MOBILE_INSTANCE_ID:
        raise ProblemError(
            503,
            "ACE_MOBILE_INSTANCE_ID is unset; deploy the mobile-runner Terraform stack first.",
            type_=TYPE_VALIDATION,
        )
    if not settings.ACE_MOBILE_S3_BUCKET:
        raise ProblemError(503, "ACE_MOBILE_S3_BUCKET is unset.", type_=TYPE_VALIDATION)


def _make_controller():
    from .controller import EmulatorController

    return EmulatorController(
        instance_id=settings.ACE_MOBILE_INSTANCE_ID,
        region=settings.ACE_MOBILE_AWS_REGION,
        s3_bucket=settings.ACE_MOBILE_S3_BUCKET,
        ami_version=settings.ACE_MOBILE_AMI_VERSION,
    )


def _to_payload(obj):
    from dataclasses import asdict, is_dataclass

    if is_dataclass(obj):
        d = asdict(obj)
        for k, v in list(d.items()):
            d[k] = _to_payload(v) if is_dataclass(v) else v
        return d
    if isinstance(obj, list):
        return [_to_payload(x) for x in obj]
    return obj


def _mobile_problem(e) -> ProblemError:

    return ProblemError(e.http_status, e.message, detail=e.code)


# ---------------------------------------------------------------------------
# GET /mobile/status
# ---------------------------------------------------------------------------


def get_mobile_status() -> dict:
    return {
        "instance_id": settings.ACE_MOBILE_INSTANCE_ID or None,
        "region": settings.ACE_MOBILE_AWS_REGION,
        "s3_bucket": settings.ACE_MOBILE_S3_BUCKET or None,
        "ami_version": settings.ACE_MOBILE_AMI_VERSION or None,
        "configured": bool(
            settings.ACE_MOBILE_INSTANCE_ID and settings.ACE_MOBILE_S3_BUCKET
        ),
    }


@router.get("/status", response={200: MobileStatusOut}, summary="Emulator status config")
def status(request: HttpRequest) -> HttpResponse:
    from django.http import JsonResponse

    payload = MobileStatusOut.model_validate(get_mobile_status()).model_dump(mode="json")
    return JsonResponse(payload)


# ---------------------------------------------------------------------------
# POST /mobile/ensure-running
# ---------------------------------------------------------------------------


def ensure_running_op(state: str | None = None) -> dict:
    from .exceptions import MobileError

    _assert_configured()
    try:
        result = _make_controller().ensure_running(state_name=state)
    except MobileError as e:
        raise _mobile_problem(e) from e
    return _to_payload(result)


@router.post("/ensure-running", summary="Ensure emulator is running")
def ensure_running(request: HttpRequest, state: str | None = None) -> HttpResponse:
    from django.http import JsonResponse

    result = ensure_running_op(state=state)
    return JsonResponse(result)


# ---------------------------------------------------------------------------
# POST /mobile/stop
# ---------------------------------------------------------------------------


def stop_emulator(force: bool = False) -> dict:
    from .exceptions import MobileError

    _assert_configured()
    from . import singleton

    if not force:
        current = singleton.current_owner()
        if current:
            raise ProblemError(
                503,
                f"Emulator busy; singleton held by {current}",
                type_=TYPE_VALIDATION,
            )
    try:
        result = _make_controller().stop()
    except MobileError as e:
        raise _mobile_problem(e) from e
    return _to_payload(result)


@router.post("/stop", summary="Stop emulator")
def stop(request: HttpRequest, force: bool = False) -> HttpResponse:
    from django.http import JsonResponse

    result = stop_emulator(force=force)
    return JsonResponse(result)


# ---------------------------------------------------------------------------
# GET /mobile/diagnose
# ---------------------------------------------------------------------------


def diagnose_op() -> dict:
    from .exceptions import MobileError

    _assert_configured()
    try:
        diag = _make_controller().diagnose()
    except MobileError as e:
        raise _mobile_problem(e) from e
    return _to_payload(diag)


@router.get("/diagnose", response={200: DiagnoseOut}, summary="Diagnose emulator")
def diagnose(request: HttpRequest) -> HttpResponse:
    from django.http import JsonResponse

    result = diagnose_op()
    payload = DiagnoseOut.model_validate(result).model_dump(mode="json")
    return JsonResponse(payload)


# ---------------------------------------------------------------------------
# GET /mobile/states
# ---------------------------------------------------------------------------


def list_states_op() -> dict:
    from .exceptions import MobileError

    _assert_configured()
    try:
        catalog = _make_controller().list_states()
    except MobileError as e:
        raise _mobile_problem(e) from e
    return _to_payload(catalog)


@router.get("/states", response={200: StatesCatalogOut}, summary="List emulator states")
def states(request: HttpRequest) -> HttpResponse:
    from django.http import JsonResponse

    result = list_states_op()
    payload = StatesCatalogOut.model_validate(result).model_dump(mode="json")
    return JsonResponse(payload)


# ---------------------------------------------------------------------------
# POST /mobile/states/select — select an active state
# ---------------------------------------------------------------------------


def select_state_op(state_name: str) -> dict:
    from .exceptions import MobileError

    _assert_configured()
    try:
        result = _make_controller().select_state(state_name=state_name)
    except MobileError as e:
        raise _mobile_problem(e) from e
    return _to_payload(result)


@router.post("/states/select", summary="Select active state")
def select_state(request: HttpRequest, state: str) -> HttpResponse:
    from django.http import JsonResponse

    result = select_state_op(state)
    return JsonResponse(result)


# ---------------------------------------------------------------------------
# POST /mobile/snapshots/save
# ---------------------------------------------------------------------------


def save_snapshot_op(name: str) -> dict:
    from .exceptions import MobileError

    _assert_configured()
    try:
        result = _make_controller().save_snapshot(name=name)
    except MobileError as e:
        raise _mobile_problem(e) from e
    return _to_payload(result)


@router.post("/snapshots/save", summary="Save emulator snapshot")
def save_snapshot(request: HttpRequest, body: SnapshotIn) -> HttpResponse:
    from django.http import JsonResponse

    result = save_snapshot_op(body.name)
    return JsonResponse(result)


# ---------------------------------------------------------------------------
# POST /mobile/snapshots/load
# ---------------------------------------------------------------------------


def load_snapshot_op(name: str) -> dict:
    from .exceptions import MobileError

    _assert_configured()
    try:
        result = _make_controller().load_snapshot(name=name)
    except MobileError as e:
        raise _mobile_problem(e) from e
    return _to_payload(result)


@router.post("/snapshots/load", summary="Load emulator snapshot")
def load_snapshot(request: HttpRequest, body: SnapshotIn) -> HttpResponse:
    from django.http import JsonResponse

    result = load_snapshot_op(body.name)
    return JsonResponse(result)


# ---------------------------------------------------------------------------
# POST /mobile/run-recipe — async (202 + job_id)
# ---------------------------------------------------------------------------


def submit_run_recipe(body: RunRecipeIn) -> dict:
    from .exceptions import MobileError

    _assert_configured()
    from . import jobs, singleton

    owner = singleton.make_owner()
    acquired, current = singleton.try_acquire(owner)
    if not acquired:
        raise ProblemError(
            503,
            f"Emulator busy; singleton held by {current or 'unknown'}",
            type_=TYPE_VALIDATION,
        )

    recipe_yaml = body.recipe_yaml
    env = body.env or {}
    screenshot_prefix = body.screenshot_prefix
    requested_state = body.state

    def worker_holding(job_id: str) -> None:
        try:
            try:
                controller = _make_controller()
                if requested_state:
                    controller.ensure_running(state_name=requested_state)
                    singleton.refresh(owner)
                result = controller.run_recipe(
                    recipe_yaml=recipe_yaml,
                    env=env,
                    screenshot_prefix=screenshot_prefix,
                )
                jobs.mark_completed(job_id, _to_payload(result))
            except MobileError as e:
                jobs.mark_failed(job_id, error=e.message, error_code=e.code)
            except Exception as e:  # noqa: BLE001
                jobs.mark_failed(
                    job_id,
                    error=f"unexpected error: {e}",
                    error_code="unexpected-error",
                    include_traceback=True,
                )
        finally:
            singleton.release(owner)

    job_id = jobs.make_job_id()
    job = jobs.JobRecord(
        job_id=job_id,
        operation="run_recipe",
        status="running",
        owner=owner,
        started_at=jobs._iso_now(),  # noqa: SLF001
    )
    jobs.write(job)
    try:
        threading.Thread(
            target=worker_holding,
            args=(job_id,),
            name=f"mobile-job-{job_id}",
            daemon=True,
        ).start()
    except Exception as e:  # noqa: BLE001
        singleton.release(owner)
        jobs.mark_failed(
            job_id, error=f"failed to start worker: {e}", error_code="thread-start-failed"
        )
        raise ProblemError(
            500, f"Could not start worker thread: {e}", type_=TYPE_VALIDATION
        ) from e

    return {"job_id": job_id, "status": "running"}


@router.post(
    "/run-recipe",
    response={202: RunRecipeAcceptedOut},
    summary="Submit recipe for async execution",
)
def run_recipe(request: HttpRequest, body: RunRecipeIn) -> HttpResponse:
    from django.http import JsonResponse

    result = submit_run_recipe(body)
    payload = RunRecipeAcceptedOut.model_validate(result).model_dump(mode="json")
    return JsonResponse(payload, status=202)


# ---------------------------------------------------------------------------
# GET /mobile/jobs/{job_id} — poll job status
# ---------------------------------------------------------------------------


def get_job_status(job_id: str) -> dict | None:
    from . import jobs

    _assert_configured()
    rec = jobs.read(job_id)
    if rec is None:
        return None
    return rec.to_dict()


@router.get("/jobs/{job_id}", response={200: JobOut}, summary="Poll async job status")
def get_job(
    request: HttpRequest,
    job_id: Annotated[str, Path()],
) -> HttpResponse:
    from django.http import JsonResponse

    result = get_job_status(job_id)
    if result is None:
        raise ProblemError(404, f"Job {job_id!r} not found or expired", type_=TYPE_NOT_FOUND)
    payload = JobOut.model_validate(result).model_dump(mode="json")
    return JsonResponse(payload)


# ---------------------------------------------------------------------------
# POST /mobile/apk/install
# ---------------------------------------------------------------------------


def install_apk_op(apk_url: str) -> dict:
    from .exceptions import MobileError

    _assert_configured()
    try:
        result = _make_controller().install_apk(apk_url=apk_url)
    except MobileError as e:
        raise _mobile_problem(e) from e
    return _to_payload(result)


@router.post("/apk/install", summary="Install APK")
def install_apk(request: HttpRequest, apk_url: str) -> HttpResponse:
    from django.http import JsonResponse

    result = install_apk_op(apk_url)
    return JsonResponse(result)


# ---------------------------------------------------------------------------
# POST /mobile/capture-ui-dump
# ---------------------------------------------------------------------------


@router.post("/capture-ui-dump", summary="Capture UI dump")
def capture_ui_dump(request: HttpRequest) -> HttpResponse:
    from django.http import JsonResponse

    from .exceptions import MobileError

    _assert_configured()
    try:
        xml = _make_controller().capture_ui_dump()
    except MobileError as e:
        raise _mobile_problem(e) from e
    return JsonResponse({"xml": xml})


# ---------------------------------------------------------------------------
# POST /mobile/screenshot
# ---------------------------------------------------------------------------


@router.post("/screenshot", summary="Take screenshot")
def screenshot(request: HttpRequest) -> HttpResponse:
    from django.http import JsonResponse

    from .exceptions import MobileError

    _assert_configured()
    try:
        artifact = _make_controller().capture_screenshot()
    except MobileError as e:
        raise _mobile_problem(e) from e
    return JsonResponse(_to_payload(artifact))


# ---------------------------------------------------------------------------
# POST /mobile/restart-runner
# ---------------------------------------------------------------------------


def restart_runner_op(wait_for_ready: bool = True) -> dict:
    from .exceptions import MobileError

    _assert_configured()
    try:
        diag = _make_controller().restart_runner(wait_for_ready=wait_for_ready)
    except MobileError as e:
        raise _mobile_problem(e) from e
    return _to_payload(diag)


@router.post("/restart-runner", summary="Restart the in-VM mobile runner")
def restart_runner(
    request: HttpRequest, wait_for_ready: bool = True
) -> HttpResponse:
    from django.http import JsonResponse

    result = restart_runner_op(wait_for_ready=wait_for_ready)
    return JsonResponse(result)


# ---------------------------------------------------------------------------
# POST /mobile/admin/patch-launch-script (admin)
# ---------------------------------------------------------------------------


def patch_launch_script_op(user, body: LaunchScriptPatchIn) -> dict:
    from .exceptions import MobileError
    from .models import MobileLaunchScriptPatch

    _assert_configured()
    try:
        result = _make_controller().patch_launch_script(
            script_body=body.script_body,
            restart=body.restart_runner,
        )
    except MobileError as e:
        raise _mobile_problem(e) from e

    patch = MobileLaunchScriptPatch.objects.create(
        user=user,
        sha256=result.get("sha256", ""),
        bytes_written=result.get("bytes_written", 0),
        restart_requested=bool(result.get("restarted_runner")),
        instance_id=settings.ACE_MOBILE_INSTANCE_ID,
        ami_version=settings.ACE_MOBILE_AMI_VERSION or "",
    )
    return {
        "id": patch.id,
        "created_at": patch.created_at,
        "user_id": patch.user_id,
        "user_email": user.email,
        "sha256": patch.sha256,
        "bytes_written": patch.bytes_written,
        "restart_requested": patch.restart_requested,
        "instance_id": patch.instance_id,
        "ami_version": patch.ami_version,
    }


@router.post(
    "/admin/patch-launch-script",
    response={200: LaunchScriptPatchOut},
    summary="Admin: patch in-VM launch script",
)
def admin_patch_launch_script(
    request: HttpRequest, body: LaunchScriptPatchIn
) -> HttpResponse:
    from django.http import JsonResponse

    require_write_global(request)
    result = patch_launch_script_op(request.user, body)
    payload = LaunchScriptPatchOut.model_validate(result).model_dump(mode="json")
    return JsonResponse(payload)


# ---------------------------------------------------------------------------
# GET /mobile/admin/launch-script-patches (admin)
# ---------------------------------------------------------------------------


def list_launch_script_patches(offset: int = 0, limit: int = 50) -> dict:
    from .models import MobileLaunchScriptPatch

    qs = MobileLaunchScriptPatch.objects.select_related("user").order_by("-created_at")
    total = qs.count()
    page = qs[offset: offset + limit]
    patches = [
        {
            "id": p.id,
            "created_at": p.created_at.isoformat(),
            "user_id": p.user_id,
            "user_email": p.user.email,
            "sha256": p.sha256,
            "bytes_written": p.bytes_written,
            "restart_requested": p.restart_requested,
            "instance_id": p.instance_id,
            "ami_version": p.ami_version,
        }
        for p in page
    ]
    return {"patches": patches, "total": total, "limit": limit, "offset": offset}


@router.get(
    "/admin/launch-script-patches",
    summary="Admin: list launch script patches",
)
def admin_list_launch_script_patches(
    request: HttpRequest,
    offset: int = 0,
    limit: int = 50,
) -> HttpResponse:
    from django.http import JsonResponse

    require_write_global(request)
    if limit < 1 or limit > 500:
        raise ProblemError(400, "limit must be between 1 and 500", type_=TYPE_VALIDATION)
    if offset < 0:
        raise ProblemError(400, "offset must be >= 0", type_=TYPE_VALIDATION)
    result = list_launch_script_patches(offset=offset, limit=limit)
    return JsonResponse(result)
