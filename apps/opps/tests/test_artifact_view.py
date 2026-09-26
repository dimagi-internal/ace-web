"""``/artifacts/{id}/view`` — a run file, shaped for the in-page viewer.

The authorization tests matter most: the id must be a file OF THIS RUN. A
viewer endpoint that fetched whatever id it was handed would let any
workspace member read any file the service account can see.
"""
from __future__ import annotations

import pytest

from apps.opps import artifact_view
from apps.opps.drive_client import DriveFile, FileContent

DOC = "application/vnd.google-apps.document"
SLIDES = "application/vnd.google-apps.presentation"
SHEET = "application/vnd.google-apps.spreadsheet"


class _Drive:
    def __init__(self, files=None, folder=()):
        self.files = files or {}
        self.folder = list(folder)
        self.calls: list[tuple] = []

    def get_file(self, file_id):
        name, mime, size = self.files[file_id]
        return DriveFile(id=file_id, name=name, mime_type=mime,
                         web_view_link=f"https://drive/{file_id}", size_bytes=size)

    def list_folder(self, folder_id):
        return [DriveFile(id=i, name=i, mime_type=DOC, web_view_link="") for i in self.folder]

    def get_content(self, file_id, mime_type, *, export_as=None):
        self.calls.append(("content", file_id, export_as))
        return FileContent(content=f"# body {file_id}\\+", content_type=export_as or "text/plain")

    def export_bytes(self, file_id, export_mime):
        self.calls.append(("export", file_id, export_mime))
        return b"%PDF-1.7"

    def get_binary(self, file_id):
        self.calls.append(("binary", file_id))
        return b"\x89PNG"


def _snapshot(artifacts=(), products=(), folder_id="run-folder"):
    return {
        "current_run": {
            "run_id": "r1",
            "folder_id": folder_id,
            "steps": [{"skill_name": "s", "artifacts": list(artifacts)}],
            "products": list(products),
        },
    }


def _art(file_id, name, mime, size=10):
    return {"drive_file_id": file_id, "name": name, "mime_type": mime, "size_bytes": size,
            "drive_web_link": f"https://drive/{file_id}", "path": name}


# ─── authorization ──────────────────────────────────────────────────


def test_unknown_id_is_not_found():
    with pytest.raises(artifact_view.ArtifactNotFound):
        artifact_view.resolve(_Drive(), _snapshot(), "someone-elses-file")


def test_step_artifact_resolves_without_a_drive_metadata_read():
    meta = artifact_view.resolve(_Drive(), _snapshot([_art("a1", "pdd.md", DOC)]), "a1")
    assert (meta.name, meta.mime_type) == ("pdd.md", DOC)


def test_product_file_id_is_allowed_and_looked_up():
    drive = _Drive(files={"deck": ("Training deck", SLIDES, None)})
    meta = artifact_view.resolve(drive, _snapshot(products=[{"file_id": "deck"}]), "deck")
    assert meta.mime_type == SLIDES


def test_run_folder_file_is_allowed():
    drive = _Drive(files={"dec": ("decisions.yaml", DOC, 5)}, folder=["dec"])
    assert artifact_view.resolve(drive, _snapshot(), "dec").name == "decisions.yaml"


# ─── representation ─────────────────────────────────────────────────


def test_prose_doc_is_markdown_passed_through_verbatim():
    drive = _Drive()
    view = artifact_view.render(drive, artifact_view.resolve(
        drive, _snapshot([_art("a1", "pdd.md", DOC)]), "a1"))
    assert view.content_type.startswith("text/markdown")
    assert view.body.endswith(b"\\+")  # escapes are the renderer's job
    assert drive.calls == [("content", "a1", "text/markdown")]


def test_untitled_doc_reads_as_markdown_but_yaml_doc_as_plain_text():
    drive = _Drive()
    snap = _snapshot([_art("a1", "Turmeric Market Survey", DOC), _art("a2", "run_state.yaml", DOC)])
    assert artifact_view.render(drive, artifact_view.resolve(drive, snap, "a1")) \
        .content_type.startswith("text/markdown")
    view = artifact_view.render(drive, artifact_view.resolve(drive, snap, "a2"))
    assert view.content_type.startswith("text/plain")
    assert drive.calls[-1] == ("content", "a2", None)


