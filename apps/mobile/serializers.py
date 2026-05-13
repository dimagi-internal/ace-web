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
    # Allow only S3-key-safe characters: alphanumeric, underscore, dot,
    # dash, and forward slash (for nested prefixes like ``opp/run-1``).
    # The strict allowlist is load-bearing — this string ends up in the
    # ``aws s3 cp`` shell command that the controller dispatches to SSM
    # (controller.run_recipe), so any shell metacharacter (``;``, ``$``,
    # backtick, ``|``, ``&``, whitespace, quotes, …) is a command-
    # injection vector against the EC2 instance as root. The controller
    # also ``shlex.quote``-s the S3 URL as a belt-and-suspenders layer.
    screenshot_prefix = serializers.RegexField(
        regex=r"^[A-Za-z0-9_./-]{1,128}$",
        required=False,
        allow_null=True,
        default=None,
        error_messages={
            "invalid": "screenshot_prefix must match [A-Za-z0-9_./-]{1,128}",
        },
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
        # Layered on top of the regex: also block ``..`` traversal and
        # leading ``/`` (which would land the prefix outside the
        # ``screenshots/`` namespace in S3 after the controller's
        # ``strip("/")``).
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


class StopSerializer(serializers.Serializer):
    """``stop`` accepts an optional ``force`` flag.

    Without ``force`` (the default), stop refuses with ``singleton-busy``
    503 if the singleton lock is held — a recipe is in flight and the
    caller probably didn't mean to interrupt it. ``{"force": true}``
    bypasses the guard so a hung recipe can still be aborted by tearing
    the instance down."""

    force = serializers.BooleanField(required=False, default=False)


# Maximum bytes the launch-script body may have. Current script is
# ~7KB; the cap is for comments / pm-wait additions, not wholesale
# rewrites — rebake the AMI for those. Lives here so a bad body
# returns 400 invalid-request from the serializer, not a 500
# mobile-error from the controller.
_LAUNCH_SCRIPT_MAX_BYTES = 64 * 1024


class PatchLaunchScriptSerializer(serializers.Serializer):
    """Emergency-fix endpoint for hot-patching the in-VM
    ace-emulator-launch script without a full AMI rebake. The script
    body is validated here (shebang + size cap) so a malformed body
    returns 400 invalid-request, not a 500 mobile-error from the
    controller. ``restart_runner`` defaults true so a typical fix
    lands and is exercised on the next boot."""

    script_body = serializers.CharField(allow_blank=False, trim_whitespace=False)
    restart_runner = serializers.BooleanField(required=False, default=True)

    def validate_script_body(self, value: str) -> str:
        if not value.startswith("#!/bin/bash"):
            raise serializers.ValidationError(
                "launch script must start with '#!/bin/bash' shebang "
                f"(got: {value[:32]!r})"
            )
        if len(value.encode("utf-8")) > _LAUNCH_SCRIPT_MAX_BYTES:
            raise serializers.ValidationError(
                f"launch script body exceeds {_LAUNCH_SCRIPT_MAX_BYTES}-byte cap; "
                "this endpoint is for surgical fixes, not wholesale rewrites — "
                "rebake the AMI"
            )
        return value
