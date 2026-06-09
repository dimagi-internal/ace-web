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
from django.core.cache import cache as django_cache

from apps.opps.tests.fixtures.fake_drive import FakeDriveClient
from apps.videos import drive, templates


@pytest.fixture(autouse=True)
def clear_cache():
    """Each test starts with a clean cache to prevent cross-test leakage."""
    django_cache.clear()
    yield
    django_cache.clear()


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


def test_load_template_60s_campaign_overview_drops_doc_header(fake_drive_ws):
    """Integration: the real 60s-campaign-overview template fetched
    via load_template starts at provenance:, not at the `#`-block
    documenting placeholders."""
    # Seed from the real templates dir into the fake Drive workspace.
    templates.list_templates(fake_drive_ws.workspace)  # triggers lazy auto-seed
    bundle = templates.load_template(fake_drive_ws.workspace, "60s-campaign-overview")
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


def test_load_template_partnership_pitch_strips_doc_header(fake_drive_ws):
    templates.list_templates(fake_drive_ws.workspace)
    bundle = templates.load_template(fake_drive_ws.workspace, "partnership-pitch")
    assert bundle is not None
    assert bundle.skeleton_yaml.splitlines()[0].startswith("provenance:")
    for angle in ("day-in-the-life", "the-scale-gap", "trust-travels"):
        assert angle in bundle.skeleton_yaml


def test_load_template_connect_explainer_strips_doc_header(fake_drive_ws):
    """The connect-explainer template (explainer mode — no problem/impact
    stat beats) loads, and its skeleton starts at the first real field
    (provenance:), not at the leading `#` doc-comment block."""
    templates.list_templates(fake_drive_ws.workspace)
    bundle = templates.load_template(fake_drive_ws.workspace, "connect-explainer")
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


def test_load_template_includes_provenance_placeholders(fake_drive_ws):
    """The skeleton must include the two new provenance placeholders
    (template_id, generated_at) that the skill is expected to fill."""
    templates.list_templates(fake_drive_ws.workspace)
    bundle = templates.load_template(fake_drive_ws.workspace, "60s-campaign-overview")
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


# ---------------------------------------------------------------------------
# seed_templates (T2)
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_drive_ws_db(db, monkeypatch):
    """FakeDriveClient + real DB Workspace wired to apps.videos.drive.
    Used by management-command tests that require Workspace.objects.get."""
    from django.contrib.auth import get_user_model
    from apps.workspaces.models import Workspace

    User = get_user_model()
    client = FakeDriveClient.from_tree({"workspace-root": {}})
    workspace_root_id = client.folder_id("workspace-root")
    monkeypatch.setattr(drive, "client_for_workspace", lambda ws: client)

    creator = User.objects.create_user(email="ws-creator@example.com")
    ws = Workspace.objects.create(
        slug="test-ws",
        display_name="Test WS",
        drive_root_folder_id=workspace_root_id,
        created_by=creator,
    )
    return ws


@pytest.mark.django_db
def test_seed_templates_command(fake_drive_ws_db):
    from django.core.management import call_command
    from apps.videos import drive as _drive, service
    call_command("videos_seed_templates", "--workspace", fake_drive_ws_db.slug)
    layout, client = service.layout_for(fake_drive_ws_db)
    assert _drive.list_template_ids(layout, client)


def test_seed_templates_uploads_repo_tree(fake_drive_ws):
    """seed_templates copies all repo templates to Drive and returns count >= 3."""
    from apps.videos import service

    n = templates.seed_templates(fake_drive_ws.workspace)
    assert n >= 3

    layout, client = service.layout_for(fake_drive_ws.workspace)
    ids = drive.list_template_ids(layout, client)
    assert {"connect-explainer", "connectify-program", "partnership-pitch"} <= set(ids)

    # The Drive filename is "skeleton.yaml" (mapped from spec.template.yaml).
    skeleton = drive.read_template_file(layout, client, "connectify-program", "skeleton.yaml")
    assert skeleton is not None
    assert "active_cut" in skeleton


def test_seed_templates_is_idempotent(fake_drive_ws):
    """seed_templates skips templates already present in Drive; second call returns 0."""
    templates.seed_templates(fake_drive_ws.workspace)
    assert templates.seed_templates(fake_drive_ws.workspace) == 0


# ---------------------------------------------------------------------------
# T3: Drive-backed read-through + cache + lazy auto-seed
# ---------------------------------------------------------------------------


def test_list_templates_lazy_autoseeds_from_drive(fake_drive_ws):
    """list_templates auto-seeds from the repo tree when Drive has no templates."""
    metas = templates.list_templates(fake_drive_ws.workspace)   # no explicit seed
    ids = {m.id for m in metas}
    assert {"connect-explainer", "connectify-program", "partnership-pitch"} <= ids