def test_deck_is_a_pdf_export_and_sheet_is_csv():
    drive = _Drive()
    snap = _snapshot([_art("d", "deck", SLIDES), _art("s", "sheet", SHEET)])
    deck = artifact_view.render(drive, artifact_view.resolve(drive, snap, "d"))
    assert (deck.content_type, deck.body) == ("application/pdf", b"%PDF-1.7")
    assert artifact_view.render(drive, artifact_view.resolve(drive, snap, "s")) \
        .content_type.startswith("text/csv")


def test_image_is_served_as_bytes_and_oversized_media_is_refused():
    drive = _Drive()
    snap = _snapshot([
        _art("i", "shot.png", "image/png"),
        _art("v", "walk.mp4", "video/mp4", size=artifact_view.MAX_VIEW_BYTES + 1),
    ])
    img = artifact_view.render(drive, artifact_view.resolve(drive, snap, "i"))
    assert (img.content_type, img.body) == ("image/png", b"\x89PNG")
    with pytest.raises(artifact_view.ArtifactTooLarge):
        artifact_view.render(drive, artifact_view.resolve(drive, snap, "v"))


def test_unknown_binary_type_is_not_viewable():
    drive = _Drive()
    snap = _snapshot([_art("z", "bundle.zip", "application/zip")])
    with pytest.raises(artifact_view.ArtifactNotViewable):
        artifact_view.render(drive, artifact_view.resolve(drive, snap, "z"))


# ─── endpoint ───────────────────────────────────────────────────────


@pytest.fixture
def member_client(db, client):
    from apps.auth.models import User
    from apps.workspaces.models import Workspace, WorkspaceMembership

    workspace = Workspace.objects.create(
        slug="ws1", display_name="WS1", drive_root_folder_id="folder-1",
        created_by=User.objects.create_user(email="creator@example.com"),
    )
    user = User.objects.create_user(email="a@example.com")
    WorkspaceMembership.objects.create(workspace=workspace, user=user, role="editor")
    client.force_login(user)
    return client


def _wire(monkeypatch, snapshot, drive):
    monkeypatch.setattr("apps.opps.api.load_rich_opp_snapshot",
                        lambda workspace, slug, run_id=None: snapshot)
    monkeypatch.setattr("apps.opps.drive_client.get_drive_client",
                        lambda workspace=None: drive)


@pytest.mark.django_db
def test_endpoint_serves_the_view_with_name_and_drive_link(member_client, monkeypatch):
    _wire(monkeypatch, _snapshot([_art("a1", "PDD — v2.md", DOC)]), _Drive())
    r = member_client.get("/api/w/ws1/opps/opp/artifacts/a1/view?run_id=r1")
    assert r.status_code == 200
    assert r["Content-Type"].startswith("text/markdown")
    assert r["X-Artifact-Name"] == "PDD%20%E2%80%94%20v2.md"
    assert r["X-Drive-Link"] == "https://drive/a1"
    assert "private" in r["Cache-Control"]


@pytest.mark.django_db
def test_endpoint_404s_a_file_outside_the_run(member_client, monkeypatch):
    _wire(monkeypatch, _snapshot(), _Drive())
    r = member_client.get("/api/w/ws1/opps/opp/artifacts/elsewhere/view?run_id=r1")
    assert r.status_code == 404


@pytest.mark.django_db
def test_endpoint_refuses_a_snapshot_for_a_different_run(member_client, monkeypatch):
    """The loader falls back to the latest run for an unknown id; the viewer
    must not resolve a file against a run the caller didn't name."""
    _wire(monkeypatch, _snapshot([_art("a1", "pdd.md", DOC)]), _Drive())
    r = member_client.get("/api/w/ws1/opps/opp/artifacts/a1/view?run_id=other-run")
    assert r.status_code == 404


@pytest.mark.django_db
def test_endpoint_maps_unviewable_and_too_large(member_client, monkeypatch):
    snap = _snapshot([
        _art("z", "bundle.zip", "application/zip"),
        _art("v", "walk.mp4", "video/mp4", size=artifact_view.MAX_VIEW_BYTES + 1),
    ])
    _wire(monkeypatch, snap, _Drive())
    assert member_client.get("/api/w/ws1/opps/opp/artifacts/z/view").status_code == 415
    assert member_client.get("/api/w/ws1/opps/opp/artifacts/v/view").status_code == 413
