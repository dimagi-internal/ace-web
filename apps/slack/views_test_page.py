"""Slack test page — server-rendered Block Kit preview + live post.

Accessible at /api/slack/test/. Requires authentication (e2e-login or
session). Not linked from the main nav — accessed from workspace
settings or by direct URL.

Views:
  GET  /api/slack/test/                    — list opps, pick one to preview
  GET  /api/slack/test/preview/<slug>/     — render Block Kit for an opp
  POST /api/slack/test/post/<slug>/        — post to a real Slack channel
  POST /api/slack/test/cleanup/            — delete bot messages from a channel
"""
from __future__ import annotations

import json
import logging

from django.http import HttpRequest, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from apps.opps.api import load_rich_opp_snapshot

logger = logging.getLogger(__name__)


def _normalize_snapshot(snapshot: dict) -> dict:
    """Hoist nested fields to top level for Block Kit renderers.

    The rich snapshot nests opp metadata under 'opp' and run data under
    'current_run'. The Block Kit renderers (blocks.py) expect
    'display_name' and 'current_run' at the top level. This bridges
    the two shapes.
    """
    opp = snapshot.get("opp") or {}
    if "display_name" not in snapshot and "display_name" in opp:
        snapshot["display_name"] = opp["display_name"]
    if "display_name" not in snapshot:
        snapshot["display_name"] = snapshot.get("slug", "?")
    return snapshot

_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica,
       Arial, sans-serif; background: #1a1d21; color: #d1d2d3;
       padding: 20px; max-width: 800px; margin: 0 auto; }
