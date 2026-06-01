"""Django Ninja v2 router for the system overview surface."""
from __future__ import annotations

from typing import Annotated

from django.conf import settings
from django.http import HttpRequest, HttpResponse
from ninja import Path, Router

from apps.api.auth import session_auth
from apps.api.errors import TYPE_FORBIDDEN, TYPE_NOT_FOUND, ProblemError
from apps.system.manifest import get_skill_products_map

from .schemas import (
    AgentDetailOut,
    AgentSummaryOut,
    CliDiagOut,
    RefreshPluginOut,
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
# POST /system/refresh-plugin
# ---------------------------------------------------------------------------


def run_plugin_refresh() -> dict:
    """Re-run ``scripts/refresh-ace-plugin.sh`` on this task; report the delta.

    Lets the ``/ace:iterate`` control pull a just-merged ACE plugin fix into the
    running task WITHOUT an image rebuild (the script shallow-clones latest main
    and swaps the plugin cache when VERSION differs; see PR #582). The labs ECS
    service runs a single task (``--desired-count 1``), so the receiving task is
    the runner and a subsequent ``GET /system/version`` poll observes
    ``version_after`` deterministically.

    The script is fail-safe (leaves the baked plugin in place on any error and
    exits 0) and honors the ``ACE_PLUGIN_AUTO_UPDATE`` kill-switch itself, so
    this never raises on a refresh miss — it reports ``refreshed=False``.

    The monkeypatch target in contract tests is this module-level function.
    """
    import subprocess

    from apps.system.version import check_version

    plugin_path = _plugin_path()
    before = check_version(plugin_path).get("plugin_version")

    script = settings.BASE_DIR / "scripts" / "refresh-ace-plugin.sh"
    if not script.is_file():
        return {
            "ran": False,
            "refreshed": False,
            "version_before": before,
            "version_after": before,
            "detail": f"refresh script not found at {script}",
        }

    try:
        proc = subprocess.run(
            ["bash", str(script)],
            capture_output=True,
            text=True,
            timeout=300,
        )
        detail = (proc.stdout or proc.stderr or "").strip()[-500:]
    except subprocess.TimeoutExpired:
        return {
            "ran": True,
            "refreshed": False,
            "version_before": before,
            "version_after": before,
            "detail": "refresh script timed out after 300s",
        }

    after = check_version(plugin_path).get("plugin_version")
    return {
        "ran": True,
        "refreshed": after is not None and after != before,
        "version_before": before,
        "version_after": after,
        "detail": detail,
    }


@router.post(
    "/refresh-plugin",
    response={200: RefreshPluginOut},
    summary="Refresh the vendored ACE plugin to latest main (no image rebuild)",
)
def refresh_plugin(request: HttpRequest) -> HttpResponse:
    from django.http import JsonResponse

    data = run_plugin_refresh()
    payload = RefreshPluginOut.model_validate(data).model_dump(mode="json")
    return JsonResponse(payload)


# ---------------------------------------------------------------------------
# GET /system/skill-products
# ---------------------------------------------------------------------------


@router.get(
    "/skill-products",
    summary="Skill -> product paths map",
    description=(
        "Returns {skill_slug: [artifact_path, ...]} derived from the ACE "
        "plugin's artifact-manifest.ts. Used by the in-app decisions editor "
        "to show which files a forked re-run will regenerate."
    ),
)
def skill_products(request: HttpRequest) -> dict[str, list[str]]:
    return get_skill_products_map()


# ---------------------------------------------------------------------------
# POST /system/cli-diag (admin only)
# ---------------------------------------------------------------------------


def _load_blob_json_for_diag(user, source: str | None) -> str | None:
    """Return the raw credential blob JSON matching ``source``.

    Used by ``run_cli_diag`` to mirror what ``cli_backend._stage_env_for``
    writes to the staged ``.credentials.json``. We need the full blob
    (not just the access token from ``get_stored_token``) so the
    subprocess can refresh its own token if it expires mid-call —
    matches what a real chat turn sees.
    """
    if source == "user":
        from apps.common.models import UserCredential

        cred = UserCredential.objects.filter(user=user).first()
        if cred and cred.blob_encrypted:
            return cred.blob_encrypted
        return None
    if source in ("global", "env", None):
        from apps.common.models import SystemConfig

        row = SystemConfig.objects.filter(key="claude_credentials_blob").first()
        if row and row.value:
            return row.value
    return None


def run_cli_diag(user, prompt: str | None = None, timeout_seconds: float = 30.0) -> dict:
    """Run cli diagnostic — requires staff or automation identity.

    Mirrors the chat path's credential staging (see
    ``apps.common.cli_backend.CLIBackend._stage_env_for``): resolve the
    caller's stored blob, write it to ``.credentials.json`` inside a
    staged HOME, and symlink every other ``.claude/`` entry so the
    plugin registry + MCP wiring loads exactly the same way ``claude -p``
    sees it in a real chat turn. Without this staging the subprocess
    runs with ``apiKeySource=none`` and the diagnostic always reports
    "tools are loaded but tool_use=0" — a false signal that masks the
    real failure mode (credentials missing from the right place).
    """
    email = (user.email or "").lower()
    if not (user.is_staff or email.endswith("@dimagi-ai.com")):
        raise ProblemError(403, "Staff or automation account only", type_=TYPE_FORBIDDEN)

    import json
    import os
    import shutil
    import subprocess
    import tempfile
    import time
    import uuid
    from pathlib import Path

    from apps.common import auth_flow

    prompt = prompt or "Use the Bash tool to run 'echo CLI-DIAG-OK' and return only the result."

    binary = shutil.which("claude") or "claude"
    args = [
        binary, "-p", "--verbose", "--output-format", "stream-json",
        "--dangerously-skip-permissions",
    ]

    env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
    env.pop("CLAUDE_CODE_OAUTH_TOKEN", None)

    # Resolve credentials the same way chat does: user blob first, then
    # global SystemConfig fallback. ``auth_flow.get_stored_token`` returns
    # ``(access_token, source) | None``; we also need the raw blob JSON to
    # write a usable ``.credentials.json`` (the access token alone isn't
    # enough — claude CLI's refresh logic reads the refresh token from the
    # same file when the access token nears expiry).
    resolved = auth_flow.get_stored_token(user=user)
    token = resolved[0] if resolved else ""
    source = resolved[1] if resolved else None
    blob_json = _load_blob_json_for_diag(user, source)

    # Stage a temp HOME so the subprocess sees a real .credentials.json
    # rather than relying solely on CLAUDE_CODE_OAUTH_TOKEN env var
    # (which claude -p does NOT use as a credential source for the
    # subscription auth flow — it reads .credentials.json from $HOME).
    staged_root = (
        Path(tempfile.gettempdir())
        / "ace-cli-diag"
        / f"{user.pk}-{uuid.uuid4().hex[:8]}"
    )
    claude_dir = staged_root / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    for path in (staged_root, claude_dir):
        try:
            path.chmod(0o700)
        except OSError:
            pass

    original_home = os.environ.get("HOME") or ""
    if original_home:
        real_claude_dir = Path(original_home) / ".claude"
        if real_claude_dir.is_dir():
            for entry in real_claude_dir.iterdir():
                if entry.name == ".credentials.json":
                    continue
                link = claude_dir / entry.name
                if link.exists() or link.is_symlink():
                    continue
                try:
                    link.symlink_to(entry)
                except OSError:
                    pass
        real_claude_json = Path(original_home) / ".claude.json"
        if real_claude_json.exists():
            link = staged_root / ".claude.json"
            if not (link.exists() or link.is_symlink()):
                try:
                    link.symlink_to(real_claude_json)
                except OSError:
                    pass

    if blob_json:
        creds_path = claude_dir / ".credentials.json"
        creds_path.write_text(blob_json)
        try:
            creds_path.chmod(0o600)
        except OSError:
            pass

    env["HOME"] = str(staged_root)
    if token:
        env["CLAUDE_CODE_OAUTH_TOKEN"] = token

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
    finally:
        shutil.rmtree(staged_root, ignore_errors=True)
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
        "credential_source": source,
        "credential_blob_staged": blob_json is not None,
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
