"""SSM transport for the mobile runner -- now a thin shim over the shared SDK.

The implementation lives in ``canopy_sdk.ondemand.ssm`` (extracted from this
module). What stays here is the exception translation: the SDK raises its own
``SSMFailure`` / ``SSMTimeout``, but everything in ``apps/mobile`` (controller,
API envelope) speaks ``MobileError`` subclasses that carry ``code`` and
``http_status``. ``run_command`` keeps its old signature and raises those.
"""
from __future__ import annotations

from typing import Any

from canopy_sdk.ondemand import errors as _sdk_errors
from canopy_sdk.ondemand import ssm as _sdk_ssm
from canopy_sdk.ondemand.ssm import CommandResult

from .exceptions import SSMFailure, SSMTimeout

__all__ = ["CommandResult", "run_command"]


def run_command(
    ssm_client: Any,
    instance_id: str,
    *,
    commands: list[str],
    timeout_seconds: int,
    poll_interval: float = 1.0,
    return_on_script_failure: bool = False,
) -> CommandResult:
    """Send a shell command to ``instance_id`` and wait for completion.

    Raises ``apps.mobile.exceptions.SSMTimeout`` / ``SSMFailure`` (the SDK's
    errors, translated).
    """
    try:
        return _sdk_ssm.run_command(
            ssm_client,
            instance_id,
            commands=commands,
            timeout_seconds=timeout_seconds,
            poll_interval=poll_interval,
            return_on_script_failure=return_on_script_failure,
        )
    except _sdk_errors.SSMTimeout as e:
        raise SSMTimeout(str(e)) from e
    except _sdk_errors.SSMFailure as e:
        raise SSMFailure(str(e)) from e
