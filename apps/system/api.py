"""Django Ninja v2 router for the system overview surface."""
from __future__ import annotations

from typing import Annotated

from django.conf import settings
from django.http import HttpRequest, HttpResponse
from ninja import Path, Router

from apps.api.auth import session_auth
from apps.api.errors import TYPE_FORBIDDEN, TYPE_NOT_FOUND, ProblemError

from .schemas import (
    AgentDetailOut,
    AgentSummaryOut,
    CliDiagOut,
    SkillDetailOut,
    SkillSummaryOut,
    SystemOverviewOut,
    VersionOut,
)

router = Router(auth=session_auth, tags=["system"])


def _plugin_path() -> str:
    return getattr(settings, "ACE_PLUGIN_PATH", "")


# ---------------------------------------------------------------------------
# GET /system/overview
# ---------------------------------------------------------------------------


def get_system_overview() -> dict:
    from apps.system.reader import load_system_overview
    from apps.system.version import check_version

    path = _plugin_path()
    data = load_system_overview(path)
    version = check_version(path)
    data["plugin_version"] = version["plugin_version"]
    data["remote_version"] = version["remote_version"]
    data["update_available"] = version["update_available"]
    return data


@router.get(
    "/overview",
    response={200: SystemOverviewOut},
    summary="Full system overview",
)
def overview(request: HttpRequest) -> HttpResponse:
    from django.http import JsonResponse

    data = get_system_overview()
    payload = SystemOverviewOut.model_validate(data).model_dump(mode="json")
    return JsonResponse(payload)


# ---------------------------------------------------------------------------
# GET /system/skills
# ---------------------------------------------------------------------------


def get_skills_list() -> list[dict]:
    from apps.system.reader import load_system_overview

    data = load_system_overview(_plugin_path())
    return data.get("skills", [])


@router.get(
    "/skills",
    response={200: list[SkillSummaryOut]},
    summary="List skills",
)
def list_skills(request: HttpRequest) -> HttpResponse:
    from django.http import JsonResponse

    skills = get_skills_list()
    payload = [SkillSummaryOut.model_validate(s).model_dump(mode="json") for s in skills]
    return JsonResponse(payload, safe=False)


# ---------------------------------------------------------------------------
# GET /system/skills/{name}
# ---------------------------------------------------------------------------


def get_skill_detail(name: str) -> dict | None:
    from apps.system.reader import load_skill_detail

    return load_skill_detail(_plugin_path(), name)


@router.get(
    "/skills/{name}",
    response={200: SkillDetailOut},
    summary="Skill detail",
)
def skill_detail(
    request: HttpRequest,
    name: Annotated[str, Path()],
) -> HttpResponse:
    from django.http import JsonResponse

    detail = get_skill_detail(name)
    if detail is None:
        raise ProblemError(404, f"Skill {name!r} not found", type_=TYPE_NOT_FOUND)
    payload = SkillDetailOut.model_validate(detail).model_dump(mode="json")
    return JsonResponse(payload)


# ---------------------------------------------------------------------------
# GET /system/agents
# ---------------------------------------------------------------------------


def get_agents_list() -> list[dict]:
    from apps.system.reader import load_system_overview

    data = load_system_overview(_plugin_path())
    return data.get("agents", [])


@router.get(
    "/agents",
    response={200: list[AgentSummaryOut]},
    summary="List agents",
)
def list_agents(request: HttpRequest) -> HttpResponse:
    from django.http import JsonResponse

    agents = get_agents_list()
    payload = [AgentSummaryOut.model_validate(a).model_dump(mode="json") for a in agents]
    return JsonResponse(payload, safe=False)


# ---------------------------------------------------------------------------
# GET /system/agents/{name}
# ---------------------------------------------------------------------------


def get_agent_detail(name: str) -> dict | None:
    from apps.system.reader import load_agent_detail

    return load_agent_detail(_plugin_path(), name)


@router.get(
    "/agents/{name}",
    response={200: AgentDetailOut},
    summary="Agent detail",
)
def agent_detail(
    request: HttpRequest,
    name: Annotated[str, Path()],
) -> HttpResponse:
    from django.http import JsonResponse

    detail = get_agent_detail(name)
    if detail is None:
        raise ProblemError(404, f"Agent {name!r} not found", type_=TYPE_NOT_FOUND)
    payload = AgentDetailOut.model_validate(detail).model_dump(mode="json")
    return JsonResponse(payload)


# ---------------------------------------------------------------------------
# GET /system/version
# ---------------------------------------------------------------------------


def get_version_info() -> dict:
    from apps.system.version import check_version

    return check_version(_plugin_path())


@router.get(
    "/version",
    response={200: VersionOut},
    summary="Plugin version check",
)
def version(request: HttpRequest) -> HttpResponse:
    from django.http import JsonResponse

    data = get_version_info()
    payload = VersionOut.model_validate(data).model_dump(mode="json")
    return JsonResponse(payload)


# ---------------------------------------------------------------------------
# POST /system/cli-diag (admin only)
# ---------------------------------------------------------------------------


def run_cli_diag(user, prompt: str | None = None, timeout_seconds: float = 30.0) -> dict:
    """Run cli diagnostic — requires staff or automation identity."""
    email = (user.email or "").lower()
    if not (user.is_staff or email.endswith("@dimagi-ai.com")):
        raise ProblemError(403, "Staff or automation account only", type_=TYPE_FORBIDDEN)

    import json
    import os
    import shutil
    import subprocess
    import time

    prompt = prompt or "Use the Bash tool to run 'echo CLI-DIAG-OK' and return only the result."

    binary = shutil.which("claude") or "claude"
    args = [
        binary, "-p", "--verbose", "--output-format", "stream-json",
        "--dangerously-skip-permissions",
    ]

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
        except Exception:  # noqa: BLE001
            pass

    started = time.monotonic()
    try:
        proc = subprocess.Popen(  # noqa: S603
            args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            text=True,
        )
        stdout_text, stderr_text = proc.communicate(input=prompt, timeout=timeout_seconds)
        rc = proc.returncode
    except subprocess.TimeoutExpired:
        proc.kill()
        stdout_text, stderr_text = proc.communicate()
        rc = -1
    elapsed = time.monotonic() - started

    raw_events: list[dict] = []
    for line in stdout_text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            raw_events.append(json.loads(line))
        except Exception:  # noqa: BLE001
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

    return {
        "elapsed_seconds": round(elapsed, 2),
        "returncode": rc,
        "spawn_args": args,
        "stderr_tail": stderr_text[-2000:] if stderr_text else "",
        "stream_event_count": len(raw_events),
        "init_summary": init_summary,
        "tool_uses": [{"name": b.get("name"), "input": b.get("input")} for b in tool_uses],
    }


@router.post(
    "/cli-diag",
    response={200: CliDiagOut},
    summary="CLI diagnostic (admin)",
)
def cli_diag(
    request: HttpRequest,
    prompt: str | None = None,
    timeout_seconds: float = 30.0,
) -> HttpResponse:
    from django.http import JsonResponse

    result = run_cli_diag(request.user, prompt=prompt, timeout_seconds=timeout_seconds)
    payload = CliDiagOut.model_validate(result).model_dump(mode="json")
    return JsonResponse(payload)
