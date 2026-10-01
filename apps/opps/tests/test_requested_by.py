"""Run attribution (`requested_by`) and the run-actor preflight.

Observed case: spark-facilitator/20261001-2208 (canopy turn 2727e227).
Jonathan asked his own Claude Code session for a seeded run; it called
`actions/seeded-run` with ACE's bot token, so:

* every record said ace@dimagi-ai.com started it and nothing said Jonathan
  asked — fixed by `requested_by` (attribution beside the truthful
  `initiated_by`);
* canopy resolved ace@ as a CONTACT, confined the turn to ask-only, and the run
  sat at Phase 3 `pending` forever behind a 202 — fixed by resolving the
  owner's canopy principal BEFORE forking and refusing with 409.
"""
from __future__ import annotations

import datetime as dt
from unittest import mock

import pytest
import yaml
from django.contrib.auth import get_user_model
from django.test import Client, override_settings

from apps.canopy import client as canopy_client
from apps.canopy import run_dispatch
from apps.opps import attribution
from apps.opps.opp_forker import ForkOppResult, fork_opp
from apps.sessions.models import Message, Session
from apps.workspaces.models import Workspace, WorkspaceMembership

User = get_user_model()

AGENT = "ace@dimagi-ai.com"
HUMAN = "jjackson@dimagi.com"

CANOPY_ON = dict(
    CANOPY_BASE_URL="http://canopy.test",
    CANOPY_SIGNING_KEY="test-key",
    CANOPY_WORKSPACE="connect",
    CANOPY_AGENT_SLUG="ace",
    CANOPY_RUN_EXECUTION=True,
)

SEEDED = "/api/w/ws1/opps/opp-1/actions/seeded-run"
FORK = "/api/w/ws1/opps/opp-1/fork"


# --- fixtures -----------------------------------------------------------------


@pytest.fixture
def workspace(db):
    return Workspace.objects.create(
        slug="ws1", display_name="WS1", drive_root_folder_id="folder-1",
        created_by=User.objects.create_user(email="creator@example.com"),
    )


def _client_for(workspace, email) -> tuple[Client, object]:
    user = User.objects.create_user(email=email)
    WorkspaceMembership.objects.create(workspace=workspace, user=user, role="editor")
    c = Client()
    c.force_login(user)
    return c, user


@pytest.fixture
def human(workspace):
    return _client_for(workspace, HUMAN)


@pytest.fixture
def agent(workspace):
    return _client_for(workspace, AGENT)


@pytest.fixture
def fake_seed_env(monkeypatch):
    """Real `seed_run_for_opp`, with Drive, the forker and the turn launch stubbed.
    Returns the dict the fake fork records its kwargs into (empty ⇒ never forked)."""
    forked: dict = {}

    def _fake_fork(**kwargs):
        forked.update(kwargs)
        return ForkOppResult(
            opp_slug=kwargs["source_slug"], new_run_id="20261001-2208",
            new_run_folder_id="folder-new", working_session=None,
        )

    monkeypatch.setattr("apps.opps.access.resolve_ace_root_folder_id", lambda ws: "ace-root")
    monkeypatch.setattr("apps.opps.drive_client.get_drive_client", lambda workspace: object())
    monkeypatch.setattr("apps.opps.opp_forker.fork_opp", _fake_fork)
    monkeypatch.setattr(
        "apps.opps.skills.all_phases", lambda: [f"p{i}" for i in range(1, 11)],
    )
    monkeypatch.setattr("apps.opps.api.nova_preflight", lambda *a: None)
    started: list = []
    monkeypatch.setattr("apps.canopy.run_dispatch.start_turn", lambda mid: started.append(mid))
    forked["_started"] = started
    return forked


def _seed(c, **body):
    return c.post(
        SEEDED,
        data={"golden_run_id": "20260926-1800", "only": "3,4,5", **body},
        content_type="application/json",
    )


# --- resolve_requested_by: the rules --------------------------------------------


@pytest.mark.django_db
def test_a_human_defaults_to_themselves():
    u = User.objects.create_user(email=HUMAN)
    assert attribution.resolve_requested_by(u, None) == HUMAN


