"""Tests for apps.videos.templates — discovery + loading.

Covers the 3-file template kit (meta + prompt + example) loaded through
Drive, plus the Drive-backed template helpers (templates_folder_id,
list_template_ids, read_template_file, write_template_file) using the same
FakeDriveClient the service tests use.

(The old skeleton.yaml + its author-time doc-comment stripping were removed:
the example.spec.yaml is now the single source of truth for a template's
spec shape — see apps/videos/templates.py.)
"""
from __future__ import annotations

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


def test_load_template_carries_example_yaml(fake_drive_ws):
    """load_template returns the canonical example spec as example_yaml."""
    templates.list_templates(fake_drive_ws.workspace)  # triggers lazy auto-seed
    bundle = templates.load_template(fake_drive_ws.workspace, "program-designer")
    assert bundle is not None
    assert bundle.example_yaml is not None
    # The example is a real, filled spec for this template.
    assert "slug: program-designer" in bundle.example_yaml


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
    assert {"connect-explainer", "program-designer", "partnership-pitch", "llo-deliver"} <= set(ids)

    # The example spec is seeded as "example.spec.yaml" (no skeleton anymore).
    example = drive.read_template_file(layout, client, "program-designer", "example.spec.yaml")
    assert example is not None
    assert "active_cut" in example


def test_seed_templates_is_idempotent(fake_drive_ws):
    """seed_templates skips templates already present in Drive; second call returns 0."""
    templates.seed_templates(fake_drive_ws.workspace)
    assert templates.seed_templates(fake_drive_ws.workspace) == 0


def _drop_template_file(fake_ws, template_id: str, name: str) -> None:
    """Delete one file out of a seeded Drive kit, leaving the kit folder.

    Reproduces the ace-web#679 state: the kit exists, one of its three files
    does not.
    """
    path = f"workspace-root/videos/_templates/{template_id}/{name}"
    fake_ws.client.trash_folder(fake_ws.client.file_id(path))


def test_seed_templates_backfills_a_missing_file_in_an_existing_kit(fake_drive_ws):
    """Regression (ace-web#679): a kit whose folder exists but is missing
    example.spec.yaml gets that one file restored.

    The old per-kit skip made this unrepairable — the folder was present, so
    seeding skipped the kit and the missing file 404'd forever.
    """
    from apps.videos import service

    templates.seed_templates(fake_drive_ws.workspace)
    layout, client = service.layout_for(fake_drive_ws.workspace)

    _drop_template_file(fake_drive_ws, "120s-program-demo", "example.spec.yaml")
    assert drive.read_template_file(
        layout, client, "120s-program-demo", "example.spec.yaml"
    ) is None

    assert templates.seed_templates(fake_drive_ws.workspace) == 1

    restored = drive.read_template_file(
        layout, client, "120s-program-demo", "example.spec.yaml"
    )
    assert restored is not None
    assert restored.strip()


def test_seed_templates_backfill_leaves_edited_files_alone(fake_drive_ws):
    """Backfill must not overwrite a kit file that was edited through the UI —
    Drive is the source of truth for an existing file."""
    from apps.videos import service

    templates.seed_templates(fake_drive_ws.workspace)
    layout, client = service.layout_for(fake_drive_ws.workspace)

    drive.write_template_file(
        layout, client, "120s-program-demo", "prompt.md", "EDITED BY A HUMAN"
    )
    _drop_template_file(fake_drive_ws, "120s-program-demo", "example.spec.yaml")

    templates.seed_templates(fake_drive_ws.workspace)

    assert drive.read_template_file(
        layout, client, "120s-program-demo", "prompt.md"
    ) == "EDITED BY A HUMAN"
    assert drive.read_template_file(
        layout, client, "120s-program-demo", "example.spec.yaml"
    ) is not None


