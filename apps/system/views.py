"""REST API views for the ACE System Overview."""
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

from django.conf import settings
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.common.envelope import error_response, success_response
from apps.system.reader import load_agent_detail, load_skill_detail, load_system_overview
from apps.system.version import check_version


def _plugin_path() -> str:
    return getattr(settings, "ACE_PLUGIN_PATH", "")


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def overview(request):
    """Return the full system snapshot: skills, agents, artifacts, version."""
    path = _plugin_path()
    data = load_system_overview(path)
    version = check_version(path)
    data["plugin_version"] = version["plugin_version"]
    data["remote_version"] = version["remote_version"]
    data["update_available"] = version["update_available"]
    return Response(success_response(data))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def skill_detail(request, name: str):
    """Return a single skill with full markdown body."""
    detail = load_skill_detail(_plugin_path(), name)
    if detail is None:
        return Response(
            error_response(f"skill {name!r} not found", code="skill-not-found"),
            status=404,
        )
    return Response(success_response(detail))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def agent_detail(request, name: str):
    """Return a single agent with full markdown body."""
    detail = load_agent_detail(_plugin_path(), name)
    if detail is None:
        return Response(
            error_response(f"agent {name!r} not found", code="agent-not-found"),
            status=404,
        )
    return Response(success_response(detail))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def version(request):
    """Lightweight version-only check."""
    data = check_version(_plugin_path())
    return Response(success_response(data))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def cli_diag(request):
    """Diagnostic — spawn `claude -p` with the same args/env that
    apps.common.cli_backend would, and return the first N stream-json
    events as JSON. Lets us see in-container whether tools, plugins, and
    the system init payload are being delivered correctly without needing
    CloudWatch.

    Restricted to staff + the ace@dimagi-ai.com automation domain.
    Body: ``{"prompt": "..."}`` (default: short bash-test).
    """
    user = request.user
    email = (user.email or "").lower()
    if not (user.is_staff or email.endswith("@dimagi-ai.com")):
        return Response(
            error_response("staff or automation account only", code="forbidden"),
            status=403,
        )

    payload = request.data if isinstance(request.data, dict) else {}
    prompt = payload.get(
        "prompt",
        "Use the Bash tool to run 'echo CLI-DIAG-OK' and return only the result.",
    )
    timeout_seconds = float(payload.get("timeout_seconds", 30))

    binary = shutil.which("claude") or "claude"
    args = [
        binary, "-p", "--verbose", "--output-format", "stream-json",
        "--dangerously-skip-permissions",
    ]

    # Build env with the SAME logic cli_backend uses, plus pull the global
    # blob from SystemConfig and set CLAUDE_CODE_OAUTH_TOKEN so claude doesn't
    # bail with "Not logged in".
    env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
    env.pop("CLAUDE_CODE_OAUTH_TOKEN", None)

    from apps.common.models import SystemConfig
    global_row = SystemConfig.objects.filter(key="claude_credentials_blob").first()
    if global_row:
        try:
            blob = json.loads(global_row.value)
            access = (blob.get("claudeAiOauth") or {}).get("accessToken") or ""
            if access:
                env["CLAUDE_CODE_OAUTH_TOKEN"] = access
        except Exception:
            pass

    home = env.get("HOME", "")
    real_claude_dir = Path(home) / ".claude" if home else None
    real_claude_listing = (
        sorted(p.name for p in real_claude_dir.iterdir())
        if real_claude_dir and real_claude_dir.is_dir()
        else None
    )
    installed_plugins_text = ""
    if real_claude_dir and real_claude_dir.is_dir():
        ip = real_claude_dir / "plugins" / "installed_plugins.json"
        if ip.is_file():
            try:
                installed_plugins_text = ip.read_text()[:2000]
            except Exception:
                installed_plugins_text = "(unreadable)"

    started = time.monotonic()
    try:
        proc = subprocess.Popen(  # noqa: S603 - controlled args
            args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            text=True,
        )
        stdout_text, stderr_text = proc.communicate(
            input=prompt, timeout=timeout_seconds
        )
        rc = proc.returncode
    except subprocess.TimeoutExpired:
        proc.kill()
        stdout_text, stderr_text = proc.communicate()
        rc = -1
    elapsed = time.monotonic() - started

    # Parse the stream-json lines we did get. Don't care about completeness —
    # the goal is to surface the init event for diagnosis.
    raw_events: list[dict] = []
    for line in stdout_text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            raw_events.append(json.loads(line))
        except Exception:
            raw_events.append({"_unparseable": line[:300]})

    init = next(
        (e for e in raw_events if e.get("type") == "system" and e.get("subtype") == "init"),
        None,
    )
    init_summary = None
    if init:
        init_summary = {
            "tools": init.get("tools", [])[:30],
            "permissionMode": init.get("permissionMode"),
            "apiKeySource": init.get("apiKeySource"),
            "model": init.get("model"),
            "claude_code_version": init.get("claude_code_version"),
            "mcp_servers": init.get("mcp_servers"),
            "plugins": [p.get("name") for p in init.get("plugins", [])],
            "session_id": init.get("session_id"),
        }

    tool_uses = [
        block
        for ev in raw_events
        if ev.get("type") == "assistant"
        for block in ev.get("message", {}).get("content", [])
        if block.get("type") == "tool_use"
    ]

    return Response(
        success_response({
            "elapsed_seconds": round(elapsed, 2),
            "returncode": rc,
            "spawn_args": args,
            "env": {
                "HOME": home,
                "real_home_claude_listing": real_claude_listing,
                "CLAUDE_CODE_OAUTH_TOKEN_set": bool(env.get("CLAUDE_CODE_OAUTH_TOKEN")),
                "CLAUDE_CODE_OAUTH_TOKEN_prefix": (
                    env.get("CLAUDE_CODE_OAUTH_TOKEN", "")[:18] or None
                ),
                "installed_plugins_json": installed_plugins_text,
            },
            "stderr_tail": stderr_text[-2000:] if stderr_text else "",
            "stream_event_count": len(raw_events),
            "init_summary": init_summary,
            "tool_uses": [
                {"name": b.get("name"), "input": b.get("input")}
                for b in tool_uses
            ],
            "first_3_assistant_text_blocks": [
                block.get("text", "")[:200]
                for ev in raw_events
                if ev.get("type") == "assistant"
                for block in ev.get("message", {}).get("content", [])
                if block.get("type") == "text"
            ][:3],
        })
    )
