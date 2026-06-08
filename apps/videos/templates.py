"""Video-spec templates: discovery + skeleton loading.

Templates are stored in Drive under each workspace's
``videos/_templates/<template-id>/`` folder, with these files:

  meta.yaml       — metadata (id, name, description, duration, …)
  skeleton.yaml   — YAML skeleton with {{placeholders}}
  prompt.md       — LLM instructions for filling the placeholders
  example.spec.yaml (optional)

The repo tree under ``video-production/connect-videos/templates/<id>/``
is the seed source (T2: ``seed_templates``). The Drive copy is the
runtime source of truth (T3: ``list_templates`` / ``load_template``).

Lazy auto-seed: if a workspace has no templates in Drive yet,
``list_templates`` calls ``seed_templates`` automatically and then
re-lists from Drive.
"""
from __future__ import annotations

import dataclasses
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from django.conf import settings
from ruamel.yaml import YAML


def _yaml() -> YAML:
    y = YAML(typ="safe")
    return y


def _templates_dir() -> Path:
    return Path(settings.ACE_VIDEOS_ROOT) / "templates"


@dataclass(frozen=True)
class TemplateMeta:
    id: str
    name: str
    description: str
    expected_duration_seconds: int
    intended_audience: str
    when_to_use: str


@dataclass(frozen=True)
class TemplateBundle:
    """A loaded template: metadata + skeleton + prompt."""

    meta: TemplateMeta
    skeleton_yaml: str
    prompt_md: str


_TEMPLATE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


def is_valid_template_id(template_id: str) -> bool:
    return bool(_TEMPLATE_ID_RE.match(template_id))


def list_templates(workspace) -> list[TemplateMeta]:
    """All template metas for this workspace, read from Drive with caching.

    Lazy auto-seed: if Drive has no templates yet, uploads the repo tree
    via seed_templates and then re-lists. Returns sorted by id.
    """
    from apps.videos import cache as vcache, drive, service  # lazy — avoid circulars

    ws_slug = workspace.slug
    cached = vcache.get_tpl_list(ws_slug)
    if cached is not None:
        return [_meta_from_dict(d) for d in cached]

    layout, client = service.layout_for(workspace)
    ids = drive.list_template_ids(layout, client)

    # Lazy auto-seed: seed from repo tree if Drive has nothing yet.
    if not ids:
        seed_templates(workspace)
        ids = drive.list_template_ids(layout, client)

    metas: list[TemplateMeta] = []
    for tid in sorted(ids):
        raw = drive.read_template_file(layout, client, tid, "meta.yaml")
        if raw is None:
            continue
        metas.append(_parse_meta(tid, raw))

    vcache.set_tpl_list(ws_slug, [dataclasses.asdict(m) for m in metas])
    return metas


def load_template(workspace, template_id: str) -> TemplateBundle | None:
    """Load skeleton + prompt for a specific template from Drive, with caching.

    Returns None if the template is not found in Drive.
    """
    if not is_valid_template_id(template_id):
        return None

    from apps.videos import cache as vcache, drive, service  # lazy — avoid circulars

    ws_slug = workspace.slug
    cached = vcache.get_tpl_bundle(ws_slug, template_id)
    if cached is not None:
        return _bundle_from_dict(cached)

    layout, client = service.layout_for(workspace)
    meta_raw = drive.read_template_file(layout, client, template_id, "meta.yaml")
    if meta_raw is None:
        return None
    skeleton_raw = drive.read_template_file(layout, client, template_id, "skeleton.yaml")
    if skeleton_raw is None:
        return None
    prompt_raw = drive.read_template_file(layout, client, template_id, "prompt.md")
    if prompt_raw is None:
        return None

    bundle = TemplateBundle(
        meta=_parse_meta(template_id, meta_raw),
        skeleton_yaml=_strip_leading_doc_comments(skeleton_raw),
        prompt_md=prompt_raw,
    )
    vcache.set_tpl_bundle(ws_slug, template_id, _bundle_to_dict(bundle))
    return bundle


def load_example(workspace, template_id: str) -> str | None:
    """Return the raw text of example.spec.yaml for this template, or None.

    Reads from Drive; does NOT cache (examples are rarely accessed and
    small — no benefit to polluting the cache namespace).
    """
    if not is_valid_template_id(template_id):
        return None

    from apps.videos import drive, service  # lazy — avoid circulars

    layout, client = service.layout_for(workspace)
    return drive.read_template_file(layout, client, template_id, "example.spec.yaml")


