"""apps/opps/preview_gaps.py — the outputs the page can't show yet."""
from __future__ import annotations

from apps.opps.drive_client import DriveFile
from apps.opps.preview_gaps import auth_for, build_preview_gaps


class _Drive:
    def __init__(self, files: dict[str, tuple[str, str]], broken: tuple[str, ...] = ()):
        self.files = files
        self.broken = broken
        self.calls: list[str] = []

    def get_file(self, file_id):
        self.calls.append(file_id)
        if file_id in self.broken:
            raise RuntimeError("drive down")
        name, mime = self.files[file_id]
        return DriveFile(id=file_id, name=name, mime_type=mime, web_view_link="", size_bytes=10)


def _p(key, kind, url=None, file_id=None, previews=(), phase="p"):
    return {"id": f"{phase}:{key}", "phase": phase, "key": key, "kind": kind, "title": key,
            "url": url, "file_id": file_id, "previews": list(previews)}


def _snap(products):
    return {"current_run": {"run_id": "r1", "products": products}}


def test_viewable_docs_and_pictured_outputs_are_covered_the_rest_are_gaps():
    drive = _Drive({
        "doc": ("PDD", "application/vnd.google-apps.document"),
        "html": ("walkthrough.html", "text/html"),
        "zip": ("bundle.zip", "application/zip"),
    })
    out = build_preview_gaps(_snap([
        _p("pdd", "document", file_id="doc"),
        _p("apps.learn", "commcare_app", "https://www.commcarehq.org/a/d/apps/view/1/",
           previews=[{"file_id": "s"}]),
        _p("connect.opportunity", "connect_opportunity", "https://connect.dimagi.com/a/o/opportunity/1/"),
        _p("ocs_chatbot", "chatbot", "https://www.openchatstudio.com/a/t/chatbots/1/"),
        _p("solicitation", "solicitation", "https://labs.connect.dimagi.com/solicitations/9/"),
        _p("bundle", "link", file_id="zip"),
        _p("walk", "document", file_id="html"),
    ]), drive)
    assert out["run_id"] == "r1"
    assert out["covered"] == 3  # the PDD, the pictured app, and the HTML (text/*)
    gaps = {g["output_key"]: (g["reason"], g["auth"]) for g in out["outputs"]}
    assert gaps == {
        "connect.opportunity": ("no-preview", "connect"),
        "ocs_chatbot": ("no-preview", "ocs"),
        "solicitation": ("no-preview", "labs"),
        "bundle": ("not-viewable-file", "google"),
    }
    # Only file outputs cost a metadata read, and a pictured one none at all.
    assert sorted(drive.calls) == ["doc", "html", "zip"]


def test_a_file_whose_metadata_cannot_be_read_is_a_gap_not_covered():
    out = build_preview_gaps(_snap([_p("pdd", "document", file_id="x")]), _Drive({}, ("x",)))
    assert [g["reason"] for g in out["outputs"]] == ["not-viewable-file"]


def test_auth_by_host():
    assert auth_for("https://connect.dimagi.com/a/x/") == "connect"
    assert auth_for("https://labs.connect.dimagi.com/solicitations/9/") == "labs"
    # canopy lives under the labs host but a labs session is sent to sign-in.
    assert auth_for("https://labs.connect.dimagi.com/canopy/ddd/a/b") == "canopy"
    # canopy's own host since 2026-10-05 — not "public", or a preview photographs sign-in.
    assert auth_for("https://canopy.dimagi.com/ddd/a/b") == "canopy"
    assert auth_for("https://canopy.dimagi.com/walkthrough/x?t=y") == "canopy"
    assert auth_for("https://www.commcarehq.org/a/d/") == "hq"
    assert auth_for("https://www.openchatstudio.com/a/t/") == "ocs"
    assert auth_for("https://docs.google.com/document/d/1") == "google"
    assert auth_for("https://example.org/") == "public"
    assert auth_for(None) == "public"
