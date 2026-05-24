"""Per-user Block Kit view published to the ACE bot's App Home tab.

Slack delivers an `app_home_opened` event whenever a user opens the
bot's Home tab. We respond by computing a fresh view and publishing it
via `views.publish`. The view is per-user — linked users see their
tracked runs and workspace activity; unlinked users get a sign-in CTA.

Why this exists: today the bot has no screen of its own. Every
interaction starts with the user remembering `/ace foo`. The Home tab
is Slack's native "show me what this bot knows about me" surface.
"""
from __future__ import annotations

import datetime as dt
import logging

from django.conf import settings

from .models import SlackInstallation, SlackRunThread, SlackUserLink

logger = logging.getLogger(__name__)

_TRACKED_RUN_LIMIT = 5
_ACTIVITY_ROW_LIMIT = 5


def _base_url() -> str:
    return getattr(
        settings, "ACE_PUBLIC_BASE_URL", "https://labs.connect.dimagi.com/ace",
    )


def _link_url(nonce: str | None = None) -> str:
    """Single-use OAuth-link URL. Mirrors `handlers._link_url` shape."""
    from urllib.parse import urlencode
    qs = urlencode({"nonce": nonce}) if nonce else ""
    return f"{_base_url()}/auth/slack/link/" + (f"?{qs}" if qs else "")


def _human_delta(now: dt.datetime, then: dt.datetime | None) -> str:
    if then is None:
        return ""
    secs = int((now - then).total_seconds())
    if secs < 60:
        return f"{secs}s ago"
    if secs < 3600:
        return f"{secs // 60}m ago"
    if secs < 86400:
        return f"{secs // 3600}h ago"
    return f"{secs // 86400}d ago"


def render_unlinked_view(*, installation: SlackInstallation,
                         slack_user_id: str) -> dict:
    """Home view for a user who hasn't linked their ace-web account yet."""
    from .pending import save_pending_command

    nonce = save_pending_command(
        slack_user_id=slack_user_id,
        team_id=installation.slack_team_id,
        channel_id="",
        command_text="/ace help",
        trigger_id=None,
    )
    return {
        "type": "home",
        "blocks": [
            {"type": "header",
             "text": {"type": "plain_text", "text": "ACE"}},
            {"type": "section",
             "text": {"type": "mrkdwn",
                      "text": ("Link your Slack identity to ace-web to "
                               "trigger runs, watch progress, and see "
                               "your tracked runs here.")}},
            {"type": "actions", "elements": [
                {"type": "button",
                 "text": {"type": "plain_text", "text": "Link account"},
                 "url": _link_url(nonce),
                 "style": "primary"},
            ]},
            {"type": "context",
             "elements": [{"type": "mrkdwn",
                           "text": "Linking is single-use and expires in 10 minutes."}]},
        ],
    }


def _activity_lines(*, installation: SlackInstallation,
                    now: dt.datetime) -> list[str]:
    """Top-N workspace activity rows rendered as mrkdwn bullets.

    Reuses the same data source as `/ace activity` and the web Activity
    page — observable facts only, no 'is running' labels.
    """
    try:
        from apps.activity.api import get_workspace_activity
        result = get_workspace_activity(
            installation.ace_workspace,
            include_completed=True, limit=_ACTIVITY_ROW_LIMIT,
        )
    except Exception:
        logger.exception("home_view: get_workspace_activity failed")
        return []
    rows = result.get("rows", [])
    base = _base_url()
    out: list[str] = []
    for r in rows[:_ACTIVITY_ROW_LIMIT]:
        opp_slug = r.get("opp_slug") or "?"
        display_name = r.get("opp_display_name") or opp_slug
        run_id = r.get("run_id") or ""
        phase = r.get("current_phase_display") or r.get("current_phase_name")
        phase_url = r.get("phase_url") or (
            f"{base}/w/{installation.ace_workspace.slug}/opps/{opp_slug}"
        )
        last_iso = r.get("last_activity_at")
        try:
            last_dt = (dt.datetime.fromisoformat(last_iso.replace("Z", "+00:00"))
                       if last_iso else None)
        except (ValueError, AttributeError):
            last_dt = None
        delta = _human_delta(now, last_dt)
        parts = [f"*<{phase_url}|{display_name}>*", f"`{run_id}`"]
        if phase:
            parts.append(f"`{phase}`")
        if delta:
            parts.append(f"_{delta}_")
        out.append("• " + " · ".join(parts))
    return out