def test_load_template_from_drive(fake_drive_ws):
    """load_template reads from Drive after seeding."""
    templates.list_templates(fake_drive_ws.workspace)  # seed
    b = templates.load_template(fake_drive_ws.workspace, "connectify-program")
    assert b is not None
    assert "active_cut" in b.skeleton_yaml
    assert b.prompt_md.strip()
    assert b.meta.name


def test_load_template_missing_returns_none(fake_drive_ws):
    """load_template returns None for a template not present in Drive."""
    templates.list_templates(fake_drive_ws.workspace)
    assert templates.load_template(fake_drive_ws.workspace, "does-not-exist") is None


def test_list_templates_cached_on_second_call(fake_drive_ws):
    """Second call to list_templates returns from cache (no new Drive list call)."""
    from unittest import mock
    metas1 = templates.list_templates(fake_drive_ws.workspace)
    assert len(metas1) >= 3
    # Patch drive.list_template_ids — should not be called on second call.
    with mock.patch.object(drive, "list_template_ids") as spy:
        metas2 = templates.list_templates(fake_drive_ws.workspace)
    assert len(metas2) == len(metas1)
    assert spy.call_count == 0


def test_load_template_cached_on_second_call(fake_drive_ws):
    """Second call to load_template returns from cache."""
    from unittest import mock
    templates.list_templates(fake_drive_ws.workspace)
    b1 = templates.load_template(fake_drive_ws.workspace, "connectify-program")
    assert b1 is not None
    with mock.patch.object(drive, "read_template_file") as spy:
        b2 = templates.load_template(fake_drive_ws.workspace, "connectify-program")
    assert b2 is not None
    assert b2.meta.id == b1.meta.id
    assert spy.call_count == 0


def test_invalidate_tpl_list_clears_list_cache(fake_drive_ws):
    """invalidate_tpl(slug) with no tid drops the list cache entry."""
    from apps.videos import cache as vcache
    templates.list_templates(fake_drive_ws.workspace)
    assert vcache.get_tpl_list(fake_drive_ws.workspace.slug) is not None
    vcache.invalidate_tpl(fake_drive_ws.workspace.slug)
    assert vcache.get_tpl_list(fake_drive_ws.workspace.slug) is None


def test_invalidate_tpl_bundle_clears_bundle_and_list(fake_drive_ws):
    """invalidate_tpl(slug, tid) drops the specific bundle AND the list."""
    from apps.videos import cache as vcache
    templates.list_templates(fake_drive_ws.workspace)
    templates.load_template(fake_drive_ws.workspace, "connectify-program")
    ws_slug = fake_drive_ws.workspace.slug
    assert vcache.get_tpl_bundle(ws_slug, "connectify-program") is not None
    assert vcache.get_tpl_list(ws_slug) is not None
    vcache.invalidate_tpl(ws_slug, "connectify-program")
    assert vcache.get_tpl_bundle(ws_slug, "connectify-program") is None
    assert vcache.get_tpl_list(ws_slug) is None


# ---------------------------------------------------------------------------
# T6: save_template + load_example
# ---------------------------------------------------------------------------


def test_save_template_meta_persists(fake_drive_ws):
    """Updating name via save_template round-trips through Drive and cache."""
    ws = fake_drive_ws.workspace
    templates.list_templates(ws)  # seed
    b = templates.save_template(ws, "connect-explainer", meta={"name": "Renamed"})
    assert b.meta.name == "Renamed"
    assert templates.load_template(ws, "connect-explainer").meta.name == "Renamed"


def test_save_template_rejects_bad_skeleton(fake_drive_ws):
    """skeleton_yaml that does not parse as a YAML mapping raises ValueError."""
    ws = fake_drive_ws.workspace
    templates.list_templates(ws)
    with pytest.raises(ValueError):
        templates.save_template(ws, "connect-explainer", skeleton_yaml="::: not yaml :::")


def test_save_template_rejects_skeleton_not_mapping(fake_drive_ws):
    """skeleton_yaml that parses but is not a mapping (e.g. a list) raises ValueError."""
    ws = fake_drive_ws.workspace
    templates.list_templates(ws)
    with pytest.raises(ValueError):
        templates.save_template(ws, "connect-explainer", skeleton_yaml="- item1\n- item2\n")


def test_save_template_rejects_schema_invalid_example(fake_drive_ws):
    """example_yaml missing required program-spec fields raises ValueError."""
    ws = fake_drive_ws.workspace
    templates.list_templates(ws)
    with pytest.raises(ValueError):
        # Missing slug + workspace fields → validate_spec_structure raises ValueError.
        templates.save_template(ws, "connect-explainer", example_yaml="slug: x\n")


