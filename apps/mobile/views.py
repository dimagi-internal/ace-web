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
from .exceptions import MobileError, NotConfigured, SingletonBusy
from .serializers import (
    EnsureRunningSerializer,
    InstallApkSerializer,
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


def _strip_trailing_underscore_keys(obj: Any) -> Any:
    """Recursively rename ``k_`` → ``k`` in dict keys.

    Used so dataclass fields that follow the Python kwarg convention
    (``class_`` etc.) serialize as their natural JSON key. Doesn't touch
    dunder names.
    """
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            key = k[:-1] if isinstance(k, str) and k.endswith("_") and not k.endswith("__") else k
            out[key] = _strip_trailing_underscore_keys(v)
        return out
    if isinstance(obj, list):
        return [_strip_trailing_underscore_keys(x) for x in obj]
    return obj


def _to_payload(obj: Any) -> Any:
    """Normalize a controller result for the JSON envelope.

    Dataclass → dict; list of dataclasses → list of dicts; primitives pass.

    Trailing-underscore field names are stripped (``class_`` → ``class``)
    after ``asdict`` walks the tree.
    """
    if is_dataclass(obj):
        return _strip_trailing_underscore_keys(asdict(obj))
    if isinstance(obj, list):
        return [_to_payload(x) for x in obj]
    return obj


def _mobile_error_response(e: MobileError, extra: dict[str, Any] | None = None) -> Response:
    body = error_response(message=e.message, code=e.code)
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
        result = _make_controller().capture_ui_dump()
    except MobileError as e:
        return _mobile_error_response(e)
    return Response(success_response(_to_payload(result)))


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
def stop(request: Request) -> Response:
    """Stop the EC2 instance.

    By default, refuses if a recipe is in flight (singleton lock held)
    so an accidental stop call from a concurrent skill can't silently
    kill a legitimate run. Pass ``{"force": true}`` to bypass the guard
    and tear the instance down anyway — needed for aborting a hung
    recipe whose own lock never releases. The stop itself never takes
    the lock (so it can always proceed once cleared to act); SSM
    commands queued against a stopping instance fail naturally.
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
