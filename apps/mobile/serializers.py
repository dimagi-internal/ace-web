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
