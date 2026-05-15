import pytest

from apps.slack.pending import (
    PendingMissing,
    save_pending_command,
    take_pending_command,
)


def test_save_and_take_roundtrip():
    nonce = save_pending_command(
        slack_user_id="U_JJ",
        team_id="T1",
        channel_id="C1",
        command_text="/ace run my-opp",
    )
    payload = take_pending_command(nonce)
    assert payload["slack_user_id"] == "U_JJ"
    assert payload["command_text"] == "/ace run my-opp"


def test_take_after_consume_raises():
    nonce = save_pending_command(slack_user_id="U_JJ", team_id="T1",
                                 channel_id="C1", command_text="/ace help")
    take_pending_command(nonce)
    with pytest.raises(PendingMissing):
        take_pending_command(nonce)


def test_take_unknown_nonce_raises():
    with pytest.raises(PendingMissing):
        take_pending_command("never-existed")
