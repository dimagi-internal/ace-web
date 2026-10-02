"""apps.slack.run_starter — Slack-triggered runs actually execute (they never did).

Every other Slack test mocks `start_run_from_slack` out of existence, which is
why this module was green in CI since May while doing nothing at all. These
tests deliberately call the real function and assert the *damage* each defect
caused, not the nearest observable symptom:

  1. `/ace run <slug>` created rows and executed nothing — so the assertion is
     that the `/ace:run <slug>/<run_id>` command reaches canopy's send, not
     merely that some function was called.
  2. The run it created was invisible to the post-deploy resume sweep forever
     (both `interrupted()` and `resumable_after_deploy()` require an assistant
     row) — so the assertion is that the sweep can see it.
  3. `/ace new` and `/ace run <pdd-link>` crashed before creating anything —
     so the assertion is that the opp, its session and its dispatch exist,
     with `ACE_DRIVE_SA_KEY_JSON` populated exactly as it is in production.
"""

from __future__ import annotations

import json
from unittest import mock

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings

from apps.opps.models import OppWorkspace
from apps.opps.tests.fixtures.fake_drive import FakeDriveClient
from apps.sessions.models import Message, Session
from apps.slack import run_starter
from apps.workspaces.models import Workspace

User = get_user_model()
pytestmark = pytest.mark.django_db

# The production shape of the setting the old code passed straight into
# googleapiclient. A NON-EMPTY string is the point: `build(credentials="")`
# happens to be tolerated, so an empty test default would have hidden the bug.
PROD_SA_KEY = json.dumps(
    {"type": "service_account", "client_email": "ace@x.iam.gserviceaccount.com"}
)

# Canopy run execution ON, so dispatch goes down the canopy path where the
# prompt text is observable on the wire.
CANOPY_ON = dict(
    CANOPY_BASE_URL="http://canopy.test",
    CANOPY_SIGNING_KEY="test-key",
    CANOPY_WORKSPACE="connect",
    CANOPY_AGENT_SLUG="ace",
    CANOPY_RUN_EXECUTION=True,
)


def _fixture():
    user = User.objects.create_user(email="slacker@dimagi.com")
    ws = Workspace.objects.create(
        slug="ws", display_name="ws", drive_root_folder_id="fake-root", created_by=user,
    )
    OppWorkspace.objects.create(
        slug="opp-a", display_name="A", created_by=user, workspace=ws,
    )
    return user, ws


def _canopy_patches(send_return=None):
    """Patch the canopy client calls run_dispatch makes, leaving run_dispatch
    itself real so the prompt text is asserted on the actual wire payload."""
    return (
        mock.patch("apps.canopy.client.visitor_token",
                   return_value={"token": "usertok", "kind": "user"}),
        mock.patch("apps.canopy.client.Principal.create_session", return_value={"id": "sess-9"}),
        mock.patch(
            "apps.canopy.client.Principal.send",
            return_value=send_return or {"turn_id": "turn-9", "message": {}},
        ),
        mock.patch("apps.canopy.client.Principal.stop", return_value={"cancelled": False}),
    )


def _fake_drive():
    """An empty in-memory Drive rooted at `fake-root` — the id the fixture
    workspace's `drive_root_folder_id` points at — so create_opp's collision
    scan and folder/file writes all succeed without touching Google."""
    return FakeDriveClient.from_tree({})


# --------------------------------------------------------------------------
# Defect 1: `/ace run <existing-slug>` created rows and executed nothing.
# --------------------------------------------------------------------------