a { color: #4a9eff; text-decoration: none; }
a:hover { text-decoration: underline; }
h1 { color: #e8e8e8; font-size: 22px; margin-bottom: 16px; }
h2 { color: #e8e8e8; font-size: 16px; margin: 24px 0 8px; }
.nav { margin-bottom: 24px; font-size: 13px; color: #9ea0a5; }
.opp-list { list-style: none; }
.opp-list li { padding: 8px 12px; border-bottom: 1px solid #393b3f; }
.opp-list li:hover { background: #222529; }
.message { background: #222529; border-radius: 8px; padding: 12px 16px;
           margin: 8px 0; border-left: 3px solid #4a9eff; }
.message.thread { margin-left: 32px; border-left-color: #36c5f0; }
.label { background: #36373a; color: #9ea0a5; font-size: 11px;
         padding: 2px 8px; border-radius: 10px; display: inline-block;
         margin-bottom: 6px; }
.block-context { font-size: 12px; color: #9ea0a5; padding: 3px 0; }
.block-section { font-size: 14px; line-height: 1.5; padding: 4px 0; }
.block-section b, .block-section strong { color: #e8e8e8; }
.block-actions { display: flex; gap: 6px; flex-wrap: wrap; padding: 6px 0; }
.btn { display: inline-block; padding: 5px 12px; border-radius: 4px;
       font-size: 13px; font-weight: 600; border: 1px solid #4a4b4e;
       background: #2c2d30; color: #d1d2d3; cursor: pointer; }
.btn-primary { background: #007a5a; border-color: #007a5a; color: white; }
.btn-danger { background: #e01e5a; border-color: #e01e5a; color: white; }
.block-divider { border-top: 1px solid #393b3f; margin: 12px 0; }
.block-header { font-size: 15px; font-weight: 700; color: #e8e8e8;
                padding: 6px 0; }
code, .code { background: #2c2d30; padding: 1px 5px; border-radius: 3px;
              font-family: monospace; font-size: 13px; color: #e8e8e8; }
.json-dump { background: #2c2d30; padding: 12px; border-radius: 6px;
             font-family: monospace; font-size: 12px; white-space: pre-wrap;
             word-break: break-all; max-height: 300px; overflow-y: auto;
             margin: 8px 0; color: #9ea0a5; }
.post-form { margin: 16px 0; padding: 16px; background: #222529;
             border-radius: 8px; }
.post-form label { display: block; font-size: 13px; color: #9ea0a5;
                   margin-bottom: 4px; }
.post-form input[type=text] { width: 300px; padding: 6px 10px;
             background: #2c2d30; border: 1px solid #4a4b4e;
             border-radius: 4px; color: #d1d2d3; font-size: 14px; }
.post-form button { margin-top: 8px; }
.result { margin: 12px 0; padding: 12px; border-radius: 6px; font-size: 13px; }
.result-ok { background: #1a3a2a; border: 1px solid #007a5a; }
.result-err { background: #3a1a1a; border: 1px solid #e01e5a; }
.tab-bar { display: flex; gap: 0; margin-bottom: 16px; }
.tab { padding: 8px 16px; font-size: 13px; cursor: pointer;
       border: 1px solid #4a4b4e; background: #2c2d30; color: #9ea0a5; }
.tab:first-child { border-radius: 4px 0 0 4px; }
.tab:last-child { border-radius: 0 4px 4px 0; }
.tab.active { background: #4a9eff; color: white; border-color: #4a9eff; }
"""


def _require_auth(view_fn):
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return HttpResponse("Login required", status=401)
        return view_fn(request, *args, **kwargs)
    return wrapper


def _render_mrkdwn(text: str) -> str:
    """Minimal Slack mrkdwn → HTML. Handles *bold*, `code`, <@U..>, <URL|text>."""
    import re
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    # Restore Slack link syntax that we just escaped
    text = re.sub(r'&lt;(@\w+)&gt;', r'<strong>\1</strong>', text)
    text = re.sub(r'&lt;(https?://[^|]+)\|([^&]+)&gt;', r'<a href="\1">\2</a>', text)
    text = re.sub(r'&lt;(https?://[^&]+)&gt;', r'<a href="\1">\1</a>', text)
    text = re.sub(r'\*([^*]+)\*', r'<strong>\1</strong>', text)
    text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)
    text = re.sub(r'_([^_]+)_', r'<em>\1</em>', text)
    text = text.replace('\n', '<br>')
    return text


def _render_block(block: dict) -> str:
    """Render one Block Kit block as HTML."""
    btype = block.get("type", "")
    if btype == "section":
        txt = block.get("text", {}).get("text", "")
        return f'<div class="block-section">{_render_mrkdwn(txt)}</div>'
    if btype == "context":
        parts = []
        for el in block.get("elements", []):
            parts.append(_render_mrkdwn(el.get("text", "")))
        return f'<div class="block-context">{" ".join(parts)}</div>'
    if btype == "actions":
        btns = []
        for el in block.get("elements", []):
            style = el.get("style", "")
            cls = "btn-primary" if style == "primary" else (
                "btn-danger" if style == "danger" else "")
            label = el.get("text", {}).get("text", "?")
            btns.append(f'<span class="btn {cls}">{label}</span>')
        return f'<div class="block-actions">{"".join(btns)}</div>'
    if btype == "divider":
        return '<div class="block-divider"></div>'
    if btype == "header":
        txt = block.get("text", {}).get("text", "")
        return f'<div class="block-header">{txt}</div>'
    if btype == "input":
        label = block.get("label", {}).get("text", "")
        return (f'<div class="block-section"><strong>{label}</strong><br>'
                f'<input type="text" class="code" placeholder="..." '
                f'style="width:100%;padding:6px;margin-top:4px"></div>')
    return f'<div class="block-context">[{btype}]</div>'


def _render_message(blocks: list[dict], label: str = "",
                    is_thread: bool = False) -> str:
    cls = "message thread" if is_thread else "message"
    parts = []
    if label:
        parts.append(f'<span class="label">{label}</span>')
    for b in blocks:
        parts.append(_render_block(b))
    return f'<div class="{cls}">{"".join(parts)}</div>'


def _get_workspace(request):
    from apps.workspaces.models import Workspace
    return Workspace.objects.filter(
        memberships__user=request.user,
    ).first()


def _get_installation(workspace):
    from .models import SlackInstallation
    return SlackInstallation.objects.filter(
        ace_workspace=workspace,
    ).first()


@require_GET
@_require_auth
def test_index(request: HttpRequest) -> HttpResponse:
    workspace = _get_workspace(request)
    if workspace is None:
        return HttpResponse("No workspace found", status=404)

    from apps.opps.api import list_opp_cards
    cards = list_opp_cards(workspace) or []

    opp_items = []
    for card in cards[:30]:
        slug = card.get("slug", "")
        name = card.get("display_name", slug)
        run_count = card.get("run_count", 0)
        opp_items.append(
            f'<li><a href="preview/{slug}/">'
            f'{name}</a> <span style="color:#9ea0a5">'
            f'({run_count} runs)</span></li>'
        )

    installation = _get_installation(workspace)
    slack_status = (
        f'<span style="color:#2eb67d">Connected</span> '
        f'({installation.slack_team_name})'
        if installation else
        '<span style="color:#e01e5a">Not installed</span>'
    )

    cleanup_form = ""
    if installation:
        cleanup_form = """
        <div class="post-form" style="margin-top:24px">
          <h2>Clean up channel</h2>
          <p style="color:#9ea0a5;font-size:13px;margin-bottom:8px">
            Delete all bot messages and their thread replies from a channel.</p>
          <form method="POST" action="cleanup/">
            <label>Channel ID</label>
            <input type="text" name="channel_id" placeholder="C0123456789">
            <br><button type="submit" class="btn btn-danger"
                        style="margin-top:8px">
              Delete all bot messages</button>
          </form>
        </div>"""

    html = f"""<!DOCTYPE html><html><head>
<meta charset="utf-8"><title>Slack Test</title>
<style>{_CSS}</style></head><body>
<div class="nav">ace-web / {workspace.slug} / slack test</div>
<h1>Slack Integration Test Page</h1>
<p style="margin-bottom:16px">Slack: {slack_status}</p>
<h2>Pick an opp to preview</h2>
<ul class="opp-list">{"".join(opp_items) or "<li>No opps found</li>"}</ul>
{cleanup_form}
</body></html>"""
    return HttpResponse(html)


@require_GET
@_require_auth
def test_preview(request: HttpRequest, slug: str) -> HttpResponse:
    workspace = _get_workspace(request)
    if workspace is None:
        return HttpResponse("No workspace found", status=404)

    run_id = request.GET.get("run_id")
    snapshot = load_rich_opp_snapshot(workspace, slug, run_id=run_id)
    if snapshot is None:
        return HttpResponse(f"Opp '{slug}' not found", status=404)
    _normalize_snapshot(snapshot)

    from .blocks import render_parent_card, render_phase_tile

    display_name = snapshot.get("display_name", slug)
    current_run = snapshot.get("current_run") or {}
    run_id_actual = current_run.get("run_id", "?")
    phases = snapshot.get("phases") or []
    decisions = current_run.get("decisions") or []
    steps = current_run.get("steps") or []

    messages_html = []

    # Parent card
    try:
        parent_blocks = render_parent_card(
            snapshot, opp_slug=slug,
            workspace_slug=workspace.slug,
            triggerer_display="@you",
            elapsed_seconds=0,
        )
        messages_html.append(
            _render_message(parent_blocks, "Parent card"))
    except Exception as exc:
        messages_html.append(
            f'<div class="result result-err">Parent card error: {exc}</div>')

    # Phase tiles
    for phase in sorted(phases, key=lambda p: p.get("ordinal", 0)):
        pname = phase.get("name", "")
        phase_steps = [s for s in steps if s.get("phase") == pname]
        if not phase_steps:
            continue

        try:
            tile_blocks = render_phase_tile(
                snapshot, phase_name=pname,
                opp_slug=slug, workspace_slug=workspace.slug,
            )
            messages_html.append(
                _render_message(tile_blocks,
                                f"Phase {phase.get('ordinal', '?')}: "
                                f"{phase.get('display_name', pname)}"))
        except Exception as exc:
            messages_html.append(
                f'<div class="result result-err">Phase tile error '
                f'({pname}): {exc}</div>')

    # Raw JSON dump
    raw_json = json.dumps({
        "keys": list(snapshot.keys()),
        "phases_count": len(phases),
        "steps_count": len(steps),
        "decisions_count": len(decisions),
        "run_id": run_id_actual,
    }, indent=2)

    installation = _get_installation(workspace)
    post_section = ""
    if installation:
        post_section = f"""
        <div class="post-form">
          <h2>Post to Slack</h2>
          <form method="POST" action="../../post/{slug}/">
            <label>Channel ID (find in Slack channel details)</label>
            <input type="text" name="channel_id" placeholder="C0123456789"
                   value="{request.GET.get('channel', '')}">
            <input type="hidden" name="run_id" value="{run_id or ''}">
            <br><button type="submit" class="btn btn-primary"
                        style="margin-top:8px">
              Post all messages to channel</button>
          </form>
        </div>"""

    html = f"""<!DOCTYPE html><html><head>
<meta charset="utf-8"><title>Slack Preview: {slug}</title>
<style>{_CSS}</style></head><body>
<div class="nav">
  <a href="../">← back</a> / {slug} / {run_id_actual}
</div>
<h1>{display_name}</h1>
<p style="color:#9ea0a5;margin-bottom:4px">
  Run: <code>{run_id_actual}</code> ·
  {len(phases)} phases · {len(steps)} steps ·
  {len(decisions)} decisions
</p>

<div class="tab-bar">
  <span class="tab active" onclick="
    document.getElementById('preview').style.display='block';
    document.getElementById('raw').style.display='none';
    this.classList.add('active');
    this.nextElementSibling.classList.remove('active');
  ">Preview</span>
  <span class="tab" onclick="
    document.getElementById('preview').style.display='none';
    document.getElementById('raw').style.display='block';
    this.classList.add('active');
    this.previousElementSibling.classList.remove('active');
  ">Raw JSON</span>
</div>

<div id="preview">{"".join(messages_html)}</div>
<div id="raw" style="display:none">
  <div class="json-dump">{raw_json}</div>
</div>

{post_section}

</body></html>"""
    return HttpResponse(html)


@csrf_exempt
@require_POST
@_require_auth
def test_post(request: HttpRequest, slug: str) -> HttpResponse:
    workspace = _get_workspace(request)
    if workspace is None:
        return HttpResponse("No workspace found", status=404)

    installation = _get_installation(workspace)
    if installation is None:
        return HttpResponse("Slack not installed", status=404)

    channel_id = request.POST.get("channel_id", "").strip()
    if not channel_id:
        return HttpResponse("channel_id required", status=400)

    run_id = request.POST.get("run_id") or None
    snapshot = load_rich_opp_snapshot(workspace, slug, run_id=run_id)
    if snapshot is None:
        return HttpResponse(f"Opp '{slug}' not found", status=404)
    _normalize_snapshot(snapshot)

    from .blocks import render_parent_card, render_phase_tile
    from .slack_client import client_for

    client = client_for(installation)
    results = []

    current_run = snapshot.get("current_run") or {}
    run_id_actual = current_run.get("run_id", "?")
    phases = snapshot.get("phases") or []
    steps = current_run.get("steps") or []

    # Post parent card
    try:
        parent_blocks = render_parent_card(
            snapshot, opp_slug=slug,
            workspace_slug=workspace.slug,
            triggerer_display="Slack Test Page",
            elapsed_seconds=0,
        )
        parent_ts = client.post_message(
            channel=channel_id, blocks=parent_blocks,
            text=f"ACE run test: {slug}/{run_id_actual}",
        )
        results.append(f"Parent card posted (ts={parent_ts})")
    except Exception as exc:
        results.append(f"Parent card FAILED: {exc}")
        parent_ts = None

    # Post phase tiles as thread replies
    for phase in sorted(phases, key=lambda p: p.get("ordinal", 0)):
        pname = phase.get("name", "")
        phase_steps = [s for s in steps if s.get("phase") == pname]
        if not phase_steps:
            continue

        try:
            tile_blocks = render_phase_tile(
                snapshot, phase_name=pname,
                opp_slug=slug, workspace_slug=workspace.slug,
            )
            client.post_message(
                channel=channel_id, blocks=tile_blocks,
                text=f"Phase: {pname}",
                thread_ts=parent_ts,
            )
            results.append(f"Phase tile: {pname}")
        except Exception as exc:
            results.append(f"Phase tile FAILED ({pname}): {exc}")

    result_items = "".join(f"<li>{r}</li>" for r in results)
    html = f"""<!DOCTYPE html><html><head>
<meta charset="utf-8"><title>Post Result</title>
<style>{_CSS}</style></head><body>
<div class="nav"><a href="../preview/{slug}/?channel={channel_id}">
  ← back to preview</a></div>
<h1>Posted to #{channel_id}</h1>
<div class="result result-ok">
  <ul style="list-style:none">{result_items}</ul>
</div>
</body></html>"""
    return HttpResponse(html)


@csrf_exempt
@require_POST
@_require_auth
def test_cleanup(request: HttpRequest) -> HttpResponse:
    """Delete all bot messages (and their thread replies) from a channel."""
    workspace = _get_workspace(request)
    if workspace is None:
        return HttpResponse("No workspace found", status=404)

    installation = _get_installation(workspace)
    if installation is None:
        return HttpResponse("Slack not installed", status=404)

    channel_id = request.POST.get("channel_id", "").strip()
    if not channel_id:
        return HttpResponse("channel_id required", status=400)

    from .slack_client import client_for

    client = client_for(installation)

    deleted = 0
    errors = []
    try:
        messages = client.get_channel_history(channel=channel_id, limit=50)
        for msg in messages:
            if msg.get("bot_id") or msg.get("subtype") == "bot_message":
                ts = msg["ts"]
                replies = client.get_thread_replies(
                    channel=channel_id, ts=ts)
                for reply_ts in replies:
                    try:
                        client.delete_message(
                            channel=channel_id, ts=reply_ts)
                        deleted += 1
                    except Exception as exc:
                        errors.append(f"reply {reply_ts}: {exc}")
                try:
                    client.delete_message(channel=channel_id, ts=ts)
                    deleted += 1
                except Exception as exc:
                    errors.append(f"parent {ts}: {exc}")
    except Exception as exc:
        errors.append(f"history: {exc}")

    err_html = ""
    if errors:
        err_items = "".join(f"<li>{e}</li>" for e in errors)
        err_html = (f'<div class="result result-err">'
                    f'<ul style="list-style:none">{err_items}</ul></div>')

    html = f"""<!DOCTYPE html><html><head>
<meta charset="utf-8"><title>Cleanup Result</title>
<style>{_CSS}</style></head><body>
<div class="nav"><a href="../">← back</a></div>
<h1>Cleaned up #{channel_id}</h1>
<div class="result result-ok">Deleted {deleted} messages.</div>
{err_html}
</body></html>"""
    return HttpResponse(html)