@pytest.mark.django_db
def test_a_human_naming_themselves_is_fine_case_insensitively():
    u = User.objects.create_user(email=HUMAN)
    assert attribution.resolve_requested_by(u, "JJackson@Dimagi.com") == HUMAN


@pytest.mark.django_db
def test_a_human_cannot_attribute_a_run_to_someone_else():
    u = User.objects.create_user(email=HUMAN)
    with pytest.raises(attribution.RequestedByForbidden):
        attribution.resolve_requested_by(u, "someone@dimagi.com")


@pytest.mark.django_db
def test_an_agent_identity_is_honoured_and_records_nothing_when_absent():
    bot = User.objects.create_user(email=AGENT)
    assert attribution.is_agent_identity(bot)
    assert attribution.resolve_requested_by(bot, HUMAN) == HUMAN
    assert attribution.resolve_requested_by(bot, None) is None


@pytest.mark.django_db
@override_settings(ACE_AGENT_IDENTITIES=["other-bot@dimagi-ai.com"])
def test_agent_identities_come_from_settings():
    bot = User.objects.create_user(email=AGENT)
    assert not attribution.is_agent_identity(bot)
    with pytest.raises(attribution.RequestedByForbidden):
        attribution.resolve_requested_by(bot, HUMAN)


def test_creator_label_prefers_the_human_marked_via_ace():
    label = attribution.creator_label
    assert label({"initiated_by": AGENT, "requested_by": HUMAN}) == f"{HUMAN} (via ACE)"
    assert label({"initiated_by": HUMAN, "requested_by": HUMAN}) == HUMAN
    assert label({"initiated_by": AGENT}) == AGENT
    assert label({"created_by": "legacy@x.org", "requested_by": HUMAN}) == "legacy@x.org"
    assert label(None) is None


# --- seeded-run: request/response -------------------------------------------------


@pytest.mark.django_db
def test_seeded_run_agent_with_requested_by_records_it_everywhere(agent, fake_seed_env):
    c, _ = agent
    r = _seed(c, requested_by=HUMAN)
    assert r.status_code == 202, r.content
    body = r.json()
    assert body["initiated_by"] == AGENT
    assert body["requested_by"] == HUMAN
    # into the fork (→ run_state.yaml) …
    assert fake_seed_env["requested_by"] == HUMAN
    # … and onto the Session + its title.
    s = Session.objects.get(slug=body["session_slug"])
    assert s.owner.email == AGENT  # initiated_by stays the authenticated actor
    assert s.requested_by == HUMAN
    assert s.title.endswith(f"— requested by {HUMAN}")
    assert fake_seed_env["_started"] == [body["assistant_message_id"]]


@pytest.mark.django_db
def test_seeded_run_agent_without_requested_by_records_nothing(agent, fake_seed_env):
    c, _ = agent
    r = _seed(c)
    assert r.status_code == 202, r.content
    assert r.json()["requested_by"] is None
    assert fake_seed_env["requested_by"] is None
    s = Session.objects.get(slug=r.json()["session_slug"])
    assert s.requested_by == ""
    assert "requested by" not in s.title


@pytest.mark.django_db
def test_seeded_run_human_defaults_requested_by_to_themselves(human, fake_seed_env):
    c, _ = human
    r = _seed(c)
    assert r.status_code == 202, r.content
    assert r.json()["initiated_by"] == HUMAN
    assert r.json()["requested_by"] == HUMAN


@pytest.mark.django_db
def test_seeded_run_human_naming_someone_else_is_400_and_mints_nothing(human, fake_seed_env):
    c, _ = human
    r = _seed(c, requested_by="someone@dimagi.com")
    assert r.status_code == 400
    assert r.json()["extras"]["code"] == "requested_by_forbidden"
    assert "requested_by" not in fake_seed_env  # never forked
    assert fake_seed_env["_started"] == []
    assert not Session.objects.exists()