@override_settings(**CANOPY_ON)
def test_slug_run_sends_the_ace_run_command_to_canopy():
    """The damage: the run never executed. Assert the actual command text
    lands on canopy's send — not merely that a seam function was called."""
    user, ws = _fixture()
    ex, create, send, stop = _canopy_patches()
    with ex, create, send as send_m, stop:
        slug, run_id = run_starter.start_run_from_slack(
            slug_or_link="opp-a", user=user, workspace=ws,
        )

    assert slug == "opp-a"
    send_m.assert_called_once()
    assert send_m.call_args.kwargs["text"] == f"Run /ace:run opp-a/{run_id}."

    session = Session.objects.get(opp_slug="opp-a", opp_run_id=run_id)
    assistant = Message.objects.get(session=session, role="assistant")
    assert assistant.status == "pending"
    assert assistant.canopy_turn_id == "turn-9"
    assert send_m.call_args.kwargs["client_id"] == f"acerun:{assistant.pk}"


def test_slug_run_dispatches_the_assistant_placeholder_through_the_seam():
    """Flag-independent: the route must go through run_dispatch.start_turn, or
    CANOPY_RUN_EXECUTION has no effect on a Slack-triggered run."""
    user, ws = _fixture()
    with mock.patch("apps.canopy.run_dispatch.start_turn") as start:
        slug, run_id = run_starter.start_run_from_slack(
            slug_or_link="opp-a", user=user, workspace=ws,
        )
    session = Session.objects.get(opp_slug="opp-a", opp_run_id=run_id)
    assistant = Message.objects.get(session=session, role="assistant")
    start.assert_called_once_with(assistant.id)
    # The user turn still precedes it — the prompt resolution depends on it.
    user_turn = Message.objects.get(session=session, role="user")
    assert user_turn.turn_index < assistant.turn_index
    assert user_turn.status == "complete"


def test_the_created_run_is_visible_to_the_post_deploy_resume_sweep():
    """The old shape (user message only) was invisible to interrupted() and
    resumable_after_deploy() FOREVER, because both require an assistant row —
    so a Slack run killed by a deploy could never be resumed."""
    user, ws = _fixture()
    with mock.patch("apps.canopy.run_dispatch.start_turn"):
        run_starter.start_run_from_slack(slug_or_link="opp-a", user=user, workspace=ws)
    assert Session.interrupted(grace_seconds=0).filter(opp_slug="opp-a").exists()


@override_settings(**CANOPY_ON)
def test_a_dispatch_failure_is_reported_to_slack_not_swallowed():
    """A run that could not be dispatched must say so. RunStartError renders as
    `:x: <reason>` in Slack; anything else hits verbs_run's bare `except
    Exception` and becomes "Internal error starting run."."""
    from apps.canopy.client import CanopyError

    user, ws = _fixture()
    # The requester preflight passes (canopy resolved them as a user); the
    # DISPATCH is what fails. A preflight failure is a different, earlier
    # refusal that mints nothing — covered by the preflight tests below.
    with mock.patch("apps.canopy.run_dispatch.preflight_run_actor"), \
         mock.patch("apps.canopy.client.visitor_token", side_effect=CanopyError(403, "nope")):
        with pytest.raises(run_starter.RunStartError) as exc:
            run_starter.start_run_from_slack(
                slug_or_link="opp-a", user=user, workspace=ws,
            )
    assert "403" in str(exc.value)
    assistant = Message.objects.get(role="assistant")
    assert assistant.status == "error"
    assert assistant.error_detail.startswith("canopy-dispatch:")


# --------------------------------------------------------------------------
# Defect 3: `/ace new` and `/ace run <pdd-link>` crashed before creating
# anything — GoogleDriveClient(<str>) raises AttributeError, swallowed by the
# caller's bare except and reported as "Internal error starting run."
# --------------------------------------------------------------------------


