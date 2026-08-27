"""A run folder with no ``run_state.yaml`` is not a run (ace-web#734).

The forked run in #734 landed in Drive as six phase folders and a
``decisions.yaml`` with no ``run_state.yaml``. Asked for that run's
public summary, the API answered **200 with an empty payload** — so
"the fork failed" and "the run has not started" were indistinguishable
from the outside, and the page rendered a shell with nothing in it.

``run_state.yaml`` is the file that makes a folder a run: it is where
``/ace:run`` reads execution order from, and it is where every product
the summary projects comes from. Absent it, the honest answer is 404,
which the caller already maps from a ``None`` payload.
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from apps.opps.summary import build_summary_payload
from apps.opps.tests.fixtures.fake_drive import FakeDriveClient

OPP_SLUG = "hh-poverty-targeting"
RUN_ID = "20260827-0323"

_OPP_YAML = "display_name: HH Poverty Targeting\nslug: hh-poverty-targeting\n"
_STATE_YAML = "opportunity: hh-poverty-targeting\nrun_id: 20260827-0323\nphases: {}\n"


@dataclass
class _FakeWorkspace:
    drive_root_folder_id: str
    slug: str = "dimagi-team"


def _tree(*, with_run_state: bool) -> dict:
    run: dict = {"decisions.yaml": "schema_version: 2\ndecisions: []\n"}
    if with_run_state:
        run["run_state.yaml"] = _STATE_YAML
    return {
        "ACE": {
            OPP_SLUG: {
                "opp.yaml": _OPP_YAML,
                "runs": {RUN_ID: run},
            },
        },
    }


def _build(*, with_run_state: bool):
    drive = FakeDriveClient.from_tree(_tree(with_run_state=with_run_state))
    ws = _FakeWorkspace(drive_root_folder_id=drive.folder_id("ACE"))
    return build_summary_payload(
        drive, workspace=ws, opp_slug=OPP_SLUG, run_id=RUN_ID,
        viewer_is_member=False,
    )


def test_run_folder_without_run_state_yields_no_payload():
    """#734's stalled fork verbatim: phase folders + decisions.yaml, no
    run_state.yaml. The endpoint maps ``None`` to 404."""
    assert _build(with_run_state=False) is None


def test_run_folder_with_run_state_still_builds():
    """The guard is about the state file's PRESENCE, not its richness —
    a freshly-seeded run whose phases are all pending must still build."""
    payload = _build(with_run_state=True)
    assert payload is not None
    assert payload["opp"]["slug"] == OPP_SLUG


@pytest.mark.django_db
def test_endpoint_404s_for_a_run_folder_without_run_state(client, monkeypatch):
    from django.contrib.auth import get_user_model

    from apps.workspaces.models import Workspace

    user = get_user_model().objects.create_user(email="summary734@dimagi.com")
    if not Workspace.objects.filter(slug="dimagi-team").exists():
        Workspace.objects.create(
            slug="dimagi-team", display_name="Dimagi Team",
            drive_root_folder_id="root", created_by=user,
        )
    monkeypatch.setattr(
        "apps.opps.summary.build_summary_payload",
        lambda *a, **kw: None,
    )
    monkeypatch.setattr(
        "apps.opps.drive_client.get_drive_client", lambda **kw: object(),
    )
    response = client.get(
        f"/api/public/dimagi-team/{OPP_SLUG}/runs/{RUN_ID}/summary"
    )
    assert response.status_code == 404
