"""HTTP API for the cloud Android emulator runner.

All endpoints share the project's ``{data, error}`` envelope and authenticate
via the global Bearer-token backend (``apps.auth.token_backend.BearerTokenAuthentication``),
which is already wired into ``REST_FRAMEWORK.DEFAULT_AUTHENTICATION_CLASSES``.

The controller class (``apps.mobile.controller.EmulatorController``) does
the work; views are thin: assert configured → validate input → (for
``run_recipe`` only) acquire singleton lock → dispatch → envelope.

The singleton lock only wraps ``run_recipe``. Other endpoints are short
enough not to need it. ``stop`` doesn't *take* the lock either — it just
*probes* ``singleton.current_owner()``: if a recipe is in flight it
refuses with ``singleton-busy`` 503, surfacing the current owner so the
caller can decide. ``{"force": true}`` bypasses the guard so a genuinely
hung recipe can still be aborted by tearing the instance down.
"""
from __future__ import annotations

import threading
from dataclasses import asdict, is_dataclass
from typing import Any

from django.conf import settings
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.common.auth_views import _can_write_global
from apps.common.envelope import error_response, success_response

from . import jobs, singleton
from .controller import EmulatorController
from .exceptions import EmulatorNotReady, MobileError, NotConfigured, SingletonBusy
from .models import MobileLaunchScriptPatch
from .serializers import (
    EnsureRunningSerializer,
    InstallApkSerializer,
    PatchLaunchScriptSerializer,
    RestartRunnerSerializer,
    RunRecipeSerializer,
    SnapshotSerializer,
    StateSerializer,
    StopSerializer,
)


def _assert_configured() -> None:
    if not settings.ACE_MOBILE_INSTANCE_ID:
        raise NotConfigured(
            "ACE_MOBILE_INSTANCE_ID is unset; deploy the mobile-runner Terraform stack first."
        )
    if not settings.ACE_MOBILE_S3_BUCKET:
        raise NotConfigured("ACE_MOBILE_S3_BUCKET is unset.")


def _make_controller() -> EmulatorController:
    return EmulatorController(
        instance_id=settings.ACE_MOBILE_INSTANCE_ID,
        region=settings.ACE_MOBILE_AWS_REGION,
        s3_bucket=settings.ACE_MOBILE_S3_BUCKET,
        ami_version=settings.ACE_MOBILE_AMI_VERSION,
    )


def _to_payload(obj: Any) -> Any:
    """Normalize a controller result for the JSON envelope.

    Dataclass → dict; list of dataclasses → list of dicts; primitives pass.
    """
    if is_dataclass(obj):
        d = asdict(obj)
        # Recurse for nested dataclasses (e.g. RunResult.artifacts).
        for k, v in list(d.items()):
            d[k] = _to_payload(v) if is_dataclass(v) else v
        return d
    if isinstance(obj, list):
        return [_to_payload(x) for x in obj]
    return obj