@override_settings(ACE_DRIVE_SA_KEY_JSON=PROD_SA_KEY, **CANOPY_ON)
def test_idea_branch_creates_the_opp_and_dispatches_its_first_turn():
    """The damage: nothing at all was created. Assert the opp row, its working
    session, and the dispatched turn all exist."""
    user, ws = _fixture()
    ex, create, send, stop = _canopy_patches()
    with mock.patch(
        "apps.opps.drive_client.get_drive_client", return_value=_fake_drive(),
    ) as get_drive, ex, create, send as send_m, stop:
        slug, run_id = run_starter.start_run_from_slack(
            slug_or_link="idea: a new thing", user=user, workspace=ws,
        )

    get_drive.assert_called_once_with(workspace=ws)
    opp = OppWorkspace.objects.get(slug=slug)
    assert opp.workspace_id == ws.pk
    assert run_id == "run-001"

    session = opp.working_session
    assistant = Message.objects.get(session=session, role="assistant")
    assert assistant.status == "pending"
    assert assistant.canopy_turn_id == "turn-9"
    # The turn that runs is the kickoff create_opp seeded, not an empty prompt.
    assert send_m.call_args.kwargs["text"] == f"Run /ace:step idea-to-pdd for {slug}."


@override_settings(ACE_DRIVE_SA_KEY_JSON=PROD_SA_KEY)
def test_pdd_link_branch_creates_the_opp_and_stores_the_link_as_the_idea():
    user, ws = _fixture()
    link = "https://docs.google.com/document/d/abc123/edit"
    drive = _fake_drive()
    with mock.patch(
        "apps.opps.drive_client.get_drive_client", return_value=drive,
    ), mock.patch("apps.canopy.run_dispatch.start_turn") as start:
        slug, _run_id = run_starter.start_run_from_slack(
            slug_or_link=link, user=user, workspace=ws,
        )

    opp = OppWorkspace.objects.get(slug=slug)
    assistant = Message.objects.get(session=opp.working_session, role="assistant")
    start.assert_called_once_with(assistant.id)
    idea_id = drive.file_id(f"{slug}/idea.md")
    assert drive.get_content(idea_id, "text/markdown").content == link


@override_settings(ACE_DRIVE_SA_KEY_JSON=PROD_SA_KEY)
def test_a_missing_drive_service_account_is_reported_not_swallowed():
    from apps.service_accounts.exceptions import ServiceAccountNotFound

    user, ws = _fixture()
    with mock.patch(
        "apps.opps.drive_client.get_drive_client",
        side_effect=ServiceAccountNotFound("ace-drive"),
    ):
        with pytest.raises(run_starter.RunStartError) as exc:
            run_starter.start_run_from_slack(
                slug_or_link="idea: another thing", user=user, workspace=ws,
            )
    assert "Drive" in str(exc.value)
    assert not OppWorkspace.objects.filter(slug__startswith="another").exists()


# --------------------------------------------------------------------------
# The requester preflight: a Slack run is dispatched AS the requester, so a
# requester canopy knows only as a contact (confined to ask-only) must be
# refused before anything is minted — the same check seeded-run and resume
# make (ace-web#845/#846). Before it, the run was created, Slack said
# "Kicking off…", and the turn sat `pending` forever.
# --------------------------------------------------------------------------


class _Principal:
    def __init__(self, is_contact):
        self.is_contact = is_contact


def _assert_nothing_minted(ws):
    assert Session.objects.count() == 0
    assert Message.objects.count() == 0
    assert OppWorkspace.objects.filter(workspace=ws).count() == 1  # the fixture's only


@override_settings(**CANOPY_ON)
def test_a_contact_requester_is_refused_and_nothing_is_created():
    user, ws = _fixture()
    with mock.patch("apps.canopy.client.act_as", return_value=_Principal(True)) as act_as, \
         mock.patch("apps.canopy.run_dispatch.start_turn") as start:
        with pytest.raises(run_starter.RunRequesterRefused) as exc:
            run_starter.start_run_from_slack(slug_or_link="opp-a", user=user, workspace=ws)

    act_as.assert_called_once_with("slacker@dimagi.com")
    start.assert_not_called()
    _assert_nothing_minted(ws)
    assert exc.value.code == "run_actor_unresolvable"
    # Who, why, what to do — the reader is a person in Slack.
    msg = str(exc.value)
    assert "slacker@dimagi.com" in msg
    assert "contact" in msg
    assert "canopy user account" in msg
    assert "Nothing was created" in msg


