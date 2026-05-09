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
    InstallApkSerializer,
    RunRecipeSerializer,
    SnapshotSerializer,
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
        result = _make_controller().ensure_running()
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
            result = _make_controller().run_recipe(
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