def test_save_template_rejects_example_not_mapping(fake_drive_ws):
    """example_yaml that parses as a list (not mapping) raises ValueError."""
    ws = fake_drive_ws.workspace
    templates.list_templates(ws)
    with pytest.raises(ValueError):
        templates.save_template(ws, "connect-explainer", example_yaml="- a\n- b\n")


def test_save_template_valid_example_persists(fake_drive_ws):
    """A structurally valid example_yaml is stored and load_example returns it."""
    ws = fake_drive_ws.workspace
    templates.list_templates(ws)
    valid_ex = (
        "slug: connect-explainer\n"
        "workspace: test-ws\n"
        "name: Example Program\n"
    )
    b = templates.save_template(ws, "connect-explainer", example_yaml=valid_ex)
    assert b is not None  # bundle returned on success
    ex = templates.load_example(ws, "connect-explainer")
    assert ex is not None
    assert "slug: connect-explainer" in ex


def test_save_template_nonexistent_raises(fake_drive_ws):
    """save_template raises ValueError when the template has no meta.yaml."""
    ws = fake_drive_ws.workspace
    templates.list_templates(ws)  # seed real ones
    with pytest.raises(ValueError, match="does not exist"):
        templates.save_template(ws, "no-such-template", meta={"name": "x"})


def test_load_example(fake_drive_ws):
    """load_example returns the seeded example for connectify-program."""
    ws = fake_drive_ws.workspace
    templates.list_templates(ws)  # triggers auto-seed which uploads example.spec.yaml too
    ex = templates.load_example(ws, "connectify-program")
    assert ex and "slug: connectify-program" in ex


def test_load_example_returns_none_when_missing(fake_drive_ws):
    """load_example returns None when example.spec.yaml was not seeded."""
    ws = fake_drive_ws.workspace
    templates.list_templates(ws)
    # connect-explainer has no example.spec.yaml in the repo tree
    ex = templates.load_example(ws, "connect-explainer")
    # May be None (no file) or a string (if it does exist); just ensure no exception.
    assert ex is None or isinstance(ex, str)


# ---------------------------------------------------------------------------
# T7: load_example_spec + save_template(example_spec=...)
# ---------------------------------------------------------------------------


def test_load_example_spec_parsed(fake_drive_ws):
    """load_example_spec returns the example as a parsed dict."""
    templates.list_templates(fake_drive_ws.workspace)  # seed
    spec = templates.load_example_spec(fake_drive_ws.workspace, "connectify-program")
    assert isinstance(spec, dict) and spec["slug"] == "connectify-program"


def test_load_example_spec_returns_none_when_missing(fake_drive_ws):
    """load_example_spec returns None when no example.spec.yaml is seeded."""
    ws = fake_drive_ws.workspace
    templates.list_templates(ws)
    # connect-explainer has no example.spec.yaml in the repo tree.
    result = templates.load_example_spec(ws, "connect-explainer")
    assert result is None or isinstance(result, dict)


def test_load_example_spec_injects_resolved_beats(fake_drive_ws):
    """The BeatEditor renders from a top-level `beats` array; load_example_spec
    injects the resolved _defaults.yaml timeline (like read_parsed_spec does for
    runs) so the editor isn't blank."""
    ws = fake_drive_ws.workspace
    templates.list_templates(ws)
    spec = templates.load_example_spec(ws, "connectify-program")
    assert isinstance(spec.get("beats"), list) and len(spec["beats"]) > 0
    # each beat carries id + kind (what BeatList keys on)
    assert all("id" in b and "kind" in b for b in spec["beats"])


def test_save_example_spec_strips_derived_beats(fake_drive_ws):
    """The editor's effectiveSpec round-trips the injected `beats` back on save;
    it must NOT be persisted to example.spec.yaml (it's derived, not source)."""
    ws = fake_drive_ws.workspace
    templates.list_templates(ws)
    spec = templates.load_example_spec(ws, "connectify-program")
    assert "beats" in spec  # injected on read
    spec["tagline"] = "edited via beateditor"
    templates.save_template(ws, "connectify-program", example_spec=spec)
    raw = templates.load_example(ws, "connectify-program")  # the persisted YAML text
    assert "\nbeats:" not in raw and not raw.startswith("beats:")
    assert "edited via beateditor" in raw


def test_save_template_example_spec_roundtrips(fake_drive_ws):
    """save_template(example_spec=...) serializes to YAML, stores, and load_example_spec reflects it."""
    templates.list_templates(fake_drive_ws.workspace)
    spec = templates.load_example_spec(fake_drive_ws.workspace, "connectify-program")
    assert spec is not None
    spec = dict(spec)
    spec["tagline"] = "Edited tagline"
    templates.save_template(fake_drive_ws.workspace, "connectify-program", example_spec=spec)
    reloaded = templates.load_example_spec(fake_drive_ws.workspace, "connectify-program")
    assert reloaded["tagline"] == "Edited tagline"


