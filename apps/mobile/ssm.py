"""Thin boto3 wrapper around AWS SSM ``send_command`` + poll.

Why SSM and not SSH: the spec explicitly chose SSM Session Manager so
ace-web's ECS task can drive the EC2 instance over the AWS control plane
without inbound SG rules or key management. The instance role just needs
``AmazonSSMManagedInstanceCore``.

Module is sync. Polling is a tight 1 s loop — SSM commands return in
hundreds of ms typically, but ``maestro test`` runs may take tens of
seconds; the 1 s cadence keeps idle wait short while not hammering SSM.

One retry on ``ThrottlingException`` because SSM's TPS can dip; otherwise
errors surface to the caller as ``SSMFailure``.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from botocore.exceptions import ClientError

from .exceptions import SSMFailure, SSMTimeout

# SSM command status set per
# https://docs.aws.amazon.com/systems-manager/latest/APIReference/API_GetCommandInvocation.html
_TERMINAL_STATUSES = {"Success", "Cancelled", "TimedOut", "Failed"}
_FAILURE_STATUSES = {"Cancelled", "TimedOut", "Failed"}


@dataclass
class CommandResult:
    """Result of a single SSM ``AWS-RunShellScript`` invocation."""

    status: str
    exit_code: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.status == "Success" and self.exit_code == 0


def run_command(
    ssm_client: Any,
    instance_id: str,
    *,
    commands: list[str],
    timeout_seconds: int,
    poll_interval: float = 1.0,
) -> CommandResult:
    """Send a shell command to ``instance_id`` and wait for completion.

    Args:
        ssm_client: a boto3 SSM client (``boto3.client("ssm")``). Passed
            in so callers can inject a stubbed client in tests.
        instance_id: target EC2 instance.
        commands: list of shell command strings; concatenated into a
            single ``AWS-RunShellScript`` invocation.
        timeout_seconds: outer wall-clock timeout. Includes both the SSM
            send-command + the in-VM execution. Beyond this we raise
            ``SSMTimeout`` even if SSM is still polling.
        poll_interval: seconds between ``get_command_invocation`` polls.

    Raises:
        SSMTimeout: if ``timeout_seconds`` elapses before terminal status.
        SSMFailure: on non-throttling boto errors, or on terminal
            failure statuses (``Cancelled``, ``TimedOut``, ``Failed``).
    """
    command_id = _send_with_retry(
        ssm_client, instance_id, commands, timeout_seconds
    )

    deadline = time.monotonic() + timeout_seconds
    last_response: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        try:
            resp = ssm_client.get_command_invocation(
                CommandId=command_id, InstanceId=instance_id
            )
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if code in ("InvocationDoesNotExist", "InvalidCommandId"):
                # SSM hasn't materialized the invocation yet; keep polling.
                time.sleep(poll_interval)
                continue
            raise SSMFailure(f"SSM get_command_invocation failed: {e}") from e

        last_response = resp
        status = resp.get("Status", "Pending")
        if status in _TERMINAL_STATUSES:
            return _build_result(resp)
        time.sleep(poll_interval)

    raise SSMTimeout(
        f"SSM command {command_id} on {instance_id} did not finish in "
        f"{timeout_seconds}s; last status: "
        f"{(last_response or {}).get('Status', 'unknown')}"
    )


def _send_with_retry(
    ssm_client: Any,
    instance_id: str,
    commands: list[str],
    timeout_seconds: int,
) -> str:
    """Call ``send_command`` with one retry on throttling."""
    attempts = 0
    while True:
        attempts += 1
        try:
            resp = ssm_client.send_command(
                InstanceIds=[instance_id],
                DocumentName="AWS-RunShellScript",
                Parameters={"commands": commands},
                TimeoutSeconds=max(30, min(timeout_seconds, 2592000)),
            )
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if code == "ThrottlingException" and attempts == 1:
                time.sleep(2.0)
                continue
            raise SSMFailure(f"SSM send_command failed: {e}") from e

        command = resp.get("Command") or {}
        command_id = command.get("CommandId")
        if not command_id:
            raise SSMFailure(
                f"SSM send_command returned no CommandId: {resp!r}"
            )
        return command_id


def _build_result(resp: dict[str, Any]) -> CommandResult:
    status = resp.get("Status", "Failed")
    raw_code = resp.get("ResponseCode")
    exit_code = int(raw_code if raw_code is not None else 1)
    stdout = resp.get("StandardOutputContent", "") or ""
    stderr = resp.get("StandardErrorContent", "") or ""

    if status in _FAILURE_STATUSES:
        # Terminal failure — surface as SSMFailure so the view returns 502.
        # We still package the streams in the exception message so callers
        # can see what the in-VM command spat out before bailing.
        raise SSMFailure(
            f"SSM command terminated with status={status} exit_code={exit_code}; "
            f"stderr={stderr[:500]!r}"
        )

    return CommandResult(
        status=status,
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
    )
