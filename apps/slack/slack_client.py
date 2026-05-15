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
        resp = self._web.chat_postMessage(
            channel=channel, blocks=blocks, text=text, thread_ts=thread_ts,
        )
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
        resp = self._web.chat_postMessage(
            channel=channel, text=text, blocks=blocks or [],
        )
        return resp["ts"]

    def open_view(self, *, trigger_id: str, view: dict) -> None:
        try:
            self._web.views_open(trigger_id=trigger_id, view=view)
        except SlackApiError as e:
            self._raise_typed(e)

    def lookup_user_info(self, *, slack_user_id: str) -> dict[str, Any]:
        resp = self._web.users_info(user=slack_user_id)
        return resp["user"]

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
