"""Reading ACE-authored prose out of Drive.

Everything ACE writes lands as a Google Doc, and Drive's default export
for a Google Doc is ``text/plain`` — which renders `-` bullets as `*` and
drops `**bold**` and `#` headings entirely. A reader keyed on markdown
markers is then parsing a document whose markers were removed in transit.

The rule is name-gated on purpose: `run_state.yaml`, `decisions.yaml` and
every verdict are Google Docs too, and a markdown export escapes their
content (``\\---``, ``run\\_id``) and breaks the YAML parse outright.
"""
from __future__ import annotations

import pytest

from apps.opps.drive_export import (
    GOOGLE_DOC_MIME,
    MARKDOWN_EXPORT,
    prose_export_mime,
    read_prose,
    unescape_markdown,
)
from apps.opps.summary import _parse_open_questions

# What Drive's text/plain export makes of a rendered gdoc: `-` becomes
# `*`, the bold markers are gone. Captured from the live doc
# 1Wxwz0ddS23FUeXIkmiJv6oB-Njb992HBf8ozZQ04lbU (spark-facilitator).
PLAIN_EXPORT = (
    "\ufeffOpen Questions — spark-facilitator / 20260813-2126\n"
    "Seeded from the approved PDD's § Open Questions (Phase 1).\n"
    "\n"
    "* Device reality per CBF — whether every pilot CBF carries a capable "
    "Android device is undocumented. Owner: responding LLO. Answered in: the "
    "LLO's solicitation response (Phase 8).\n"
    "* Rate confirmation — the USD 2–5 per-meeting band is ACE-inferred. "
    "Owner: responding LLO + Spark. Answered in: solicitation response "
    "(Phase 8).\n"
)

# The same doc exported as text/markdown: structure intact, punctuation
# backslash-escaped.
MARKDOWN_EXPORT_BODY = (
    "# Open Questions — spark-facilitator / 20260813-2126\n"
    "\n"
    "Seeded from the approved PDD's § Open Questions (Phase 1).\n"
    "\n"
    "- **Device reality per CBF** — whether every pilot CBF carries a capable "
    "Android device is undocumented. Owner: responding LLO. Answered in: the "
    "LLO's solicitation response (Phase 8).  \n"
    "- **Rate confirmation** — the USD 2–5 per-meeting band is ACE-inferred. "
    "Owner: responding LLO \\+ Spark. Answered in: solicitation response "
    "(Phase 8).  \n"
)


class TestProseExportMime:
    @pytest.mark.parametrize("name", ["open-questions.md", "PDD.MD", "notes.markdown"])
    def test_prose_named_google_docs_read_as_markdown(self, name):
        assert prose_export_mime(name, GOOGLE_DOC_MIME) == MARKDOWN_EXPORT

    @pytest.mark.parametrize(
        "name",
        ["run_state.yaml", "decisions.yaml", "opp.yaml", "idea-to-pdd_verdict.yaml"],
    )
    def test_yaml_google_docs_keep_the_plain_default(self, name):
        """A markdown export escapes YAML (``\\---``, ``run\\_id``) and
        breaks the parse. This is why the rule is not global."""
        assert prose_export_mime(name, GOOGLE_DOC_MIME) is None

    def test_non_google_files_are_never_re_exported(self):
        assert prose_export_mime("pdd.md", "text/markdown") is None
        assert prose_export_mime("clip.mp4", "video/mp4") is None


class TestUnescapeMarkdown:
    def test_it_undoes_googles_prose_escaping(self):
        assert unescape_markdown(r"responding LLO \+ Spark") == "responding LLO + Spark"
        assert unescape_markdown(r"run\_id 2\. x") == "run_id 2. x"

    def test_it_leaves_ordinary_prose_alone(self):
        text = "C:\\Users is not markdown, and 2+2 is fine."
        assert unescape_markdown(text) == text


class TestReadProse:
    def test_a_prose_gdoc_is_read_as_unescaped_markdown(self):
        class FakeDrive:
            def get_content(self, file_id, mime_type, *, export_as=None):
                from apps.opps.drive_client import FileContent
                assert export_as == MARKDOWN_EXPORT
                return FileContent(content=r"- **A** — b \+ c", content_type=export_as)

        class F:
            id, name, mime_type = "f1", "open-questions.md", GOOGLE_DOC_MIME

        assert read_prose(FakeDrive(), F()) == "- **A** — b + c"

    def test_a_yaml_gdoc_falls_through_to_the_default_read(self):
        class FakeDrive:
            def get_content(self, file_id, mime_type, *, export_as=None):
                from apps.opps.drive_client import FileContent
                assert export_as is None
                return FileContent(content="run_id: x", content_type="text/plain")

        class F:
            id, name, mime_type = "f1", "run_state.yaml", GOOGLE_DOC_MIME

        assert read_prose(FakeDrive(), F()) == "run_id: x"


class TestOpenQuestionsParsesEitherExport:
    """The reported symptom was "0 open questions on the live summary".
    It does NOT reproduce — plain text happens to keep `* ` and the em
    dash, which is all the parser needs, so it parses today by luck. This
    locks BOTH exports to the same result so the markdown switch is a
    hardening rather than a trade of one mangling for another.
    """

    def test_both_exports_yield_the_same_items(self):
        plain = _parse_open_questions(PLAIN_EXPORT)
        md = _parse_open_questions(unescape_markdown(MARKDOWN_EXPORT_BODY))
        assert [i["title"] for i in plain] == [
            "Device reality per CBF", "Rate confirmation",
        ]
        assert plain == md

    def test_the_markdown_export_escaping_would_otherwise_leak(self):
        """Without `unescape_markdown` the switch would ship `LLO \\+
        Spark` to a partner — a worse defect than the one it fixes."""
        leaked = _parse_open_questions(MARKDOWN_EXPORT_BODY)
        assert leaked[1]["owner"] == r"responding LLO \+ Spark"
