"""A resume runs as the person who clicked it; the post-deploy sweep runs as the owner.

The gap: `POST /w/{ws}/sessions/{slug}/resume` is open to every workspace
member, and its turn was dispatched to canopy AS THE SESSION OWNER. So a member
could make any run execute with its owner's authority — and since canopy-web#1044
resolves ACE's own login (ace@dimagi-ai.com) to the agent itself, a member
resuming an ace@-owned run got ACE's full authority. Partner workspaces hold
external reviewers as members, so this reached outsiders.

canopy is mocked at `client.act_as`: every principal ace-web acts as is recorded
with the calls made through it, so each test asserts WHO did WHAT in canopy.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.test import Client, override_settings
from django.utils import timezone

from apps.canopy import client as canopy_client
from apps.sessions.models import Message, Session
from apps.workspaces.models import Workspace, WorkspaceMembership

User = get_user_model()
pytestmark = pytest.mark.django_db

AGENT = "ace@dimagi-ai.com"
OWNER = "jjackson@dimagi.com"
MEMBER = "reviewer@partner.org"

CANOPY_ON = dict(
    CANOPY_BASE_URL="http://canopy.test",
    CANOPY_SIGNING_KEY="test-key",
    CANOPY_WORKSPACE="connect",
    CANOPY_AGENT_SLUG="ace",
    CANOPY_RUN_EXECUTION=True,
)


class _Canopy:
    """A fake canopy: `act_as(email)` hands back a principal that logs every call
    as (email, verb, session_id). `contacts` resolve as contacts."""

    def __init__(self, contacts=()):
        self.calls: list[tuple[str, str, str]] = []
        self.created: list[dict] = []
        self.contacts = {c.lower() for c in contacts}

    def act_as(self, email):
        canopy = self

        class _Principal:
            is_contact = email.lower() in canopy.contacts

            def create_session(self, *, title, metadata):
                sid = f"sess-{email}"
                canopy.calls.append((email, "create", sid))
                canopy.created.append({"email": email, "title": title, "metadata": metadata})
                return {"id": sid}

            def send(self, session_id, *, text, client_id):
                canopy.calls.append((email, "send", session_id))
                return {"turn_id": f"turn-{email}"}

            def stop(self, session_id):
                canopy.calls.append((email, "stop", session_id))
                return {"cancelled": 1}

        return _Principal()

    def by(self, verb):
        return [(e, sid) for e, v, sid in self.calls if v == verb]


@pytest.fixture
def canopy(monkeypatch):
    fake = _Canopy()
    monkeypatch.setattr(canopy_client, "act_as", fake.act_as)
    return fake


@pytest.fixture
def workspace(db):
    return Workspace.objects.create(
        slug="ws1", display_name="WS1", drive_root_folder_id="folder-1",
        created_by=User.objects.create_user(email="creator@example.com"),
    )


def _member(workspace, email, role="editor"):
    user = User.objects.filter(email=email).first() or User.objects.create_user(email=email)
    WorkspaceMembership.objects.get_or_create(
        workspace=workspace, user=user, defaults={"role": role},
    )
    return user


def _client(user) -> Client:
    c = Client()
    c.force_login(user)
    return c


def _dead_run(workspace, owner, *, canopy_session_id="sess-owner", run_id="20261001-0900"):
    """A canopy-dispatched run whose last turn died (hard kill shape)."""
    s = Session.create_with_owner(
        owner=owner, workspace=workspace, source="web", title="seeded-run: opp-1",
        opp_slug="opp-1", opp_run_id=run_id, canopy_session_id=canopy_session_id,
        driver_heartbeat_at=timezone.now() - timedelta(seconds=300),
    )
    Message.objects.create(
        session=s, turn_index=0, role="user", sender_user=owner,
        content={"text": "/ace:run opp-1"}, plaintext="/ace:run opp-1", status="complete",
    )
    dead = Message.objects.create(
        session=s, turn_index=1, role="assistant", status="streaming", content={},
        canopy_turn_id="turn-dead",
    )
    return s, dead


def _resume(user, session):
    return _client(user).post(f"/api/w/{session.workspace.slug}/sessions/{session.slug}/resume")


@override_settings(**CANOPY_ON)
def test_a_member_resuming_an_ace_owned_run_dispatches_as_the_member(workspace, canopy):
    ace = _member(workspace, AGENT)
    member = _member(workspace, MEMBER)
    session, _ = _dead_run(workspace, ace)

    resp = _resume(member, session)

    assert resp.status_code == 202, resp.content
    # The turn is SENT as the member, into a canopy session the member created —
    # never into ace@'s session, where canopy would run it in ACE's full profile.
    assert canopy.by("send") == [(MEMBER, f"sess-{MEMBER}")]
    assert canopy.by("create") == [(MEMBER, f"sess-{MEMBER}")]
    # ace@'s dead turn is retired as ace@ (a stop, not a send).
    assert (AGENT, "sess-owner") in canopy.by("stop")
    assert not [c for c in canopy.calls if c[0] == AGENT and c[1] != "stop"]
    created = canopy.created[0]
    assert created["metadata"]["requested_by"] == MEMBER
    assert MEMBER in created["title"]

    resume_turn = Message.objects.get(session=session, role="user", turn_index=2)
    assert resume_turn.sender_user == member
    session.refresh_from_db()
    assert session.canopy_session_id == f"sess-{MEMBER}"
    assert session.canopy_session_actor == MEMBER


@override_settings(**CANOPY_ON)
def test_a_member_resuming_another_humans_run_dispatches_as_the_member(workspace, canopy):
    owner = _member(workspace, OWNER, role="owner")
    member = _member(workspace, MEMBER)
    session, _ = _dead_run(workspace, owner)

    resp = _resume(member, session)

    assert resp.status_code == 202, resp.content
    senders = {email for email, _sid in canopy.by("send")}
    assert senders == {MEMBER}
    assert OWNER not in {e for e, v, _ in canopy.calls if v in ("send", "create")}
    assert Message.objects.get(session=session, role="user", turn_index=2).sender_user == member


@override_settings(**CANOPY_ON)
def test_the_owner_resuming_their_own_run_reuses_their_canopy_session(workspace, canopy):
    owner = _member(workspace, OWNER, role="owner")
    session, _ = _dead_run(workspace, owner)

    resp = _resume(owner, session)

    assert resp.status_code == 202, resp.content
    assert canopy.by("create") == []
    assert canopy.by("stop") == [(OWNER, "sess-owner")]
    assert canopy.by("send") == [(OWNER, "sess-owner")]
    session.refresh_from_db()
    assert session.canopy_session_actor == ""


@override_settings(**CANOPY_ON)
def test_a_clicker_canopy_knows_only_as_a_contact_is_refused_before_anything_is_written(
    workspace, monkeypatch,
):
    fake = _Canopy(contacts={MEMBER})
    monkeypatch.setattr(canopy_client, "act_as", fake.act_as)
    ace = _member(workspace, AGENT)
    member = _member(workspace, MEMBER)
    session, dead = _dead_run(workspace, ace)
    before = list(Message.objects.filter(session=session).values_list("pk", flat=True))

    resp = _resume(member, session)

    assert resp.status_code == 409
    body = resp.json()
    assert body["extras"]["code"] == "run_actor_unresolvable"
    assert body["extras"]["email"] == MEMBER
    # No turn appended, the dead turn not retired, nothing sent or stopped.
    assert list(Message.objects.filter(session=session).values_list("pk", flat=True)) == before
    dead.refresh_from_db()
    assert dead.status == "streaming"
    assert not dead.error_detail
    assert [v for _e, v, _s in fake.calls] == []


@override_settings(**CANOPY_ON)
def test_an_unreachable_canopy_is_a_502_and_writes_nothing(workspace, monkeypatch):
    def _down(email):
        raise canopy_client.CanopyError(503, "down")

    monkeypatch.setattr(canopy_client, "act_as", _down)
    ace = _member(workspace, AGENT)
    member = _member(workspace, MEMBER)
    session, _ = _dead_run(workspace, ace)

    resp = _resume(member, session)

    assert resp.status_code == 502
    assert resp.json()["extras"]["code"] == "run_actor_unverified"
    assert Message.objects.filter(session=session).count() == 2


@override_settings(**CANOPY_ON)
def test_the_post_deploy_sweep_still_dispatches_as_the_owner(workspace, canopy, monkeypatch):
    """Nobody clicked: the sweep continues a run its owner started, so the turn
    runs as the owner even though another identity (the deploy caller) made the
    HTTP call. Only the system caller may make it — see
    tests/test_resume_sweep_authority.py for the member refusal."""
    owner = _member(workspace, OWNER, role="owner")
    deployer = _member(workspace, "deploy@dimagi.com", role="owner")
    # Never dispatched to canopy (no canopy_session_id) → the sweep does not
    # consult canopy for liveness, it just resumes.
    session, _ = _dead_run(workspace, owner, canopy_session_id="")

    resp = _client(deployer).post(f"/api/w/{workspace.slug}/sessions/resume-interrupted")

    assert resp.status_code == 200, resp.content
    assert resp.json()["count"] == 1
    assert canopy.by("send") == [(OWNER, f"sess-{OWNER}")]
    assert Message.objects.get(session=session, role="user", turn_index=2).sender_user == owner


@override_settings(**CANOPY_ON)
def test_the_sweep_after_a_member_resume_takes_the_run_back_to_the_owner(workspace, canopy):
    """A member resumed (their canopy session holds the run); the deploy then
    killed it. The owner-run sweep must not send into the member's session — it
    stops it as the member and starts the turn in a session of the owner's."""
    from apps.canopy import run_dispatch

    owner = _member(workspace, OWNER, role="owner")
    session, _ = _dead_run(workspace, owner, canopy_session_id=f"sess-{MEMBER}")
    Session.objects.filter(pk=session.pk).update(canopy_session_actor=MEMBER)
    assistant = Message.objects.create(
        session=session, turn_index=3, role="assistant", status="pending", content={},
    )

    run_dispatch.dispatch_turn(assistant.id)  # no actor: the sweep's call shape

    assert canopy.by("stop") == [(MEMBER, f"sess-{MEMBER}")]
    assert canopy.by("send") == [(OWNER, f"sess-{OWNER}")]
    session.refresh_from_db()
    assert session.canopy_session_id == f"sess-{OWNER}"
    assert session.canopy_session_actor == ""