def test_seed_templates_backfill_counts_only_repaired_kits(fake_drive_ws):
    """The return value counts kits created or repaired — untouched kits
    don't inflate it."""
    templates.seed_templates(fake_drive_ws.workspace)
    _drop_template_file(fake_drive_ws, "120s-program-demo", "example.spec.yaml")
    _drop_template_file(fake_drive_ws, "60s-campaign-overview", "example.spec.yaml")

    assert templates.seed_templates(fake_drive_ws.workspace) == 2
    assert templates.seed_templates(fake_drive_ws.workspace) == 0


def test_template_file_exists_is_metadata_only(fake_drive_ws):
    """drive.template_file_exists reports presence without reading a body."""
    from apps.videos import service

    templates.seed_templates(fake_drive_ws.workspace)
    layout, client = service.layout_for(fake_drive_ws.workspace)

    assert drive.template_file_exists(
        layout, client, "120s-program-demo", "example.spec.yaml"
    )
    _drop_template_file(fake_drive_ws, "120s-program-demo", "example.spec.yaml")
    assert not drive.template_file_exists(
        layout, client, "120s-program-demo", "example.spec.yaml"
    )
    assert not drive.template_file_exists(layout, client, "no-such-kit", "meta.yaml")


# ---------------------------------------------------------------------------
# T3: Drive-backed read-through + cache + lazy auto-seed
# ---------------------------------------------------------------------------


def test_list_templates_lazy_autoseeds_from_drive(fake_drive_ws):
    """list_templates auto-seeds from the repo tree when Drive has no templates."""
    metas = templates.list_templates(fake_drive_ws.workspace)   # no explicit seed
    ids = {m.id for m in metas}
    assert {"connect-explainer", "program-designer", "partnership-pitch", "llo-deliver"} <= ids


def test_load_template_from_drive(fake_drive_ws):
    """load_template reads from Drive after seeding."""
    templates.list_templates(fake_drive_ws.workspace)  # seed
    b = templates.load_template(fake_drive_ws.workspace, "program-designer")
    assert b is not None
    assert b.example_yaml is not None and "active_cut" in b.example_yaml
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
    b1 = templates.load_template(fake_drive_ws.workspace, "program-designer")
    assert b1 is not None
    with mock.patch.object(drive, "read_template_file") as spy:
        b2 = templates.load_template(fake_drive_ws.workspace, "program-designer")
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
    templates.load_template(fake_drive_ws.workspace, "program-designer")
    ws_slug = fake_drive_ws.workspace.slug
    assert vcache.get_tpl_bundle(ws_slug, "program-designer") is not None
    assert vcache.get_tpl_list(ws_slug) is not None
    vcache.invalidate_tpl(ws_slug, "program-designer")
    assert vcache.get_tpl_bundle(ws_slug, "program-designer") is None
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
    """load_example returns the seeded example for program-designer."""
    ws = fake_drive_ws.workspace
    templates.list_templates(ws)  # triggers auto-seed which uploads example.spec.yaml too
    ex = templates.load_example(ws, "program-designer")
    assert ex and "slug: program-designer" in ex


def test_load_example_returns_none_when_missing(fake_drive_ws):
    """load_example returns None for a template with no example.spec.yaml."""
    ws = fake_drive_ws.workspace
    templates.list_templates(ws)
    # A template id that was never seeded has no files at all in Drive.
    ex = templates.load_example(ws, "no-such-template")
    assert ex is None


# ---------------------------------------------------------------------------
# T7: load_example_spec + save_template(example_spec=...)
# ---------------------------------------------------------------------------


def test_load_example_spec_parsed(fake_drive_ws):
    """load_example_spec returns the example as a parsed dict."""
    templates.list_templates(fake_drive_ws.workspace)  # seed
    spec = templates.load_example_spec(fake_drive_ws.workspace, "program-designer")
    assert isinstance(spec, dict) and spec["slug"] == "program-designer"


def test_load_example_spec_returns_none_when_missing(fake_drive_ws):
    """load_example_spec returns None for a template with no example.spec.yaml."""
    ws = fake_drive_ws.workspace
    templates.list_templates(ws)
    result = templates.load_example_spec(ws, "no-such-template")
    assert result is None


