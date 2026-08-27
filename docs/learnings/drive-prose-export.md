# Reading ACE prose out of Drive

**Status:** shipped 2026-08-14. **Code:** `apps/opps/drive_export.py`.

Everything the ACE plugin writes to Drive lands as a **Google Doc**,
whatever the filename says. Drive's default export for a Google Doc is
`text/plain`, and that export is lossy in exactly the way a markdown
parser cares about: a `-` bullet comes back as `*`, and `**bold**` and `#`
headings are **dropped entirely**.

```
text/plain      * Device reality per CBF — whether every pilot CBF …
text/markdown   - **Device reality per CBF** — whether every pilot CBF …
```

So a reader keyed on those markers is parsing a document whose markers
were removed in transit. It keeps working only for as long as whatever it
*does* still key on survives the flattening by accident. The plugin hit
the same class from the other side and fixed it the same way:
`idea-to-pdd-qa` anchored 5 of 8 checks on `^##\s+<Section>` while reading
the plain default, so a *correctly rendered* PDD would have failed its own
QA; its fix was an opt-in `exportAs` (ACE PR #1345 rendered those docs).

## The rule is name-gated, never global

`prose_export_mime(name, mime_type)` returns `text/markdown` only for a
Google Doc whose name ends in `.md` / `.markdown`. **Do not make this a
default.** `run_state.yaml`, `decisions.yaml`, `opp.yaml` and every
`*_verdict.yaml` are Google Docs too, and a markdown export escapes their
content (`\---`, `run\_id`, `2\.`) and breaks the YAML parse outright.

## Markdown export escapes prose, so unescape it

Google's markdown export backslash-escapes punctuation inside prose:
`Owner: responding LLO \+ Spark`. Shipping that to a partner is a worse
defect than the one the switch fixes, so `read_prose` runs the body
through `unescape_markdown`. A reader switched onto markdown export
without that is trading one mangling for another.

## What was actually broken, and what wasn't

The reported symptom — "the live summary returns `open_questions` with 0
items" — **did not reproduce**. The live payload for
`spark-facilitator/20260813-2126` returns all five questions with
title/detail/owner/answered_in, because plain text happens to keep `* `
and the em dash, which is all `_parse_open_questions` needs. (A likelier
explanation for an empty-looking section: Open questions renders on the
**Decisions tab**, not the overview.) The change is therefore hardening,
not a bug fix, and `test_drive_export.py` locks BOTH exports to the same
parsed items so it stays that way.

Readers switched: `open-questions.md` (`apps/opps/summary.py`) and
`pdd.md` / `idea.md` (`apps/opps/framework_reader.py`, whose body
`apps/opps/seed.py` fences as ```markdown). Deliberately NOT switched: the
artifact download path (`apps/opps/api.py`), which serves the file itself
rather than parsing it.