@override_settings(ACE_DRIVE_SA_KEY_JSON=PROD_SA_KEY, **CANOPY_ON)
def test_a_contact_requester_creates_no_opp_from_an_idea_either():
    user, ws = _fixture()
    with mock.patch("apps.canopy.client.act_as", return_value=_Principal(True)), \
         mock.patch("apps.opps.drive_client.get_drive_client") as get_drive, \
         mock.patch("apps.canopy.run_dispatch.start_turn") as start:
        with pytest.raises(run_starter.RunRequesterRefused):
            run_starter.start_run_from_slack(
                slug_or_link="idea: a new thing", user=user, workspace=ws,
            )
    get_drive.assert_not_called()  # refused before Drive is even touched
    start.assert_not_called()
    _assert_nothing_minted(ws)


@override_settings(**CANOPY_ON)
def test_an_unreachable_canopy_refuses_with_the_unverified_message():
    from apps.canopy.client import CanopyError

    user, ws = _fixture()
    with mock.patch("apps.canopy.client.act_as", side_effect=CanopyError(503, "down")), \
         mock.patch("apps.canopy.run_dispatch.start_turn") as start:
        with pytest.raises(run_starter.RunRequesterRefused) as exc:
            run_starter.start_run_from_slack(slug_or_link="opp-a", user=user, workspace=ws)

    start.assert_not_called()
    _assert_nothing_minted(ws)
    assert exc.value.code == "run_actor_unverified"
    msg = str(exc.value)
    assert "slacker@dimagi.com" in msg and "503" in msg
    assert "couldn't check" in msg and "Nothing was created" in msg


@override_settings(**CANOPY_ON)
def test_a_canopy_user_requester_runs_as_before():
    user, ws = _fixture()
    with mock.patch("apps.canopy.client.act_as", return_value=_Principal(False)), \
         mock.patch("apps.canopy.run_dispatch.start_turn") as start:
        slug, run_id = run_starter.start_run_from_slack(
            slug_or_link="opp-a", user=user, workspace=ws,
        )
    session = Session.objects.get(opp_slug="opp-a", opp_run_id=run_id)
    assistant = Message.objects.get(session=session, role="assistant")
    start.assert_called_once_with(assistant.id)  # no actor: the requester owns the run
    assert session.owner == user


@override_settings(**CANOPY_ON)
def test_the_slash_command_replies_with_the_refusal_and_opens_no_thread():
    """End to end through `/ace run`: the requester sees why, ephemerally, and
    no parent card is posted, no SlackRunThread is created."""
    from apps.slack.models import SlackInstallation, SlackRunThread, SlackUserLink
    from apps.slack.verbs_run import handle_run

    user, ws = _fixture()
    inst = SlackInstallation.objects.create(
        slack_team_id="T1", slack_team_name="Dimagi",
        bot_user_id="U_BOT", ace_workspace=ws, installed_by_user=user,
    )
    link = SlackUserLink.objects.create(
        installation=inst, slack_user_id="U_S", ace_user=user,
        slack_email=user.email, slack_real_name="S",
    )
    with mock.patch("apps.canopy.client.act_as", return_value=_Principal(True)), \
         mock.patch("apps.slack.verbs_run._get_client") as get_client:
        resp = handle_run(
            installation=inst, user_link=link, rest="opp-a",
            channel_id="C1", trigger_id="tg",
        )

    assert resp["response_type"] == "ephemeral"
    assert resp["text"].startswith(":x: ")
    assert "contact" in resp["text"] and user.email in resp["text"]
    get_client.return_value.post_message.assert_not_called()
    assert not SlackRunThread.objects.exists()
    _assert_nothing_minted(ws)
