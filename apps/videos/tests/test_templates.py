"""Tests for apps.videos.templates — discovery + skeleton loading.

Focus: the load_template path strips the skeleton's author-time doc
comment block before returning, so substituting placeholders into the
output doesn't leave garbled comments referencing the placeholders
themselves.
"""
from __future__ import annotations

import textwrap

from apps.videos import templates


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
