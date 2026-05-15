import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.utils import timezone

from apps.slack.models import SlackInstallation, SlackRunThread, SlackUserLink
from apps.workspaces.models import Workspace


@pytest.mark.django_db
def test_installation_round_trip_encrypts_token():
    User = get_user_model()
    user = User.objects.create(email="admin@dimagi.com")
    ws = Workspace.objects.create(
        slug="dimagi-team",
        display_name="Dimagi Team",
        drive_root_folder_id="folder-1",
        created_by=user,
    )
    inst = SlackInstallation.objects.create(
        slack_team_id="T0001",
        slack_team_name="Dimagi",
        bot_user_id="U_BOT",
        ace_workspace=ws,
        installed_by_user=user,
    )
    inst.bot_token = "xoxb-secret-token"
    inst.save()

    refetched = SlackInstallation.objects.get(pk=inst.pk)
    # Raw column is encrypted (not plaintext).
    assert "xoxb-secret-token" not in refetched.bot_token_encrypted
    # Accessor decrypts.
    assert refetched.bot_token == "xoxb-secret-token"


@pytest.mark.django_db
def test_user_link_unique_per_installation_and_slack_user():
    User = get_user_model()
    user1 = User.objects.create(email="jj@dimagi.com")
    user2 = User.objects.create(email="other@dimagi.com")
    ws = Workspace.objects.create(
        slug="dimagi-team",
        display_name="Dimagi Team",
        drive_root_folder_id="folder-1",
        created_by=user1,
    )
    inst = SlackInstallation.objects.create(
        slack_team_id="T0001",
        slack_team_name="Dimagi",
        bot_user_id="U_BOT",
        ace_workspace=ws,
        installed_by_user=user1,
    )
    SlackUserLink.objects.create(
        installation=inst,
        slack_user_id="U_JJ",
        ace_user=user1,
        slack_email="jj@dimagi.com",
        slack_real_name="JJ",
    )
    with pytest.raises(IntegrityError):
        SlackUserLink.objects.create(
            installation=inst,
            slack_user_id="U_JJ",
            ace_user=user2,
            slack_email="other@dimagi.com",
            slack_real_name="Other",
        )


@pytest.mark.django_db
def test_run_thread_unique_per_slug_and_run_id():
    User = get_user_model()
    user = User.objects.create(email="jj@dimagi.com")
    ws = Workspace.objects.create(
        slug="dimagi-team",
        display_name="Dimagi Team",
        drive_root_folder_id="folder-1",
        created_by=user,
    )
    inst = SlackInstallation.objects.create(
        slack_team_id="T0001",
        slack_team_name="Dimagi",
        bot_user_id="U_BOT",
        ace_workspace=ws,
        installed_by_user=user,
    )
    SlackRunThread.objects.create(
        installation=inst,
        channel_id="C1",
        parent_ts="1.1",
        opp_slug="my-opp",
        run_id="run-001",
        ace_user=user,
    )
    with pytest.raises(IntegrityError):
        SlackRunThread.objects.create(
            installation=inst,
            channel_id="C2",
            parent_ts="2.2",
            opp_slug="my-opp",
            run_id="run-001",
            ace_user=user,
        )


@pytest.mark.django_db
def test_user_link_can_relink_after_unlink():
    """Partial index allows a new active link after a prior link is soft-deleted."""
    User = get_user_model()
    user = User.objects.create(email="jj@dimagi.com")
    ws = Workspace.objects.create(
        slug="dimagi-team",
        display_name="Dimagi Team",
        drive_root_folder_id="folder-1",
        created_by=user,
    )
    inst = SlackInstallation.objects.create(
        slack_team_id="T0001",
        slack_team_name="Dimagi",
        bot_user_id="U_BOT",
        ace_workspace=ws,
        installed_by_user=user,
    )
    # Create the initial active link.
    original = SlackUserLink.objects.create(
        installation=inst,
        slack_user_id="U_JJ",
        ace_user=user,
        slack_email="jj@dimagi.com",
        slack_real_name="JJ",
    )
    # Soft-delete it (simulate unlink).
    original.unlinked_at = timezone.now()
    original.save()

    # Re-linking with the same (installation, slack_user_id) must not raise.
    new_link = SlackUserLink.objects.create(
        installation=inst,
        slack_user_id="U_JJ",
        ace_user=user,
        slack_email="jj@dimagi.com",
        slack_real_name="JJ",
    )
    assert new_link.pk is not None
    assert new_link.unlinked_at is None