def save_template(
    workspace,
    template_id: str,
    *,
    meta: dict | None = None,
    skeleton_yaml: str | None = None,
    prompt_md: str | None = None,
    example_yaml: str | None = None,
) -> TemplateBundle:
    """Persist one or more template fields to Drive and return the refreshed bundle.

    For each non-None argument:
      - ``skeleton_yaml`` / ``example_yaml``: must parse as a YAML mapping.
        ``example_yaml`` additionally passes program-spec structural validation
        (slug + workspace present) so saved examples can always be rendered.
      - ``meta``: a dict of override key/values merged into the existing
        meta.yaml (round-tripped via the YAML library).

    Raises ``ValueError`` if any validation fails or if the template has no
    existing meta.yaml in Drive (i.e. the template does not exist).

    After writing, invalidates the relevant cache entries and returns the
    freshly re-read bundle.
    """
    if not is_valid_template_id(template_id):
        raise ValueError(f"Invalid template id: {template_id!r}")

    from apps.videos import cache as vcache, drive, service  # lazy — avoid circulars

    layout, client = service.layout_for(workspace)

    # Guard: template must exist.
    existing_meta_raw = drive.read_template_file(layout, client, template_id, "meta.yaml")
    if existing_meta_raw is None:
        raise ValueError(f"Template {template_id!r} does not exist in Drive")

    if skeleton_yaml is not None:
        try:
            doc = _yaml().load(skeleton_yaml)
        except Exception as e:
            raise ValueError(f"skeleton_yaml is not valid YAML: {e}") from e
        if not isinstance(doc, dict):
            raise ValueError("skeleton_yaml must parse to a YAML mapping at the top level")
        drive.write_template_file(layout, client, template_id, "skeleton.yaml", skeleton_yaml)

    if prompt_md is not None:
        drive.write_template_file(layout, client, template_id, "prompt.md", prompt_md)

    if example_yaml is not None:
        try:
            doc = _yaml().load(example_yaml)
        except Exception as e:
            raise ValueError(f"example_yaml is not valid YAML: {e}") from e
        if not isinstance(doc, dict):
            raise ValueError("example_yaml must parse to a YAML mapping at the top level")
        # Structural program-spec validation — ensures the example can be
        # rendered without further edits. Delegates to the same
        # validate_spec_structure helper that create_program_from_spec uses.
        from apps.videos.service import validate_spec_structure
        validate_spec_structure(example_yaml)
        drive.write_template_file(layout, client, template_id, "example.spec.yaml", example_yaml)

    if meta is not None:
        existing = _yaml().load(existing_meta_raw) or {}
        existing.update(meta)
        import io as _io
        y = _yaml()
        buf = _io.StringIO()
        y.dump(existing, buf)
        updated_meta_raw = buf.getvalue()
        drive.write_template_file(layout, client, template_id, "meta.yaml", updated_meta_raw)

    vcache.invalidate_tpl(workspace.slug, template_id)

    bundle = load_template(workspace, template_id)
    if bundle is None:  # pragma: no cover — shouldn't happen; we just wrote the files
        raise ValueError(f"Failed to re-read template {template_id!r} after save")
    return bundle


def _strip_leading_doc_comments(skeleton: str) -> str:
    """Drop the skeleton's authoring-time doc header before returning it.

    The on-disk ``spec.template.yaml`` opens with a comment block that
    documents every ``{{placeholder}}`` — useful for template authors,
    but harmful in the generated output because the substitution
    replaces those documentation references too, leaving a garbled
    header like::

        #   kangaroo-mother-care            slug, lowercase + hyphens (e.g. "kangaroo-care")

    Strip everything from the start of the file up to (and including)
    the first blank line that follows a comment run. The remaining
    skeleton starts directly at the first real YAML field. Templates
    that don't have a leading comment block are returned unchanged.
    """
    lines = skeleton.splitlines(keepends=True)
    if not lines or not lines[0].lstrip().startswith("#"):
        return skeleton
    i = 0
    n = len(lines)
    while i < n and (lines[i].lstrip().startswith("#") or lines[i].strip() == ""):
        i += 1
    return "".join(lines[i:])


_FILE_MAP: dict[str, str] = {
    "template.yaml": "meta.yaml",
    "spec.template.yaml": "skeleton.yaml",
    "generate.prompt.md": "prompt.md",
    "example.spec.yaml": "example.spec.yaml",
}


def seed_templates(workspace) -> int:
    """Upload the repo template tree to this workspace's Drive _templates/,
    renaming files per _FILE_MAP. Idempotent: skip template ids already
    present in Drive. Returns the number of templates seeded.
    """
    from apps.videos import drive, service  # lazy to avoid circular imports

    layout, client = service.layout_for(workspace)
    existing_ids = set(drive.list_template_ids(layout, client))

    root = _templates_dir()
    if not root.exists():
        return 0

    seeded = 0
    for entry in sorted(root.iterdir()):
        if not entry.is_dir() or not is_valid_template_id(entry.name):
            continue
        if entry.name in existing_ids:
            continue
        # Upload each file in the _FILE_MAP that is present on disk.
        for repo_name, drive_name in _FILE_MAP.items():
            src = entry / repo_name
            if not src.exists():
                continue
            drive.write_template_file(
                layout, client, entry.name, drive_name, src.read_text(encoding="utf-8")
            )
        seeded += 1

    return seeded


def _load_meta(template_id: str, meta_path: Path) -> TemplateMeta:
    """Load TemplateMeta from a filesystem Path (used by seed_templates)."""
    return _parse_meta(template_id, meta_path.read_text(encoding="utf-8"))


def _parse_meta(template_id: str, yaml_text: str) -> TemplateMeta:
    """Parse TemplateMeta from raw YAML text (used by Drive-backed loaders)."""
    raw: dict[str, Any] = _yaml().load(yaml_text) or {}
    return TemplateMeta(
        id=str(raw.get("id") or template_id),
        name=str(raw.get("name") or template_id),
        description=str(raw.get("description") or "").strip(),
        expected_duration_seconds=int(raw.get("expected_duration_seconds") or 60),
        intended_audience=str(raw.get("intended_audience") or "").strip(),
        when_to_use=str(raw.get("when_to_use") or "").strip(),
    )


# ---------------------------------------------------------------------------
# Cache serialisation helpers
# ---------------------------------------------------------------------------


def _meta_from_dict(d: dict) -> TemplateMeta:
    return TemplateMeta(**d)


def _bundle_to_dict(bundle: TemplateBundle) -> dict:
    return {
        "meta": dataclasses.asdict(bundle.meta),
        "skeleton_yaml": bundle.skeleton_yaml,
        "prompt_md": bundle.prompt_md,
    }


def _bundle_from_dict(d: dict) -> TemplateBundle:
    return TemplateBundle(
        meta=TemplateMeta(**d["meta"]),
        skeleton_yaml=d["skeleton_yaml"],
        prompt_md=d["prompt_md"],
    )
