"""Tests for GET /api/opps/ — the opportunity list endpoint."""
from unittest.mock import patch

import pytest
from django.test import Client

from apps.auth.models import User
from apps.opps.tests.fixtures.fake_drive import (
    FakeDriveClient,
    malaria_pilot_structured_tree,
    nutrition_legacy_flat_tree,
    web_created_opp_tree,
)


@pytest.fixture
def authed_user(db):
    u = User.objects.create(email="jon@dimagi.com", display_name="Jon")
    return u


@pytest.fixture
def authed_client(authed_user):
    c = Client()
    c.force_login(authed_user)
    return c


def _combined_tree() -> dict:
    """Both fixtures under one ACE folder, to verify the list endpoint returns both."""
    return {
        "ACE": {
            **malaria_pilot_structured_tree()["ACE"],
            **nutrition_legacy_flat_tree()["ACE"],
        }
    }


def test_opp_list_returns_both_opps(authed_client):
    fake = FakeDriveClient.from_tree(_combined_tree())
    with patch("apps.opps.views.get_drive_client", return_value=fake), \
         patch("apps.opps.views._resolve_ace_root_folder_id",
               return_value=fake.folder_id("ACE")):
        response = authed_client.get("/api/opps/")
    assert response.status_code == 200
    body = response.json()
    assert body["error"] is None
    cards = body["data"]
    slugs = {c["slug"] for c in cards}
    assert slugs == {"malaria-pilot", "nutrition-legacy"}


def test_opp_list_malaria_card_fields(authed_client):
    fake = FakeDriveClient.from_tree(_combined_tree())
    with patch("apps.opps.views.get_drive_client", return_value=fake), \
         patch("apps.opps.views._resolve_ace_root_folder_id",
               return_value=fake.folder_id("ACE")):
        response = authed_client.get("/api/opps/")
    cards = response.json()["data"]
    malaria = next(c for c in cards if c["slug"] == "malaria-pilot")
    assert malaria["display_name"] == "Malaria Pilot — Northern Mozambique"
    # Flat layout synthesizes run_id "r1".
    assert malaria["current_run_id"] == "r1"


def test_opp_list_drive_not_configured_returns_500(authed_client):
    from apps.service_accounts.exceptions import ServiceAccountNotFound
    with patch(
        "apps.opps.drive_client.registry.get_credentials",
        side_effect=ServiceAccountNotFound("ace-drive not found"),
    ):
        response = authed_client.get("/api/opps/")
    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "drive-not-configured"


def test_opp_list_unauthenticated_returns_401():
    c = Client()
    response = c.get("/api/opps/")
    assert response.status_code == 401


def test_opp_list_includes_web_created_opps(authed_client):
    """POST /api/opps/ writes idea.md + runs/run-001/state.yaml. The list
    endpoint used to require state.yaml + pdd.md at root, so newly-created
    opps were invisible despite rendering fine at /opps/<slug>. The new
    layout check accepts (idea.md + runs/) too."""
    fake = FakeDriveClient.from_tree(web_created_opp_tree())
    with patch("apps.opps.views.get_drive_client", return_value=fake), \
         patch("apps.opps.views._resolve_ace_root_folder_id",
               return_value=fake.folder_id("ACE")):
        response = authed_client.get("/api/opps/")
    assert response.status_code == 200
    cards = response.json()["data"]
    assert {c["slug"] for c in cards} == {"turmeric-smoketest-20260418-1114"}


def test_opp_list_skips_non_opp_folders(authed_client):
    """Folders under ACE/ that aren't opps (e.g. `Program Design Docs (PDDs)`)
    must not show up as opps in the list."""
    tree = {
        "ACE": {
            "Program Design Docs (PDDs)": {
                "turmeric-v1.md": "PDD body",
                "malaria.md": "other PDD",
            },
            **web_created_opp_tree()["ACE"],
        }
    }
    fake = FakeDriveClient.from_tree(tree)
    with patch("apps.opps.views.get_drive_client", return_value=fake), \
         patch("apps.opps.views._resolve_ace_root_folder_id",
               return_value=fake.folder_id("ACE")):
        response = authed_client.get("/api/opps/")
    cards = response.json()["data"]
    assert {c["slug"] for c in cards} == {"turmeric-smoketest-20260418-1114"}


def test_opp_list_includes_flat_idea_only_opp(authed_client):
    """New flat layout (2026-04-20): opp folder contains just idea.md
    (optionally pdd.md) at the root — no runs/ subfolder, no state.yaml.
    /ace:run initializes state.yaml itself when the lifecycle starts.
    List view must recognize these. Regression test for the bug where
    a flat idea.md-only opp created by opp_creator was invisible in /opps.
    """
    tree = {"ACE": {"flat-only": {"idea.md": "the idea body"}}}
    fake = FakeDriveClient.from_tree(tree)
    with patch("apps.opps.views.get_drive_client", return_value=fake), \
         patch("apps.opps.views._resolve_ace_root_folder_id",
               return_value=fake.folder_id("ACE")):
        response = authed_client.get("/api/opps/")
    assert response.status_code == 200
    cards = response.json()["data"]
    assert {c["slug"] for c in cards} == {"flat-only"}