def _mobile_error_response(e: MobileError, extra: dict[str, Any] | None = None) -> Response:
    body = error_response(message=e.message, code=e.code)
    # EmulatorNotReady carries a Diagnostics snapshot captured at the
    # moment of failure; surface it on the error so callers see WHY
    # the emulator isn't usable without making a follow-up
    # /api/mobile/diagnose round-trip.
    if isinstance(e, EmulatorNotReady) and e.diagnostics:
        body["error"]["diagnostics"] = e.diagnostics
    if extra:
        body["error"].update(extra)
    return Response(body, status=e.http_status)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def status(request: Request) -> Response:
    payload = {
        "instance_id": settings.ACE_MOBILE_INSTANCE_ID or None,
        "region": settings.ACE_MOBILE_AWS_REGION,
        "s3_bucket": settings.ACE_MOBILE_S3_BUCKET or None,
        "ami_version": settings.ACE_MOBILE_AMI_VERSION or None,
        "configured": bool(
            settings.ACE_MOBILE_INSTANCE_ID and settings.ACE_MOBILE_S3_BUCKET
        ),
    }
    return Response(success_response(payload))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def ensure_running(request: Request) -> Response:
    try:
        _assert_configured()
    except MobileError as e:
        return _mobile_error_response(e)

    serializer = EnsureRunningSerializer(data=request.data or {})
    if not serializer.is_valid():
        return Response(
            error_response(
                message=f"invalid request: {serializer.errors}",
                code="invalid-request",
            ),
            status=400,
        )
    try:
        result = _make_controller().ensure_running(
            state_name=serializer.validated_data.get("state")
        )
    except MobileError as e:
        return _mobile_error_response(e)
    return Response(success_response(_to_payload(result)))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def diagnose(request: Request) -> Response:
    """Read-only snapshot of the in-VM emulator runtime.

    Doesn't start the EC2 instance, doesn't run recipes, doesn't
    mutate any state. Returns the same Diagnostics shape that
    ``ensure_running`` attaches to its success / failure responses,
    so callers can probe without committing to a start. Useful when
    a previous call returned booted-but-not-usable and the caller
    wants to know what's actually broken.
    """
    try:
        _assert_configured()
        diag = _make_controller().diagnose()
    except MobileError as e:
        return _mobile_error_response(e)
    return Response(success_response(_to_payload(diag)))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def states(request: Request) -> Response:
    """List the named states (one per CommCare APK version) baked into
    the AMI, plus which one is currently active on the instance."""
    try:
        _assert_configured()
        catalog = _make_controller().list_states()
    except MobileError as e:
        return _mobile_error_response(e)
    return Response(success_response(_to_payload(catalog)))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def select_state(request: Request) -> Response:
    """Switch the active state on a running instance. Stops the
    emulator and relaunches it with the requested baked snapshot."""
    try:
        _assert_configured()
    except MobileError as e:
        return _mobile_error_response(e)

    serializer = StateSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(
            error_response(
                message=f"invalid request: {serializer.errors}",
                code="invalid-request",
            ),
            status=400,
        )
    try:
        result = _make_controller().select_state(
            state_name=serializer.validated_data["state"]
        )
    except MobileError as e:
        return _mobile_error_response(e)
    return Response(success_response(_to_payload(result)))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def install_apk(request: Request) -> Response:
    try:
        _assert_configured()
    except MobileError as e:
        return _mobile_error_response(e)

    serializer = InstallApkSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(
            error_response(
                message=f"invalid request: {serializer.errors}",
                code="invalid-request",
            ),
            status=400,
        )
    try:
        result = _make_controller().install_apk(
            apk_url=serializer.validated_data["apk_url"]
        )
    except MobileError as e:
        return _mobile_error_response(e)
    return Response(success_response(_to_payload(result)))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def run_recipe(request: Request) -> Response:
    """Submit a Maestro recipe for async execution against the cloud AVD.

    Returns 202 + ``{job_id}`` immediately; the actual work runs in a
    background thread. The client polls ``GET /api/mobile/jobs/<id>``
    for completion. This pattern is necessary because AWS ALB closes
    idle connections at 60 s and typical Maestro runs take 60–300 s —
    a synchronous POST reliably died as ``fetch failed`` client-side
    AND leaked the singleton lock until its TTL expired (caught in
    vivo by the leep Phase 5 run, 2026-05-12).

    Singleton lock is held by the background thread; the request
    handler hands it off via the ``owner`` string captured in the
    closure. The thread's ``try/finally`` is the sole release path —
    a network drop between client and ALB no longer leaves the lock
    held until TTL expiry.
    """
    try:
        _assert_configured()
    except MobileError as e:
        return _mobile_error_response(e)

    serializer = RunRecipeSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(
            error_response(
                message=f"invalid request: {serializer.errors}",
                code="invalid-request",
            ),
            status=400,
        )

    owner = singleton.make_owner()
    acquired, current = singleton.try_acquire(owner)
    if not acquired:
        try:
            raise SingletonBusy(owner=current or "unknown")
        except SingletonBusy as e:
            return _mobile_error_response(e, extra={"current_owner": e.owner})

    # Capture the validated inputs into a closure for the worker.
    recipe_yaml = serializer.validated_data["recipe_yaml"]
    env = serializer.validated_data.get("env") or {}
    screenshot_prefix = serializer.validated_data.get("screenshot_prefix")
    requested_state = serializer.validated_data.get("state")

    def worker_holding(job_id: str) -> None:
        """Execute the recipe in a background thread. MUST release the
        singleton lock in the finally — that's the sole release path
        for the async-mode submission, so a network drop between
        client and ALB no longer leaks the lock until TTL expiry."""
        try:
            try:
                controller = _make_controller()
                if requested_state:
                    controller.ensure_running(state_name=requested_state)
                    # ensure_running on a cold-boot path can spend 3+ min
                    # before returning; reset the lock TTL so the recipe
                    # gets its own fresh window (same logic the prior
                    # synchronous path had).
                    singleton.refresh(owner)
                result = controller.run_recipe(
                    recipe_yaml=recipe_yaml,
                    env=env,
                    screenshot_prefix=screenshot_prefix,
                )
                jobs.mark_completed(job_id, _to_payload(result))
            except MobileError as e:
                jobs.mark_failed(
                    job_id,
                    error=e.message,
                    error_code=e.code,
                )
            except Exception as e:  # noqa: BLE001 — store unexpected exc detail
                jobs.mark_failed(
                    job_id,
                    error=f"unexpected error: {e}",
                    error_code="unexpected-error",
                    include_traceback=True,
                )
        finally:
            singleton.release(owner)

    # Pre-allocate the job_id so the worker closure can use it AND we
    # can return it in the 202 response immediately.
    job_id = jobs.make_job_id()
    job = jobs.JobRecord(
        job_id=job_id,
        operation="run_recipe",
        status="running",
        owner=owner,
        started_at=jobs._iso_now(),  # noqa: SLF001 — same module
    )
    jobs.write(job)
    threading.Thread(
        target=worker_holding,
        args=(job_id,),
        name=f"mobile-job-{job_id}",
        daemon=True,
    ).start()

    return Response(success_response({"job_id": job_id, "status": "running"}), status=202)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_job(request: Request, job_id: str) -> Response:
    """Poll the status of an async mobile job.

    ``200 {status: 'running'}`` while the worker is still executing.
    ``200 {status: 'completed', result: ...}`` on success — the result
    envelope is the same shape ``run_recipe`` used to return
    synchronously (CloudRunResult dataclass post-_to_payload).
    ``200 {status: 'failed', error, error_code}`` on failure — clients
    that previously mapped error codes to typed errors can keep doing
    so.
    ``404`` when the job_id is unknown or has expired past its 1h TTL.
    """
    try:
        _assert_configured()
    except MobileError as e:
        return _mobile_error_response(e)

    rec = jobs.read(job_id)
    if rec is None:
        return Response(
            error_response(
                message=f"job {job_id!r} not found or expired",
                code="job-not-found",
            ),
            status=404,
        )
    return Response(success_response(rec.to_dict()))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def save_snapshot(request: Request) -> Response:
    try:
        _assert_configured()
    except MobileError as e:
        return _mobile_error_response(e)

    serializer = SnapshotSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(
            error_response(
                message=f"invalid request: {serializer.errors}",
                code="invalid-request",
            ),
            status=400,
        )
    try:
        result = _make_controller().save_snapshot(
            name=serializer.validated_data["name"]
        )
    except MobileError as e:
        return _mobile_error_response(e)
    return Response(success_response(_to_payload(result)))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def load_snapshot(request: Request) -> Response:
    try:
        _assert_configured()
    except MobileError as e:
        return _mobile_error_response(e)

    serializer = SnapshotSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(
            error_response(
                message=f"invalid request: {serializer.errors}",
                code="invalid-request",
            ),
            status=400,
        )
    try:
        result = _make_controller().load_snapshot(
            name=serializer.validated_data["name"]
        )
    except MobileError as e:
        return _mobile_error_response(e)
    return Response(success_response(_to_payload(result)))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def capture_ui_dump(request: Request) -> Response:
    try:
        _assert_configured()
        xml = _make_controller().capture_ui_dump()
    except MobileError as e:
        return _mobile_error_response(e)
    return Response(success_response({"xml": xml}))


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def screenshot(request: Request) -> Response:
    """Take a screenshot of the running AVD and return a presigned URL.

    GET or POST (no body needed). The endpoint runs adb screencap on
    the instance, uploads the PNG to S3, and returns a 1-hour presigned
    URL. Useful for debugging, skill screenshots-on-demand, and the
    /tmp/get-screenshot local helper.
    """
    try:
        _assert_configured()
        artifact = _make_controller().capture_screenshot()
    except MobileError as e:
        return _mobile_error_response(e)
    return Response(success_response(_to_payload(artifact)))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def restart_runner(request: Request) -> Response:
    """Cleanly restart the ace-mobile-runner systemd unit and return
    the post-restart in-VM diagnostics.

    Public-API counterpart to the private recovery path inside
    ``ensure_running``. Use when the caller wants a fresh cold-boot
    without the state-switching side-effects of ``select_state`` and
    without the marker-stale-detection gate of ``ensure_running``.

    ``wait_for_ready=false`` returns immediately after issuing the
    restart (Diagnostics will show the partial state); the default
    polls for the fresh ready marker before returning so the response
    shape matches ``ensure_running``.
    """
    try:
        _assert_configured()
    except MobileError as e:
        return _mobile_error_response(e)

    serializer = RestartRunnerSerializer(data=request.data or {})
    if not serializer.is_valid():
        return Response(
            error_response(
                message=f"invalid request: {serializer.errors}",
                code="invalid-request",
            ),
            status=400,
        )
    try:
        diag = _make_controller().restart_runner(
            wait_for_ready=serializer.validated_data["wait_for_ready"]
        )
    except MobileError as e:
        return _mobile_error_response(e)
    return Response(success_response(_to_payload(diag)))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def admin_patch_launch_script(request: Request) -> Response:
    """Emergency hot-patch the in-VM ace-emulator-launch script.

    Use when the launch script has a bug we want to fix without a full
    AMI rebake. The same fix MUST also land in
    ``infra/mobile-ami/files/ace-emulator-launch`` in this repo so the
    next rebake picks it up — without that, the live fix evaporates on
    next AMI roll.

    Auth: ``IsAuthenticated`` + ``_can_write_global`` (staff users or
    ``@dimagi-ai.com`` automation identities). The previous
    PAT-only-gate allowed any authenticated user to swap the in-VM
    launch script body for arbitrary bash that runs as root on the
    next boot — too broad for a stolen-PAT scenario as the surface
    grows past the founding handful of operators.

    Every successful patch is written to ``MobileLaunchScriptPatch``
    (user, ts, sha256, bytes_written, restart, instance_id, ami_version)
    so a later "what changed on the AMI between bakes" investigation
    has an authoritative trail.
    """
    try:
        _assert_configured()
    except MobileError as e:
        return _mobile_error_response(e)

    if not _can_write_global(request.user):
        return Response(
            error_response(
                message=(
                    "admin/patch-launch-script requires staff or a Dimagi "
                    "automation identity; contact the mobile-runner owner"
                ),
                code="forbidden",
            ),
            status=403,
        )

    serializer = PatchLaunchScriptSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(
            error_response(
                message=f"invalid request: {serializer.errors}",
                code="invalid-request",
            ),
            status=400,
        )
    try:
        result = _make_controller().patch_launch_script(
            script_body=serializer.validated_data["script_body"],
            restart=serializer.validated_data["restart_runner"],
        )
    except MobileError as e:
        return _mobile_error_response(e)

    # Audit row written only after the controller confirms the in-VM
    # SHA matches what we sent — failed patches don't pollute the log.
    MobileLaunchScriptPatch.objects.create(
        user=request.user,
        sha256=result.get("sha256", ""),
        bytes_written=result.get("bytes_written", 0),
        restart_requested=bool(result.get("restarted_runner")),
        instance_id=settings.ACE_MOBILE_INSTANCE_ID,
        ami_version=settings.ACE_MOBILE_AMI_VERSION or "",
    )
    return Response(success_response(result))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def stop(request: Request) -> Response:
    """Stop the EC2 instance.

    By default, refuses with ``singleton-busy`` 503 if a recipe is in
    flight (someone else's ``run_recipe`` holds the lock) so a concurrent
    skill can't silently kill a legitimate run. ``{"force": true}``
    bypasses the guard and tears the instance down anyway — needed for
    aborting a hung recipe whose own lock never releases. Stop itself
    never takes the lock (so when cleared to act it always proceeds even
    if the holder's TTL is mid-expiry); SSM commands queued against a
    stopping instance fail naturally.
    """
    try:
        _assert_configured()
    except MobileError as e:
        return _mobile_error_response(e)

    serializer = StopSerializer(data=request.data or {})
    if not serializer.is_valid():
        return Response(
            error_response(
                message=f"invalid request: {serializer.errors}",
                code="invalid-request",
            ),
            status=400,
        )
    force = serializer.validated_data.get("force") or False

    if not force:
        current = singleton.current_owner()
        if current:
            try:
                raise SingletonBusy(owner=current)
            except SingletonBusy as e:
                return _mobile_error_response(e, extra={"current_owner": e.owner})

    try:
        result = _make_controller().stop()
    except MobileError as e:
        return _mobile_error_response(e)
    return Response(success_response(_to_payload(result)))