@pytest.mark.django_db
def test_seeded_run_rejects_a_non_email_requested_by(agent, fake_seed_env):
    c, _ = agent
    assert _seed(c, requested_by="not-an-email").status_code == 422


# --- seeded-run: the contact preflight ----------------------------------------


@pytest.mark.django_db
@override_settings(**CANOPY_ON)
def test_seeded_run_409_when_canopy_resolves_the_owner_as_a_contact(agent, fake_seed_env):
    """The observed incident: ace@ resolved as a contact. Refuse BEFORE the
    fork — no Drive run, no Session, no turn."""
    c, _ = agent
    with mock.patch("apps.canopy.client.visitor_token",
                    return_value={"token": "ct", "kind": "contact"}):
        r = _seed(c, requested_by=HUMAN)
    assert r.status_code == 409, r.content
    problem = r.json()
    assert problem["extras"]["code"] == "run_actor_unresolvable"
    assert problem["extras"]["email"] == AGENT
    assert AGENT in problem["detail"] and "ask-only" in problem["detail"]
    assert "requested_by" not in fake_seed_env  # fork_opp never called
    assert fake_seed_env["_started"] == []
    assert not Session.objects.exists()


@pytest.mark.django_db
@override_settings(**CANOPY_ON)
def test_seeded_run_proceeds_when_canopy_resolves_the_owner_as_a_user(agent, fake_seed_env):
    c, _ = agent
    with mock.patch("apps.canopy.client.visitor_token",
                    return_value={"token": "ut", "kind": "user"}):
        r = _seed(c, requested_by=HUMAN)
    assert r.status_code == 202, r.content
    assert fake_seed_env["requested_by"] == HUMAN


@pytest.mark.django_db
@override_settings(**CANOPY_ON)
def test_seeded_run_502_when_canopy_cannot_be_asked(agent, fake_seed_env):
    c, _ = agent
    with mock.patch("apps.canopy.client.visitor_token",
                    side_effect=canopy_client.CanopyError(502, "down")):
        r = _seed(c)
    assert r.status_code == 502
    assert r.json()["extras"]["code"] == "run_actor_unverified"
    assert "requested_by" not in fake_seed_env


@pytest.mark.django_db
def test_preflight_is_a_noop_when_run_execution_is_off(agent, fake_seed_env):
    """Legacy subprocess path: canopy is not consulted at all."""
    c, _ = agent
    with mock.patch("apps.canopy.client.visitor_token") as vt:
        r = _seed(c)
    assert r.status_code == 202
    vt.assert_not_called()


@pytest.mark.django_db
@override_settings(**CANOPY_ON)
def test_workbench_chat_for_a_contact_is_unaffected(workspace):
    """External reviewers chat as contacts; the run-actor gate must not touch
    the chat path even with run execution ON."""
    c, _ = _client_for(workspace, "reviewer@partner.org")
    with (
        mock.patch("apps.canopy.client.visitor_token",
                   return_value={"token": "ct", "expires_at": "x", "kind": "contact"}),
        mock.patch("apps.canopy.client.create_contact_session",
                   return_value={"id": "c1"}) as cs,
    ):
        r = c.post("/api/w/ws1/canopy/sessions",
                   data={"title": "T", "opp_slug": "opp-1"}, content_type="application/json")
        tok = c.post("/api/canopy/token")
    assert r.status_code == 200 and r.json()["id"] == "c1"
    cs.assert_called_once()
    assert tok.status_code == 200 and tok.json()["kind"] == "contact"


# --- persistence: run_state.yaml, the working session, canopy ----------------------


def _fork_drive():
    from apps.opps.tests.test_fork_run_state_first import _build_drive

    drive = _build_drive(call_log=[])
    uploads: dict = {}
    original = drive.upload_file.side_effect

    def _upload(parent, name, body, mime):
        uploads[name] = body
        return original(parent, name, body, mime)

    drive.upload_file.side_effect = _upload
    return drive, uploads


