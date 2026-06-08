"""Tests for apps.videos.templates — discovery + skeleton loading.

Focus: the load_template path strips the skeleton's author-time doc
comment block before returning, so substituting placeholders into the
output doesn't leave garbled comments referencing the placeholders
themselves.

Also covers the Drive-backed template helpers added in T1
(templates_folder_id, list_template_ids, read_template_file,
write_template_file) using the same FakeDriveClient the service tests use.
"""
from __future__ import annotations

import textwrap
from types import SimpleNamespace

import pytest

from apps.opps.tests.fixtures.fake_drive import FakeDriveClient
from apps.videos import drive, templates


def test_strip_leading_doc_comments_drops_header_until_first_blank():
    src = textwrap.dedent("""\
        # Top-level docs.
        #
        # Filled by skill: {{program_slug}} {{workspace_slug}}.

        slug: "{{program_slug}}"
        workspace: "{{workspace_slug}}"
        """)
    stripped = templates._strip_leading_doc_comments(src)
    assert not stripped.startswith("#")
    assert stripped.startswith("slug:")
    # The doc-comment placeholder reference is gone; the body's real
    # placeholder remains (it's where the substitution lands).
    assert "Top-level docs" not in stripped


def test_strip_leading_doc_comments_no_op_when_first_line_is_yaml():
    src = "slug: \"x\"\nworkspace: \"y\"\n"
    assert templates._strip_leading_doc_comments(src) == src


def test_strip_leading_doc_comments_preserves_inline_comments():
    """Inline comments AFTER the first YAML field stay — only the
    leading block is stripped."""
    src = textwrap.dedent("""\
        # Header doc.

        slug: "x"
        # inline note
        workspace: "y"
        """)
    stripped = templates._strip_leading_doc_comments(src)
    assert "# inline note" in stripped


def test_strip_leading_doc_comments_handles_empty_file():
    assert templates._strip_leading_doc_comments("") == ""


def test_strip_leading_doc_comments_handles_only_comments():
    """Pathological: file is nothing but comments."""
    src = "# a\n# b\n# c\n"
    assert templates._strip_leading_doc_comments(src) == ""


def test_load_template_60s_campaign_overview_drops_doc_header(settings, tmp_path):
    """Integration: the real 60s-campaign-overview template fetched
    via load_template starts at provenance:, not at the `#`-block
    documenting placeholders."""
    # Use the real templates dir from this repo.
    bundle = templates.load_template("60s-campaign-overview")
    assert bundle is not None
    first_line = bundle.skeleton_yaml.splitlines()[0]
    assert first_line.startswith("provenance:")
    # Sanity: no stale doc-style `{{placeholder}}` references inside
    # commented lines (the dangerous ones are the ones that look like
    # examples but get substituted alongside real placeholders).
    for line in bundle.skeleton_yaml.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("#") and "{{" in stripped:
            raise AssertionError(
                f"Surviving doc comment contains a {{placeholder}}: {line!r}"
            )


def test_load_template_partnership_pitch_strips_doc_header():
    bundle = templates.load_template("partnership-pitch")
    assert bundle is not None
    assert bundle.skeleton_yaml.splitlines()[0].startswith("provenance:")
    for angle in ("day-in-the-life", "the-scale-gap", "trust-travels"):
        assert angle in bundle.skeleton_yaml


def test_load_template_connect_explainer_strips_doc_header():
    """The connect-explainer template (explainer mode — no problem/impact
    stat beats) loads, and its skeleton starts at the first real field
    (provenance:), not at the leading `#` doc-comment block."""
    bundle = templates.load_template("connect-explainer")
    assert bundle is not None
    assert bundle.skeleton_yaml.splitlines()[0].startswith("provenance:")
    # No surviving doc comment carries a {{placeholder}} (the dangerous
    # ones that get substituted alongside real placeholders).
    for line in bundle.skeleton_yaml.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("#") and "{{" in stripped:
            raise AssertionError(
                f"Surviving doc comment contains a {{placeholder}}: {line!r}"
            )


def test_load_template_includes_provenance_placeholders():
    """The skeleton must include the two new provenance placeholders
    (template_id, generated_at) that the skill is expected to fill."""
    bundle = templates.load_template("60s-campaign-overview")
    assert bundle is not None
    assert "{{template_id}}" in bundle.skeleton_yaml
    assert "{{generated_at}}" in bundle.skeleton_yaml
    # And the agent prompt must document them.
    assert "template_id" in bundle.prompt_md
    assert "generated_at" in bundle.prompt_md


# ---------------------------------------------------------------------------
# Drive-backed template helpers (T1)
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_drive_ws(monkeypatch):
    """FakeDriveClient + workspace stub wired to apps.videos.drive."""
    client = FakeDriveClient.from_tree({"workspace-root": {}})
    workspace_root_id = client.folder_id("workspace-root")
    monkeypatch.setattr(drive, "client_for_workspace", lambda ws: client)
    workspace = SimpleNamespace(
        slug="test-ws", drive_root_folder_id=workspace_root_id,
    )
    return SimpleNamespace(client=client, workspace=workspace)


def test_templates_folder_and_files_roundtrip(fake_drive_ws):
    """Full round-trip: create _templates folder, write a file into a
    template sub-folder, read it back, and confirm list_template_ids."""
    from apps.videos import service

    layout, client = service.layout_for(fake_drive_ws.workspace)

    # Before create=True the folder is absent.
    assert drive.templates_folder_id(layout, client) is None

    # After create=True it exists.
    tid = drive.templates_folder_id(layout, client, create=True)
    assert tid is not None

    # write_template_file materialises the per-template sub-folder and
    # stores the file; it returns a non-None file id.
    fid = drive.write_template_file(layout, client, "demo", "meta.yaml", "name: Demo\n")
    assert fid is not None

    # read_template_file returns the same content.
    assert drive.read_template_file(layout, client, "demo", "meta.yaml") == "name: Demo\n"

    # list_template_ids sees the new template.
    assert "demo" in drive.list_template_ids(layout, client)

    # Markdown files use text/markdown mime — write a .md file and verify
    # the round-trip still works (mime is stored in the node).
    fid_md = drive.write_template_file(layout, client, "demo", "prompt.md", "# Prompt\n")
    assert fid_md is not None
    assert drive.read_template_file(layout, client, "demo", "prompt.md") == "# Prompt\n"

    # create-or-replace: writing again returns the SAME file id.
    fid2 = drive.write_template_file(layout, client, "demo", "meta.yaml", "name: Updated\n")
    assert fid2 == fid
    assert drive.read_template_file(layout, client, "demo", "meta.yaml") == "name: Updated\n"


def test_list_template_ids_empty_when_no_templates_folder(fake_drive_ws):
    """list_template_ids returns [] when _templates/ doesn't exist yet."""
    from apps.videos import service

    layout, client = service.layout_for(fake_drive_ws.workspace)
    assert drive.list_template_ids(layout, client) == []


def test_read_template_file_returns_none_when_missing(fake_drive_ws):
    """read_template_file returns None for an absent file."""
    from apps.videos import service

    layout, client = service.layout_for(fake_drive_ws.workspace)
    assert drive.read_template_file(layout, client, "ghost", "meta.yaml") is None


def test_template_folder_id_create_false_returns_none(fake_drive_ws):
    """_template_folder_id with create=False returns None when folder absent."""
    from apps.videos import service

    layout, client = service.layout_for(fake_drive_ws.workspace)
    assert drive._template_folder_id(layout, client, "absent") is None
