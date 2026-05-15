"""Video-spec templates: discovery + skeleton loading.

A template is a directory under
``video-production/connect-videos/templates/<template-id>/`` containing:

  template.yaml        — metadata (id, name, description, duration)
  spec.template.yaml   — YAML skeleton with {{placeholders}}
  generate.prompt.md   — LLM instructions for filling the placeholders

The structured-editor follow-up plan may grow this to support
multi-stage generation flows. For now the shape is intentionally flat.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

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


def list_templates() -> list[TemplateMeta]:
    """All template metas discoverable under ACE_VIDEOS_ROOT/templates."""
    root = _templates_dir()
    if not root.exists():
        return []
    out: list[TemplateMeta] = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir() or not is_valid_template_id(entry.name):
            continue
        meta_path = entry / "template.yaml"
        if not meta_path.exists():
            continue
        out.append(_load_meta(entry.name, meta_path))
    return out


def load_template(template_id: str) -> TemplateBundle | None:
    """Load skeleton + prompt for a specific template."""
    if not is_valid_template_id(template_id):
        return None
    root = _templates_dir() / template_id
    if not root.is_dir():
        return None
    meta_path = root / "template.yaml"
    spec_path = root / "spec.template.yaml"
    prompt_path = root / "generate.prompt.md"
    if not meta_path.exists() or not spec_path.exists() or not prompt_path.exists():
        return None
    return TemplateBundle(
        meta=_load_meta(template_id, meta_path),
        skeleton_yaml=spec_path.read_text(encoding="utf-8"),
        prompt_md=prompt_path.read_text(encoding="utf-8"),
    )


def _load_meta(template_id: str, meta_path: Path) -> TemplateMeta:
    raw = _yaml().load(meta_path.read_text(encoding="utf-8")) or {}
    return TemplateMeta(
        id=str(raw.get("id") or template_id),
        name=str(raw.get("name") or template_id),
        description=str(raw.get("description") or "").strip(),
        expected_duration_seconds=int(raw.get("expected_duration_seconds") or 60),
        intended_audience=str(raw.get("intended_audience") or "").strip(),
        when_to_use=str(raw.get("when_to_use") or "").strip(),
    )
