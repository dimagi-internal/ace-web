"""DRF serializers for the mobile-runner endpoints.

Validation only — the controller does the work. We keep these tiny so the
view layer is just envelope + auth + lock + dispatch.
"""
from __future__ import annotations

from rest_framework import serializers


class InstallApkSerializer(serializers.Serializer):
    apk_url = serializers.URLField()


class RunRecipeSerializer(serializers.Serializer):
    recipe_yaml = serializers.CharField(allow_blank=False, trim_whitespace=False)
    env = serializers.DictField(
        child=serializers.CharField(allow_blank=True),
        required=False,
        default=dict,
    )
    screenshot_prefix = serializers.CharField(
        required=False, allow_blank=False, allow_null=True, default=None
    )
    state = serializers.RegexField(
        regex=r"^[A-Za-z0-9_.-]{1,64}$",
        required=False,
        allow_null=True,
        default=None,
        error_messages={
            "invalid": "state must match [A-Za-z0-9_.-]{1,64}",
        },
    )

    def validate_screenshot_prefix(self, value: str | None) -> str | None:
        if value is None:
            return None
        # Block path traversal / absolute paths — this string ends up as
        # an S3 key prefix so we want it tame.
        if value.startswith("/") or ".." in value:
            raise serializers.ValidationError(
                "screenshot_prefix must be a plain key segment"
            )
        return value


class SnapshotSerializer(serializers.Serializer):
    name = serializers.RegexField(
        regex=r"^[A-Za-z0-9_.-]{1,64}$",
        error_messages={
            "invalid": "name must match [A-Za-z0-9_.-]{1,64}",
        },
    )


class StateSerializer(serializers.Serializer):
    """Used by ``/api/mobile/select-state`` and as an optional
    ``state`` field on ``/api/mobile/ensure-running``."""

    state = serializers.RegexField(
        regex=r"^[A-Za-z0-9_.-]{1,64}$",
        error_messages={
            "invalid": "state must match [A-Za-z0-9_.-]{1,64}",
        },
    )


class EnsureRunningSerializer(serializers.Serializer):
    """``ensure-running`` accepts an optional state name."""

    state = serializers.RegexField(
        regex=r"^[A-Za-z0-9_.-]{1,64}$",
        required=False,
        allow_null=True,
        default=None,
        error_messages={
            "invalid": "state must match [A-Za-z0-9_.-]{1,64}",
        },
    )


class RestartRunnerSerializer(serializers.Serializer):
    """``restart-runner`` accepts a single ``wait_for_ready`` flag.

    Default ``true`` because the typical operator wants to know
    whether the cold-boot succeeded before returning. ``false`` is
    fire-and-forget — partial Diagnostics returned immediately."""

    wait_for_ready = serializers.BooleanField(required=False, default=True)


class PatchLaunchScriptSerializer(serializers.Serializer):
    """Emergency-fix endpoint for hot-patching the in-VM
    ace-emulator-launch script without a full AMI rebake. The script
    body is sent verbatim — server-side validation enforces shebang +
    size cap (the controller). ``restart_runner`` defaults true so a
    typical fix lands and is exercised on the next boot."""

    script_body = serializers.CharField(allow_blank=False, trim_whitespace=False)
    restart_runner = serializers.BooleanField(required=False, default=True)
