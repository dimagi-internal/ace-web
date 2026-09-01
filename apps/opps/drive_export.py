"""Which export MIME to read an ACE-authored Drive document with.

Every artifact ACE writes to Drive lands as a **Google Doc**, whatever its
filename says. Drive's default export for a Google Doc is ``text/plain``,
and that export is lossy in exactly the way a markdown parser cares about:
it renders a ``-`` bullet as ``*`` and drops ``**bold**`` and ``#``
headings entirely. A reader that keys on those markers is then reading a
document whose markers were removed in transit — it works only for as long
as whatever it *does* still key on survives the flattening by accident.

The plugin hit the same class from the other side and fixed it the same
way: ``idea-to-pdd-qa`` anchored 5 of its 8 checks on ``^##\\s+<Section>``
while reading the plain default, so a *correctly rendered* PDD would have
failed its own QA. Its fix was an opt-in ``exportAs``.

**The rule here is name-gated, not global.** ``run_state.yaml``,
``decisions.yaml``, ``opp.yaml`` and every ``*_verdict.yaml`` are Google
Docs too, and ``text/markdown`` escapes their content (``\\---``,
``run\\_id``, ``2\\.`` …), which breaks YAML parsing outright. So: a
Google-native doc whose NAME ends in a prose extension reads as markdown;
everything else keeps the plain default.

Markdown export has its own tax — it escapes ``+``, ``_``, ``-`` and ``.``
inside prose (``LLO \\+ Spark``). ``unescape_markdown`` undoes that, and
is applied by the prose readers so switching a reader over is a
no-regression change rather than a trade of one mangling for another.
"""
from __future__ import annotations

import re

#: Export MIME for prose. Drive supports this for Google Docs.
MARKDOWN_EXPORT = "text/markdown"

GOOGLE_DOC_MIME = "application/vnd.google-apps.document"

#: Filename suffixes ACE uses for prose it authored as markdown.
PROSE_SUFFIXES = (".md", ".markdown")

# A backslash before an ASCII punctuation char is markdown's escape form.
# Google's markdown export applies it liberally inside prose.
#
# The class is CommonMark's escapable-punctuation set — what Drive's
# exporter actually emits — not a shorter hand-picked list. The list this
# used to carry omitted ``&``, and ``&`` is the one Drive escapes most
# often in real ACE prose: ``M&E``, ``Q&A`` and ``R&D`` all came back
# through here still reading ``M\&E``, and the public run-summary page
# rendered that escape verbatim to an external reader on 9 of the 28
# open-question rows of ``spark-facilitator/20260828-0703``.
#
# The same set is declared plugin-side as ``ESCAPED_PUNCTUATION`` in
# ACE's ``lib/open-questions-inline.ts``. The two are a matched pair
# reading the same documents, so they are kept identical deliberately.
_MD_ESCAPE_RE = re.compile(r"""\\([\\`*_{}\[\]()#+\-.!|~<>&$"'])""")


def prose_export_mime(name: str, mime_type: str) -> str | None:
    """``text/markdown`` for a Google Doc that is ACE prose; else ``None``.

    ``None`` means "read it the default way" — pass it straight through to
    ``get_content(export_as=...)``, which ignores a ``None``.
    """
    if mime_type != GOOGLE_DOC_MIME:
        return None
    if not str(name or "").lower().endswith(PROSE_SUFFIXES):
        return None
    return MARKDOWN_EXPORT


def unescape_markdown(text: str) -> str:
    """Undo markdown's backslash escapes.

    Google's ``text/markdown`` export escapes punctuation that could be
    read as syntax, so ``Owner: responding LLO + Spark`` comes back as
    ``Owner: responding LLO \\+ Spark``. Rendering that to a partner is a
    worse defect than the one switching exports fixes, so every prose
    reader runs its body through here.
    """
    return _MD_ESCAPE_RE.sub(r"\1", str(text or ""))


def read_prose(drive, file, *, unescape: bool = True) -> str:
    """Read a Drive file as prose — markdown export when it is ACE prose.

    ``file`` is a ``DriveFile`` (needs ``.id``, ``.name``, ``.mime_type``).
    Non-Google-native files and non-prose names fall through to the normal
    read, so this is safe to use wherever a body is about to be parsed or
    rendered as markdown.
    """
    export_as = prose_export_mime(file.name, file.mime_type)
    body = drive.get_content(file.id, file.mime_type, export_as=export_as).content or ""
    if export_as and unescape:
        body = unescape_markdown(body)
    return body
