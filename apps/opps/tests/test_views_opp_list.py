"""Tests for GET /api/opps/ — the opportunity list endpoint."""
import logging
from unittest.mock import patch

import pytest
from django.test import Client

from apps.auth.models import User
from apps.opps.tests.fixtures.fake_drive import (
    FakeDriveClient,
    malaria_pilot_structured_tree,
    nutrition_legacy_flat_tree,
    opp_with_scorecard_tree,
    turmeric_multi_run_tree,
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
    with patch("apps.opps.access.get_drive_client", return_value=fake), \
         patch("apps.opps.access.resolve_ace_root_folder_id",
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
    with patch("apps.opps.access.get_drive_client", return_value=fake), \
         patch("apps.opps.access.resolve_ace_root_folder_id",
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
    with patch("apps.opps.access.get_drive_client", return_value=fake), \
         patch("apps.opps.access.resolve_ace_root_folder_id",
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
    with patch("apps.opps.access.get_drive_client", return_value=fake), \
         patch("apps.opps.access.resolve_ace_root_folder_id",
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
    with patch("apps.opps.access.get_drive_client", return_value=fake), \
         patch("apps.opps.access.resolve_ace_root_folder_id",
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
    with patch("apps.opps.access.get_drive_client", return_value=fake), \
         patch("apps.opps.access.resolve_ace_root_folder_id",
               return_value=fake.folder_id("ACE")):
        response = authed_client.get("/api/opps/")
    cards = response.json()["data"]
    card = next(c for c in cards if c["slug"] == "flat-only")
    assert card["display_name"] == "Pretty Name"


def test_opp_list_includes_multi_run_layout_opp(authed_client):
    """Multi-run-layout opps (post 2026-05-02): opp folder has opp.yaml +
    runs/<timestamp>/ but NO idea.md or state.yaml at the opp root. The list
    endpoint must still recognize them and surface latest-run phase / step /
    eval / pending-gate data on the card.
    """
    fake = FakeDriveClient.from_tree(turmeric_multi_run_tree())
    with patch("apps.opps.access.get_drive_client", return_value=fake), \
         patch("apps.opps.access.resolve_ace_root_folder_id",
               return_value=fake.folder_id("ACE")):
        response = authed_client.get("/api/opps/")
    assert response.status_code == 200
    cards = response.json()["data"]
    assert {c["slug"] for c in cards} == {"turmeric"}
    card = cards[0]
    # opp.yaml's display_name wins (no DB overlay in this test).
    assert card["display_name"] == "Turmeric Market Survey"
    # Latest run = 20260502-1830, current_phase = ocs.
    assert card["current_run_id"] == "20260502-1830"
    assert card["current_phase"] == "ocs"
    assert card["current_step"] == "ocs-agent-setup"
    assert card["status"] == "ok"
    # Two runs sit under runs/.
    assert card["run_count"] == 2
    # opp-eval-deep.yaml under the latest run's verdicts/ → eval_score
    # surfaces on the card.
    assert card["eval_score"] == 84.0
    assert card["eval_passed"] is True


def test_opp_list_returns_empty_when_no_ace_root_configured(authed_client):
    """No ACE_DRIVE_ROOT_FOLDER_ID set → empty list, not a 500.

    Local-dev / e2e envs without Drive still need the page to load.
    """
    fake = FakeDriveClient.from_tree({})
    with patch("apps.opps.access.get_drive_client", return_value=fake), \
         patch("apps.opps.access.resolve_ace_root_folder_id", return_value=None):
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
      - +1 ``list_files`` ONLY for opps that carry a ``verdicts/`` subfolder
        (so the opp-eval score chip can be surfaced on the card).
      - 0 recursive listings (load_opp's ``list_files(recursive=True)``
        must NOT fire from the list path)
      - At most 1 ``get_content`` per opp for ``state.yaml``, plus at most
        1 ``get_content`` per opp that has an ``opp-eval-*.yaml`` verdict.

    Total: ≤ (2 + V) · N + 1 list_files, ≤ (1 + V) · N get_content,
    0 recursive — where V = fraction of opps with verdicts.

    The combined tree (malaria-pilot + nutrition-legacy) has no verdicts/
    folders, so V = 0 and the budget is the original 2N+1 / N. The
    opp-eval score chip is paid per opp that has been judged, never per
    opp on the list.

    Regression test for a 14-second list response observed on labs
    (4 opps × ~3.5 s/opp via full load_opp). If this test fails because
    you added a new per-opp Drive read, add a matching entry to
    ``load_opp_card`` in ``apps/opps/sync.py`` instead — don't reach back
    into ``load_opp``.
    """
    fake = FakeDriveClient.from_tree(_combined_tree())
    counting = _CountingDriveClient(fake)
    with patch("apps.opps.access.get_drive_client", return_value=counting), \
         patch("apps.opps.access.resolve_ace_root_folder_id",
               return_value=fake.folder_id("ACE")):
        response = authed_client.get("/api/opps/")
    assert response.status_code == 200
    # Two opps in the combined tree, neither with a verdicts/ folder.
    n_opps = 2
    assert counting.recursive_list_calls == 0, (
        f"List endpoint made {counting.recursive_list_calls} recursive Drive "
        f"listings — load_opp's recursive scan is back in the list path."
    )
    assert len(counting.list_files_calls) <= 2 * n_opps + 1, (
        f"List endpoint made {len(counting.list_files_calls)} list_files "
        f"calls for {n_opps} opps (no verdicts) — budget is 2N+1."
    )
    assert len(counting.get_content_calls) <= n_opps, (
        f"List endpoint made {len(counting.get_content_calls)} get_content "
        f"calls for {n_opps} opps (no verdicts) — budget is N (state.yaml)."
    )


def test_opp_list_surfaces_opp_eval_score(authed_client):
    """An opp with verdicts/opp-eval-deep.yaml must surface eval_score +
    eval_passed on its card payload. Lets the /opps page render a score
    chip without drilling into each opp.

    Uses the canonical ``opp_with_scorecard_tree`` fixture which already
    contains a realistic opp-eval-deep.yaml (overall_score: 82, verdict:
    pass).
    """
    fake = FakeDriveClient.from_tree(opp_with_scorecard_tree())
    with patch("apps.opps.access.get_drive_client", return_value=fake), \
         patch("apps.opps.access.resolve_ace_root_folder_id",
               return_value=fake.folder_id("ACE")):
        response = authed_client.get("/api/opps/")
    cards = response.json()["data"]
    card = next(c for c in cards if c["slug"] == "cholera-smoketest")
    assert card["eval_score"] == 82.0
    assert card["eval_passed"] is True


def test_opp_list_eval_score_blank_for_unjudged_opp(authed_client):
    """An opp with no verdicts/ folder — or no opp-eval-*.yaml inside —
    must surface ``eval_score: null`` rather than crashing or making a
    spurious Drive call."""
    fake = FakeDriveClient.from_tree(_combined_tree())
    with patch("apps.opps.access.get_drive_client", return_value=fake), \
         patch("apps.opps.access.resolve_ace_root_folder_id",
               return_value=fake.folder_id("ACE")):
        response = authed_client.get("/api/opps/")
    cards = response.json()["data"]
    for card in cards:
        assert card["eval_score"] is None
        assert card["eval_passed"] is None


def test_opp_list_eval_score_prefers_deep_over_monitor_over_quick(authed_client):
    """When multiple opp-eval verdict variants coexist, deep beats
    monitor beats quick — matches the priority used by the per-step
    Workbench surface (``_load_verdicts``)."""
    tree = {
        "ACE": {
            "multi-variant-opp": {
                "idea.md": "Idea body",
                "verdicts": {
                    "opp-eval-quick.yaml": (
                        "skill: opp-eval\nmode: quick\noverall_score: 50\nverdict: fail\n"
                    ),
                    "opp-eval-monitor.yaml": (
                        "skill: opp-eval\nmode: monitor\noverall_score: 70\nverdict: pass\n"
                    ),
                    "opp-eval-deep.yaml": (
                        "skill: opp-eval\nmode: deep\noverall_score: 90\nverdict: pass\n"
                    ),
                },
            }
        }
    }
    fake = FakeDriveClient.from_tree(tree)
    with patch("apps.opps.access.get_drive_client", return_value=fake), \
         patch("apps.opps.access.resolve_ace_root_folder_id",
               return_value=fake.folder_id("ACE")):
        response = authed_client.get("/api/opps/")
    cards = response.json()["data"]
    card = next(c for c in cards if c["slug"] == "multi-variant-opp")
    assert card["eval_score"] == 90.0
    assert card["eval_passed"] is True


def test_opp_list_eval_score_tolerates_malformed_verdict(authed_client, caplog):
    """A garbage opp-eval-*.yaml must NOT 500 the list — the card surfaces
    eval_score: null and the failure is logged. The /opps page should
    stay loadable even when one opp has a corrupt verdict file."""
    tree = {
        "ACE": {
            "broken-verdict-opp": {
                "idea.md": "Idea body",
                "verdicts": {
                    # Valid YAML that's syntactically fine but missing both
                    # score keys → _parse_verdict_yaml returns a verdict
                    # with score=None, passed=None. Card surfaces them.
                    "opp-eval-deep.yaml": "skill: opp-eval\nrandom_key: 99\n",
                },
            }
        }
    }
    fake = FakeDriveClient.from_tree(tree)
    with patch("apps.opps.access.get_drive_client", return_value=fake), \
         patch("apps.opps.access.resolve_ace_root_folder_id",
               return_value=fake.folder_id("ACE")):
        response = authed_client.get("/api/opps/")
    assert response.status_code == 200
    cards = response.json()["data"]
    card = next(c for c in cards if c["slug"] == "broken-verdict-opp")
    assert card["eval_score"] is None
    assert card["eval_passed"] is None


def test_opp_list_surfaces_per_card_failures(authed_client, caplog):
    """A broken state.yaml on one opp must NOT erase that opp from the
    list, NOT erase healthy opps, AND NOT vanish silently. The failing
    opp surfaces with status='error' and a log.warning is emitted with
    a full traceback so operators can find the root cause.

    Regression test for the swallowed-exception silence in views.py.
    """
    fake = FakeDriveClient.from_tree(_combined_tree())

    real_load = __import__("apps.opps.sync", fromlist=["load_opp_card"]).load_opp_card

    def _selectively_broken(client, *, opp_folder, opp_children):
        if opp_folder.name == "malaria-pilot":
            raise RuntimeError("simulated state.yaml parse failure")
        return real_load(client, opp_folder=opp_folder, opp_children=opp_children)

    with patch("apps.opps.access.get_drive_client", return_value=fake), \
         patch("apps.opps.access.resolve_ace_root_folder_id",
               return_value=fake.folder_id("ACE")), \
         patch("apps.opps.views.load_opp_card", side_effect=_selectively_broken), \
         caplog.at_level(logging.WARNING, logger="apps.opps.views"):
        response = authed_client.get("/api/opps/")

    assert response.status_code == 200
    cards = response.json()["data"]
    by_slug = {c["slug"]: c for c in cards}

    # Healthy opp still rendered normally.
    assert by_slug["nutrition-legacy"]["status"] != "error"

    # Failing opp surfaces as an error card, not silently dropped.
    assert by_slug["malaria-pilot"]["status"] == "error"
    assert by_slug["malaria-pilot"]["error"]["message"] == (
        "simulated state.yaml parse failure"
    )

    # Operator-facing log line includes the slug AND the exception class
    # so paging through logs is productive.
    matching = [
        r for r in caplog.records
        if "opp_list" in r.getMessage() and "malaria-pilot" in r.getMessage()
    ]
    assert matching, "expected a warning log naming the failing opp"
    assert matching[0].exc_info is not None, "log line should carry traceback"


def test_list_returns_etag_header_when_flag_on(settings, authed_client):
    fake = FakeDriveClient.from_tree(_combined_tree())
    with patch("apps.opps.access.get_drive_client", return_value=fake), \
         patch("apps.opps.access.resolve_ace_root_folder_id",
               return_value=fake.folder_id("ACE")):
        resp = authed_client.get("/api/opps/")
    assert resp.status_code == 200
    assert resp.headers.get("ETag", "").startswith("sha256:")


def test_list_returns_304_when_unchanged(settings, authed_client):
    fake = FakeDriveClient.from_tree(_combined_tree())
    with patch("apps.opps.access.get_drive_client", return_value=fake), \
         patch("apps.opps.access.resolve_ace_root_folder_id",
               return_value=fake.folder_id("ACE")):
        first = authed_client.get("/api/opps/")
        etag = first.headers["ETag"]
        second = authed_client.get("/api/opps/", HTTP_IF_NONE_MATCH=etag)
    assert second.status_code == 304


def test_list_only_reloads_changed_card(settings, authed_client):
    """Mutating one opp's state.yaml invalidates only that opp's card.
    The behavioural assertion is that the response after mutation reflects
    the change for that opp, and the other opps' fields are still correct.
    """
    fake = FakeDriveClient.from_tree(_combined_tree())
    with patch("apps.opps.access.get_drive_client", return_value=fake), \
         patch("apps.opps.access.resolve_ace_root_folder_id",
               return_value=fake.folder_id("ACE")):
        first = authed_client.get("/api/opps/")
        assert first.status_code == 200
        first_etag = first.headers["ETag"]

        state_id = fake.file_id("ACE/malaria-pilot/run_state.yaml")
        fake.update_file(
            state_id,
            "current_phase: app-building\ncurrent_step: app-build\nmode: review\n",
            "application/x-yaml",
        )

        second = authed_client.get("/api/opps/", HTTP_IF_NONE_MATCH=first_etag)
    assert second.status_code == 200
    payload = second.json()["data"]
    target = next(c for c in payload if c["slug"] == "malaria-pilot")
    assert target["current_step"] == "app-build"
