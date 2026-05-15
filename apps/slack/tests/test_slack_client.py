from unittest.mock import MagicMock

import pytest
from slack_sdk.errors import SlackApiError

from apps.slack.slack_client import (
    SlackChannelGone,
    SlackClient,
    SlackRateLimited,
)


def _make_client(web_client_mock):
    c = SlackClient.__new__(SlackClient)
    c._web = web_client_mock
    return c


def test_post_message_returns_ts():
    web = MagicMock()
    web.chat_postMessage.return_value = {"ok": True, "ts": "1.2"}
    client = _make_client(web)
    ts = client.post_message(channel="C1", blocks=[], text="x")
    assert ts == "1.2"


def test_update_message_swallows_channel_not_found():
    web = MagicMock()
    err = SlackApiError(message="channel_not_found",
                       response={"error": "channel_not_found"})
    web.chat_update.side_effect = err
    client = _make_client(web)
    with pytest.raises(SlackChannelGone):
        client.update_message(channel="C1", ts="1.2", blocks=[], text="x")


def test_update_message_rate_limit_raises_typed():
    web = MagicMock()
    err = SlackApiError(message="rate_limited",
                       response={"error": "rate_limited",
                                 "headers": {"Retry-After": "3"}})
    web.chat_update.side_effect = err
    client = _make_client(web)
    with pytest.raises(SlackRateLimited) as exc:
        client.update_message(channel="C1", ts="1.2", blocks=[], text="x")
    assert exc.value.retry_after == 3
