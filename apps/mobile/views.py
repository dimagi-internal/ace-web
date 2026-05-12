"""HTTP API for the cloud Android emulator runner.

All endpoints share the project's ``{data, error}`` envelope and authenticate
via the global Bearer-token backend (``apps.auth.token_backend.BearerTokenAuthentication``),
which is already wired into ``REST_FRAMEWORK.DEFAULT_AUTHENTICATION_CLASSES``.

The controller class (``apps.mobile.controller.EmulatorController``) does
the work; views are thin: assert configured → validate input → (for
``run_recipe`` only) acquire singleton lock → dispatch → envelope.

The singleton lock only wraps ``run_recipe``. Other endpoints are short
enough not to need it; ``stop`` deliberately does NOT take the lock so a
hung ``run_recipe`` can always be aborted by stopping the instance.
"""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from django.conf import settings
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.common.envelope import error_response, success_response

from . import singleton
from .controller import EmulatorController
from .exceptions import EmulatorNotReady, MobileError, NotConfigured, SingletonBusy
from .serializers import (
    EnsureRunningSerializer,
    InstallApkSerializer,
    PatchLaunchScriptSerializer,
    RunRecipeSerializer,
    SnapshotSerializer,
    StateSerializer,
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

    try:
        try:
            controller = _make_controller()
            requested_state = serializer.validated_data.get("state")
            if requested_state:
                # Switch state if needed — no-op if already active.
                controller.ensure_running(state_name=requested_state)
            result = controller.run_recipe(
                recipe_yaml=serializer.validated_data["recipe_yaml"],
                env=serializer.validated_data.get("env") or {},
                screenshot_prefix=serializer.validated_data.get("screenshot_prefix"),
            )
        except MobileError as e:
            return _mobile_error_response(e)
    finally:
        singleton.release(owner)

    return Response(success_response(_to_payload(result)))


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
def admin_patch_launch_script(request: Request) -> Response:
    """Emergency hot-patch the in-VM ace-emulator-launch script.

    Use when the launch script has a bug we want to fix without a full
    AMI rebake. The same fix MUST also land in
    ``infra/mobile-ami/files/ace-emulator-launch`` in this repo so the
    next rebake picks it up — without that, the live fix evaporates on
    next AMI roll.

    Auth: regular IsAuthenticated (PAT or session). This is a
    privileged operation but the PAT permission model is the same as
    every other mobile endpoint, so no extra gating beyond that.
    """
    try:
        _assert_configured()
    except MobileError as e:
        return _mobile_error_response(e)

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
    return Response(success_response(result))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def stop(request: Request) -> Response:
    """Stop the EC2 instance.

    Deliberately does NOT take the singleton lock — ``stop`` must always
    succeed even mid-run so a hung recipe can be aborted by tearing the
    instance down. SSM commands queued against a stopping instance will
    fail naturally.
    """
    try:
        _assert_configured()
        result = _make_controller().stop()
    except MobileError as e:
        return _mobile_error_response(e)
    return Response(success_response(_to_payload(result)))
