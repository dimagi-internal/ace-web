"""``/artifacts/{id}/download`` must honour ``run_id``.

The frontend has always appended ``?run_id=<run>`` to the download URL,
but the view took no such parameter and ``download_artifact_bytes``
searched ``snap.current_run.steps`` only. Opening any artifact belonging
to a run that is not the opp's current run therefore 404'd, while the
step listing beside it (which does honour run_id) showed the artifact
happily.

Latent rather than reported: the run people were looking at happened to
be the current one. It stops being latent the moment anyone opens an
older run — exactly what the run picker invites.
"""
import pytest

from apps.opps import api as opps_api


class _Drive:
    def get_content(self, file_id, mime_type):
        class C:
            content = f"body-of-{file_id}"
        return C()


def _snap(run_id, artifact_id):
    class A:
        drive_file_id = artifact_id
        mime_type = "text/markdown"

    class Step:
        artifacts = [A()]

    class Run:
        steps = [Step()]

    class Snap:
        current_run = Run()

    return Snap()


@pytest.fixture
def _wired(monkeypatch):
    """Stub the Drive edges; capture the run_id load_opp is asked for."""
    seen = {}

    monkeypatch.setattr(
        "apps.opps.access.resolve_ace_root_folder_id", lambda ws: "ace-root")
    monkeypatch.setattr(
        "apps.opps.drive_client.get_drive_client", lambda workspace=None: _Drive())

    def fake_load_opp(client, *, ace_folder_id=None, slug=None, run_id=None, **kw):
        seen["run_id"] = run_id
        return _snap(run_id, "artifact-in-old-run")

    monkeypatch.setattr("apps.opps.sync.load_opp", fake_load_opp)
    return seen


def test_run_id_is_forwarded_to_load_opp(_wired):
    data, mime = opps_api.download_artifact_bytes(
        object(), "spark-facilitator", "artifact-in-old-run",
        run_id="20260724-1622",
    )
    assert _wired["run_id"] == "20260724-1622"
    assert data == b"body-of-artifact-in-old-run"
    assert mime == "text/markdown"


def test_run_id_is_optional_and_defaults_to_the_current_run(_wired):
    opps_api.download_artifact_bytes(
        object(), "spark-facilitator", "artifact-in-old-run")
    assert _wired["run_id"] is None