def _tracked_run_lines(*, installation: SlackInstallation,
                       user_link: SlackUserLink) -> list[str]:
    threads = (
        SlackRunThread.objects
        .filter(installation=installation, ace_user=user_link.ace_user,
                broken_at__isnull=True, stopped_at__isnull=True)
        .order_by("-triggered_at")[:_TRACKED_RUN_LIMIT]
    )
    base = _base_url()
    ws_slug = installation.ace_workspace.slug
    out: list[str] = []
    for t in threads:
        opp_url = f"{base}/w/{ws_slug}/opps/{t.opp_slug}?run_id={t.run_id}"
        out.append(
            f"• *<{opp_url}|{t.opp_slug}>* · `{t.run_id}` · "
            f"in <#{t.channel_id}>"
        )
    return out


def render_linked_view(*, installation: SlackInstallation,
                       user_link: SlackUserLink) -> dict:
    """Home view for a linked user."""
    now = dt.datetime.now(dt.UTC)
    user = user_link.ace_user
    workspace = installation.ace_workspace

    blocks: list[dict] = [
        {"type": "header",
         "text": {"type": "plain_text", "text": "ACE"}},
        {"type": "section",
         "text": {"type": "mrkdwn",
                  "text": (f"*Linked as* `{user.email}` · "
                           f"*Workspace* `{workspace.slug}`")}},
        {"type": "divider"},
    ]

    # Your tracked runs.
    tracked = _tracked_run_lines(installation=installation, user_link=user_link)
    blocks.append({
        "type": "section",
        "text": {"type": "mrkdwn",
                 "text": f"*Your tracked runs* ({len(tracked)})"},
    })
    if tracked:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": "\n".join(tracked)},
        })
    else:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn",
                     "text": "_You aren't tracking any runs. "
                             "Try `/ace run <slug>` in any channel where ACE is invited._"},
        })

    # Workspace activity (top 5).
    activity = _activity_lines(installation=installation, now=now)
    if activity:
        blocks.append({"type": "divider"})
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn",
                     "text": f"*Workspace activity* (top {len(activity)})"},
        })
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": "\n".join(activity)},
        })

    # Quick actions.
    base = _base_url()
    blocks.append({"type": "divider"})
    blocks.append({
        "type": "actions",
        "elements": [
            {"type": "button",
             "text": {"type": "plain_text", "text": "Open ace-web"},
             "url": f"{base}/w/{workspace.slug}/opps"},
            {"type": "button",
             "text": {"type": "plain_text", "text": "Workspace activity"},
             "url": f"{base}/w/{workspace.slug}/activity"},
            {"type": "button",
             "text": {"type": "plain_text", "text": "Settings"},
             "url": f"{base}/w/{workspace.slug}/workspace-settings"},
        ],
    })
    blocks.append({
        "type": "context",
        "elements": [{"type": "mrkdwn",
                      "text": "Tip: `/ace help` for the full command list."}],
    })

    return {"type": "home", "blocks": blocks}


def publish_for_user(*, team_id: str, slack_user_id: str) -> bool:
    """Compute + publish the Home view for one user. Returns True on success.

    Called from `views.py:events` on `app_home_opened`. Swallows errors
    (logs them) — Slack does not retry app_home_opened, so a failure
    just means the user sees yesterday's view until they re-open.
    """
    from .slack_client import client_for

    try:
        installation = SlackInstallation.objects.get(slack_team_id=team_id)
    except SlackInstallation.DoesNotExist:
        logger.warning("app_home_opened from unknown team %s", team_id)
        return False
    user_link = (
        SlackUserLink.objects
        .filter(installation=installation, slack_user_id=slack_user_id,
                unlinked_at__isnull=True)
        .select_related("ace_user").first()
    )
    if user_link is None:
        view = render_unlinked_view(
            installation=installation, slack_user_id=slack_user_id,
        )
    else:
        view = render_linked_view(
            installation=installation, user_link=user_link,
        )
    try:
        client_for(installation).views_publish(user_id=slack_user_id, view=view)
        return True
    except Exception:
        logger.exception(
            "views_publish failed for team %s user %s", team_id, slack_user_id,
        )
        return False
