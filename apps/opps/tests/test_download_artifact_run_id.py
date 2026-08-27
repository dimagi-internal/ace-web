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


# ── run-level artifacts ────────────────────────────────────────────────
#
# Not every artifact the UI lists is attributed to a STEP. `decisions.yaml`
# and `open-questions.md` sit at the run root, and a cold `load_opp`
# attaches them to no step at all — so a step-only scan 404s them while
# the step listing beside them shows them happily. (Prod hid this: the
# listing is served from a cached snapshot that still attributes them,
# and before the forked_from fix every download 500'd long before the
# lookup ran.) Reproduced against live Drive on spark-facilitator
# 20260724-1622: 1 of 3 artifacts resolved.
#
# The scan must therefore also cover files sitting directly in the run
# folder — and must NOT degrade into "fetch any id you're given", which
# would make the endpoint a read-anything proxy for any workspace member.


class _RunFolderDrive(_Drive):
    def __init__(self, files):
        self._files = files

    def list_folder(self, folder_id):
        return self._files.get(folder_id, [])

    list_files = list_folder


class _F:
    def __init__(self, fid, name, mime="text/yaml"):
        self.id, self.name, self.mime_type = fid, name, mime


def _snap_with_run_folder(run_folder_id, step_artifact_id=None):
    class Step:
        artifacts = []
        folder_id = "phase-1"

    class Run:
        steps = [Step()]
        folder_id = run_folder_id

    class Snap:
        current_run = Run()

    return Snap()


@pytest.fixture
def _run_level(monkeypatch):
    drive = _RunFolderDrive({
        "run-folder": [_F("decisions-id", "decisions.yaml"),
                       _F("open-q-id", "open-questions.md")],
        "phase-1": [],
    })
    monkeypatch.setattr(
        "apps.opps.access.resolve_ace_root_folder_id", lambda ws: "ace-root")
    monkeypatch.setattr(
        "apps.opps.drive_client.get_drive_client", lambda workspace=None: drive)
    monkeypatch.setattr(
        "apps.opps.sync.load_opp",
        lambda c, **kw: _snap_with_run_folder("run-folder"))
    return drive


def test_run_level_artifact_is_downloadable(_run_level):
    data, mime = opps_api.download_artifact_bytes(
        object(), "spark-facilitator", "decisions-id", run_id="20260724-1622")
    assert data == b"body-of-decisions-id"


def test_a_file_outside_the_run_is_still_refused(_run_level):
    """The step/run scan IS the authorization boundary — don't lose it."""
    with pytest.raises(FileNotFoundError):
        opps_api.download_artifact_bytes(
            object(), "spark-facilitator", "some-unrelated-drive-file")