def test_load_example_spec_injects_filtered_default_beats(fake_drive_ws):
    """When example.spec.yaml carries no `beats:`, load_example_spec injects the
    DEFAULT starter timeline FILTERED to the spec's content (mirrors
    beats.ts::filterDefaultsForSpec) so the editor shows exactly what renders.
    program-designer has ai_build + impact but NO problem block, so the
    body_problem_stat beat must be absent."""
    ws = fake_drive_ws.workspace
    templates.list_templates(ws)
    spec = templates.load_example_spec(ws, "program-designer")
    assert isinstance(spec.get("beats"), list) and len(spec["beats"]) > 0
    assert all("id" in b and "kind" in b for b in spec["beats"])
    kinds = [b["kind"] for b in spec["beats"]]
    assert "body_problem_stat" not in kinds  # no problem block → dropped
    assert "body_ai_build" in kinds          # ai_build + active_cut ai → kept
    assert "body_impact_stats" in kinds      # impact block → kept


def test_save_example_spec_persists_beats(fake_drive_ws):
    """Structure belongs to the template: the editor's add/remove/reorder beat
    edits must round-trip to disk. So `beats` is now PERSISTED (no longer
    stripped as a derived field)."""
    ws = fake_drive_ws.workspace
    templates.list_templates(ws)
    spec = templates.load_example_spec(ws, "program-designer")
    assert "beats" in spec  # injected on first read (filtered default timeline)
    spec["tagline"] = "edited via beateditor"
    templates.save_template(ws, "program-designer", example_spec=spec)
    raw = templates.load_example(ws, "program-designer")  # the persisted YAML text
    assert "beats:" in raw          # now persisted
    assert "edited via beateditor" in raw
    # And on reload the template carries its OWN beats (not re-injected).
    reloaded = templates.load_example_spec(ws, "program-designer")
    assert isinstance(reloaded.get("beats"), list) and len(reloaded["beats"]) > 0


def test_save_template_example_spec_roundtrips(fake_drive_ws):
    """save_template(example_spec=...) serializes to YAML, stores, and load_example_spec reflects it."""
    templates.list_templates(fake_drive_ws.workspace)
    spec = templates.load_example_spec(fake_drive_ws.workspace, "program-designer")
    assert spec is not None
    spec = dict(spec)
    spec["tagline"] = "Edited tagline"
    templates.save_template(fake_drive_ws.workspace, "program-designer", example_spec=spec)
    reloaded = templates.load_example_spec(fake_drive_ws.workspace, "program-designer")
    assert reloaded["tagline"] == "Edited tagline"


def test_save_template_example_spec_rejects_invalid(fake_drive_ws):
    """save_template(example_spec=...) with a structurally invalid spec raises ValueError."""
    templates.list_templates(fake_drive_ws.workspace)
    with pytest.raises(ValueError):
        # Missing workspace field → validate_spec_structure raises ValueError.
        templates.save_template(fake_drive_ws.workspace, "program-designer", example_spec={"slug": "x"})


def test_save_template_example_spec_and_yaml_conflict_raises(fake_drive_ws):
    """Providing both example_yaml and example_spec raises ValueError (ambiguity guard)."""
    ws = fake_drive_ws.workspace
    templates.list_templates(ws)
    valid_ex = "slug: program-designer\nworkspace: test-ws\nname: x\n"
    with pytest.raises(ValueError, match="example_yaml.*example_spec|example_spec.*example_yaml"):
        templates.save_template(
            ws,
            "program-designer",
            example_yaml=valid_ex,
            example_spec={"slug": "program-designer", "workspace": "test-ws", "name": "x"},
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
    b = templates.load_template(ws, "program-designer")
    # program-designer's seeded description was a wrapped block scalar; after reflow the
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
    for tid in ("connect-explainer", "program-designer", "partnership-pitch", "llo-deliver",
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
        "example.spec.yaml",
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