def test_opp_list_overlays_workspace_display_name(authed_client, authed_user):
    """display_name now lives on the OppWorkspace DB row (not in a Drive
    state.yaml). The list view layers the DB display_name over the
    Drive-derived manifest so cards show the human-readable name.

    Regression test for the Task 5 side effect where display_name
    defaulted to slug everywhere after the Drive write was dropped.
    """
    from apps.opps.models import OppWorkspace
    OppWorkspace.objects.create(
        slug="flat-only",
        display_name="Pretty Name",
        created_by=authed_user,
    )
    tree = {"ACE": {"flat-only": {"idea.md": "idea"}}}
    fake = FakeDriveClient.from_tree(tree)
    with patch("apps.opps.views.get_drive_client", return_value=fake), \
         patch("apps.opps.views._resolve_ace_root_folder_id",
               return_value=fake.folder_id("ACE")):
        response = authed_client.get("/api/opps/")
    cards = response.json()["data"]
    card = next(c for c in cards if c["slug"] == "flat-only")
    assert card["display_name"] == "Pretty Name"


def test_opp_list_returns_empty_when_no_ace_root_configured(authed_client):
    """No ACE_DRIVE_ROOT_FOLDER_ID set → empty list, not a 500.

    Local-dev / e2e envs without Drive still need the page to load.
    """
    fake = FakeDriveClient.from_tree({})
    with patch("apps.opps.views.get_drive_client", return_value=fake), \
         patch("apps.opps.views._resolve_ace_root_folder_id", return_value=None):
        response = authed_client.get("/api/opps/")
    assert response.status_code == 200
    body = response.json()
    assert body["error"] is None
    assert body["data"] == []


class _CountingDriveClient:
    """Wrap a FakeDriveClient to count Drive calls. The list endpoint used
    to call the full ``load_opp`` per opp (recursive tree listing + N
    verdict reads + artifact manifest matching), which on real Drive took
    ~3.5 s per opp — observed 14 s for four opps on labs 2026-04-21. The
    list view now uses a card-only loader; this test pins the new budget
    so we don't silently regress.
    """
    def __init__(self, inner):
        self._inner = inner
        self.list_files_calls: list[tuple[str, bool]] = []
        self.recursive_list_calls = 0
        self.get_content_calls: list[str] = []

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def list_files(self, folder_id, recursive=False, page_size=100):
        self.list_files_calls.append((folder_id, recursive))
        if recursive:
            self.recursive_list_calls += 1
        return self._inner.list_files(folder_id, recursive=recursive, page_size=page_size)

    def get_content(self, file_id, mime_type):
        self.get_content_calls.append(file_id)
        return self._inner.get_content(file_id, mime_type)


def test_opp_list_drive_call_budget(authed_client):
    """List endpoint must stay O(N) on Drive calls, not O(N · per-opp-work).

    Budget for N opps in the ACE root:
      - 1 ``list_files`` on the ACE root (to discover opp folders)
      - 1 ``list_files`` per opp folder (for the idea.md/state.yaml signal
        check — already performed by the view and reused by load_opp_card)
      - 0 recursive listings (load_opp's ``list_files(recursive=True)``
        must NOT fire from the list path)
      - At most 1 ``get_content`` per opp (state.yaml only; skipped if the
        opp folder doesn't have one)

    Total: ≤ 2N + 1 list_files, ≤ N get_content, 0 recursive.

    Regression test for a 14-second list response observed on labs
    (4 opps × ~3.5 s/opp via full load_opp). If this test fails because
    you added a new per-opp Drive read, add a matching entry to
    ``load_opp_card`` in ``apps/opps/sync.py`` instead — don't reach back
    into ``load_opp``.
    """
    fake = FakeDriveClient.from_tree(_combined_tree())
    counting = _CountingDriveClient(fake)
    with patch("apps.opps.views.get_drive_client", return_value=counting), \
         patch("apps.opps.views._resolve_ace_root_folder_id",
               return_value=fake.folder_id("ACE")):
        response = authed_client.get("/api/opps/")
    assert response.status_code == 200
    # Two opps in the combined tree.
    n_opps = 2
    assert counting.recursive_list_calls == 0, (
        f"List endpoint made {counting.recursive_list_calls} recursive Drive "
        f"listings — load_opp's recursive scan is back in the list path."
    )
    assert len(counting.list_files_calls) <= 2 * n_opps + 1, (
        f"List endpoint made {len(counting.list_files_calls)} list_files "
        f"calls for {n_opps} opps — budget is 2N+1."
    )
    assert len(counting.get_content_calls) <= n_opps, (
        f"List endpoint made {len(counting.get_content_calls)} get_content "
        f"calls for {n_opps} opps — budget is N (state.yaml each)."
    )