@pytest.mark.django_db
@pytest.mark.parametrize("requested_by", [HUMAN, None])
def test_fork_writes_requested_by_into_run_state_and_the_working_session(requested_by):
    owner = User.objects.create_user(email=AGENT)
    drive, uploads = _fork_drive()
    result = fork_opp(
        drive=drive, ace_root_folder_id="ace-root", owner=owner, source_slug="src-opp",
        fork_at_phase="commcare-setup", source_run_id="20260101-1000", workspace=None,
        now=dt.datetime(2026, 10, 1, 22, 8, tzinfo=dt.UTC), requested_by=requested_by,
    )
    state = yaml.safe_load(uploads["run_state.yaml"])
    assert state["initiated_by"] == AGENT
    assert state["last_actor"] == AGENT
    if requested_by:
        assert state["requested_by"] == HUMAN
    else:
        assert "requested_by" not in state  # nothing recorded rather than a guess
    assert result.working_session.requested_by == (requested_by or "")


@pytest.mark.django_db
def test_canopy_session_title_and_metadata_carry_requested_by():
    owner = User.objects.create_user(email=AGENT)
    session = Session.create_with_owner(
        owner=owner, title=f"seeded-run: opp-a/run-1 (--only 3) — requested by {HUMAN}",
        backend_kind="cli", status="active", source="web",
        opp_slug="opp-a", opp_run_id="run-1", requested_by=HUMAN,
    )
    Message.objects.create(session=session, turn_index=0, role="user", sender_user=owner,
                           content={"text": "/ace:run opp-a/run-1"},
                           plaintext="/ace:run opp-a/run-1", status="complete")
    assistant = Message.objects.create(session=session, turn_index=1, role="assistant",
                                       content={"text": ""}, status="pending")
    with (
        override_settings(**CANOPY_ON),
        mock.patch("apps.canopy.client.visitor_token",
                   return_value={"token": "ut", "kind": "user"}),
        mock.patch.object(canopy_client.Principal, "create_session",
                          return_value={"id": "sess-9"}) as create,
        mock.patch.object(canopy_client.Principal, "send",
                          return_value={"turn_id": "turn-9"}),
    ):
        run_dispatch.dispatch_turn(assistant.id)
    kwargs = create.call_args.kwargs
    assert kwargs["title"].endswith(f"— requested by {HUMAN}")
    assert kwargs["metadata"]["requested_by"] == HUMAN


# --- fork endpoint ---------------------------------------------------------------


@pytest.fixture
def fake_fork_env(monkeypatch):
    forked: dict = {}

    def _fake_fork(**kwargs):
        forked.update(kwargs)
        return ForkOppResult(
            opp_slug=kwargs["source_slug"], new_run_id="20261001-2210",
            new_run_folder_id="folder-new", working_session=mock.Mock(slug="ws-sess"),
        )

    monkeypatch.setattr("apps.opps.access.resolve_ace_root_folder_id", lambda ws: "ace-root")
    monkeypatch.setattr("apps.opps.drive_client.get_drive_client", lambda workspace: object())
    monkeypatch.setattr("apps.opps.opp_forker.fork_opp", _fake_fork)
    return forked


def _fork_post(c, **body):
    return c.post(FORK, data={"fork_at_phase": "commcare-setup", **body},
                  content_type="application/json")


@pytest.mark.django_db
def test_fork_agent_passes_requested_by_through(agent, fake_fork_env):
    c, _ = agent
    r = _fork_post(c, requested_by=HUMAN)
    assert r.status_code == 201, r.content
    assert r.json()["initiated_by"] == AGENT
    assert r.json()["requested_by"] == HUMAN
    assert fake_fork_env["requested_by"] == HUMAN


@pytest.mark.django_db
def test_fork_human_defaults_and_cannot_name_someone_else(human, fake_fork_env):
    c, _ = human
    r = _fork_post(c)
    assert r.status_code == 201
    assert r.json()["requested_by"] == HUMAN
    fake_fork_env.clear()
    r = _fork_post(c, requested_by="someone@dimagi.com")
    assert r.status_code == 400
    assert r.json()["extras"]["code"] == "requested_by_forbidden"
    assert fake_fork_env == {}  # never forked
