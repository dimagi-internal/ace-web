"""Thin slack_sdk wrapper with typed errors.

We catch `channel_not_found` / `is_archived` / `rate_limited` here so the
dispatcher / handlers don't have to know about slack_sdk's loose error
shape. Everything else bubbles up as the raw SlackApiError.
"""
from __future__ import annotations

import logging
from typing import Any

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

logger = logging.getLogger(__name__)

_GONE_ERRORS = {"channel_not_found", "is_archived", "not_in_channel"}


class SlackChannelGone(Exception):
    pass


class SlackRateLimited(Exception):
    def __init__(self, retry_after: int):
        super().__init__(f"slack rate-limited; retry after {retry_after}s")
        self.retry_after = retry_after


class SlackClient:
    def __init__(self, token: str):
        self._web = WebClient(token=token)

    def post_message(self, *, channel: str, blocks: list[dict],
                     text: str, thread_ts: str | None = None) -> str:
        try:
            resp = self._web.chat_postMessage(
                channel=channel, blocks=blocks, text=text, thread_ts=thread_ts,
            )
        except SlackApiError as e:
            self._raise_typed(e)
            raise  # unreachable but keeps the type checker happy
        return resp["ts"]

    def update_message(self, *, channel: str, ts: str,
                       blocks: list[dict], text: str) -> None:
        try:
            self._web.chat_update(channel=channel, ts=ts, blocks=blocks, text=text)
        except SlackApiError as e:
            self._raise_typed(e)

    def post_ephemeral(self, *, channel: str, user: str,
                       text: str, blocks: list[dict] | None = None) -> None:
        try:
            self._web.chat_postEphemeral(
                channel=channel, user=user, text=text, blocks=blocks or [],
            )
        except SlackApiError as e:
            self._raise_typed(e)

    def dm_user(self, *, user: str, text: str,
                blocks: list[dict] | None = None) -> str:
        opened = self._web.conversations_open(users=user)
        channel = opened["channel"]["id"]
        try:
            resp = self._web.chat_postMessage(
                channel=channel, text=text, blocks=blocks or [],
            )
        except SlackApiError as e:
            self._raise_typed(e)
            raise  # unreachable but keeps the type checker happy
        return resp["ts"]

    def open_view(self, *, trigger_id: str, view: dict) -> None:
        try:
            self._web.views_open(trigger_id=trigger_id, view=view)
        except SlackApiError as e:
            self._raise_typed(e)

    def delete_message(self, *, channel: str, ts: str) -> None:
        try:
            self._web.chat_delete(channel=channel, ts=ts)
        except SlackApiError as e:
            self._raise_typed(e)

    def get_channel_history(self, *, channel: str,
                            limit: int = 50) -> list[dict]:
        try:
            resp = self._web.conversations_history(
                channel=channel, limit=limit)
            return resp.get("messages", [])
        except SlackApiError:
            return []

    def get_thread_replies(self, *, channel: str, ts: str) -> list[str]:
        try:
            resp = self._web.conversations_replies(channel=channel, ts=ts)
            return [m["ts"] for m in resp.get("messages", []) if m["ts"] != ts]
        except SlackApiError:
            return []

    def lookup_user_info(self, *, slack_user_id: str) -> dict[str, Any]:
        resp = self._web.users_info(user=slack_user_id)
        return resp["user"]

    def list_member_conversations(self, *, limit: int = 200) -> list[dict[str, Any]]:
        """Channels the bot is currently a member of (public + private).

        Requires `channels:read` + `groups:read` bot scopes. Slack's
        conversations.list returns up to 1000 per page; ace-web caps at
        `limit` so the UI picker stays responsive. We pull a single
        page — workspaces with more than 1000 bot-member channels are
        not the use case.
        """
        try:
            resp = self._web.conversations_list(
                types="public_channel,private_channel",
                exclude_archived=True,
                limit=limit,
            )
        except SlackApiError:
            return []
        out: list[dict[str, Any]] = []
        for c in resp.get("channels", []):
            if not c.get("is_member"):
                continue
            out.append({
                "id": c["id"],
                "name": c.get("name") or c["id"],
                "is_private": bool(c.get("is_private")),
            })
        out.sort(key=lambda c: (c["is_private"], c["name"]))
        return out

    def get_permalink(self, *, channel: str, message_ts: str) -> str | None:
        """Resolve a (channel, ts) into the canonical Slack permalink.

        Returns None on any error — callers should fall back to a
        constructed URL or render without the link.
        """
        try:
            resp = self._web.chat_getPermalink(
                channel=channel, message_ts=message_ts,
            )
            return resp.get("permalink")
        except SlackApiError:
            return None

    def views_publish(self, *, user_id: str, view: dict) -> None:
        """Publish a Block Kit view to a user's App Home tab.

        Requires no extra scope beyond bot install. Idempotent: Slack
        replaces the previously-published view atomically.
        """
        try:
            self._web.views_publish(user_id=user_id, view=view)
        except SlackApiError as e:
            self._raise_typed(e)

    def auth_test(self) -> dict[str, Any]:
        """Call auth.test — returns {url, team, user, team_id, user_id, ...}.

        The `url` field is the team URL (e.g. https://dimagi.slack.com/)
        used to construct deep links.
        """
        resp = self._web.auth_test()
        return resp.data

    def _raise_typed(self, e: SlackApiError) -> None:
        err = e.response.get("error", "")
        if err in _GONE_ERRORS:
            raise SlackChannelGone(err) from e
        if err == "rate_limited":
            retry = int(e.response.get("headers", {}).get("Retry-After", 1))
            raise SlackRateLimited(retry) from e
        raise


def client_for(installation) -> SlackClient:
    """Construct a SlackClient from a SlackInstallation row."""
    return SlackClient(installation.bot_token)