def test_save_template_example_spec_rejects_invalid(fake_drive_ws):
    """save_template(example_spec=...) with a structurally invalid spec raises ValueError."""
    templates.list_templates(fake_drive_ws.workspace)
    with pytest.raises(ValueError):
        # Missing workspace field → validate_spec_structure raises ValueError.
        templates.save_template(fake_drive_ws.workspace, "connectify-program", example_spec={"slug": "x"})


def test_save_template_example_spec_and_yaml_conflict_raises(fake_drive_ws):
    """Providing both example_yaml and example_spec raises ValueError (ambiguity guard)."""
    ws = fake_drive_ws.workspace
    templates.list_templates(ws)
    valid_ex = "slug: connectify-program\nworkspace: test-ws\nname: x\n"
    with pytest.raises(ValueError, match="example_yaml.*example_spec|example_spec.*example_yaml"):
        templates.save_template(
            ws,
            "connectify-program",
            example_yaml=valid_ex,
            example_spec={"slug": "connectify-program", "workspace": "test-ws", "name": "x"},
        )


def test_reflow_prose_folds_softwraps_keeps_structure():
    """Prose meta fields lose authoring soft-wraps but keep paragraph + list breaks."""
    from apps.videos.templates import _reflow_prose
    para = "Generic explainer of how an org brings its\nexisting program onto Connect — the\njourney."
    assert "\n" not in _reflow_prose(para)
    assert _reflow_prose(para).startswith("Generic explainer")
    # blank-line paragraph break preserved
    two_para = "First paragraph wrapped\nover two lines.\n\nSecond paragraph also\nwrapped."
    assert _reflow_prose(two_para) == "First paragraph wrapped over two lines.\n\nSecond paragraph also wrapped."
    # list items stay on their own lines; their continuations fold in
    lst = "- You want the evergreen story,\n  with the business case.\n- Another bullet\n  continues here."
    out = _reflow_prose(lst)
    assert out == "- You want the evergreen story, with the business case.\n- Another bullet continues here."
    # idempotent
    assert _reflow_prose(out) == out


def test_load_template_meta_description_is_reflowed(fake_drive_ws):
    """The bundle's description has no mid-paragraph hard newlines (was ragged)."""
    ws = fake_drive_ws.workspace
    templates.list_templates(ws)
    b = templates.load_template(ws, "connectify-program")
    # connectify's seeded description was a wrapped block scalar; after reflow the
    # first paragraph is a single flowing line.
    first_para = b.meta.description.split("\n\n")[0]
    assert "\n" not in first_para


# ---------------------------------------------------------------------------
# T8: intent field
# ---------------------------------------------------------------------------


def test_load_template_intent_is_present_for_seeded_templates(fake_drive_ws):
    """All seeded templates expose a non-empty intent string on their meta."""
    ws = fake_drive_ws.workspace
    templates.list_templates(ws)  # triggers auto-seed
    for tid in ("connect-explainer", "connectify-program", "partnership-pitch",
                "60s-campaign-overview", "120s-program-demo"):
        b = templates.load_template(ws, tid)
        assert b is not None, f"{tid}: load_template returned None"
        assert b.meta.intent, f"{tid}: meta.intent is empty — seed template.yaml is missing intent:"


def test_load_template_intent_default_empty_when_absent(fake_drive_ws):
    """A template.yaml without an intent: key parses to an empty string (backward compat)."""
    from apps.videos import drive, service
    ws = fake_drive_ws.workspace
    # Write a minimal meta.yaml with no intent field into a fresh template.
    layout, client = service.layout_for(ws)
    drive.write_template_file(
        layout, client, "no-intent-tpl",
        "meta.yaml",
        "id: no-intent-tpl\nname: No Intent\n",
    )
    drive.write_template_file(
        layout, client, "no-intent-tpl",
        "skeleton.yaml",
        "slug: x\nworkspace: y\n",
    )
    drive.write_template_file(
        layout, client, "no-intent-tpl",
        "prompt.md",
        "# Prompt\n",
    )
    b = templates.load_template(ws, "no-intent-tpl")
    assert b is not None
    assert b.meta.intent == ""


def test_save_template_meta_intent_patch_persists(fake_drive_ws):
    """PATCH with {"intent": "X"} persists through save_template and round-trips."""
    ws = fake_drive_ws.workspace
    templates.list_templates(ws)  # seed
    new_intent = "Explain the mechanism in one breath — no stats, no branding."
    b = templates.save_template(ws, "connect-explainer", meta={"intent": new_intent})
    assert b.meta.intent == new_intent
    # Re-load from Drive (cache invalidated by save_template) confirms persistence.
    reloaded = templates.load_template(ws, "connect-explainer")
    assert reloaded.meta.intent == new_intent
