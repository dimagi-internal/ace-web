"""Point a Google Doc's links and visible ids at a clone's own copies.

A cloned run's Docs are copied verbatim, so their hyperlinks and any Drive id
printed in their text still name the SOURCE run's files (dimagi-internal/ace#2607:
the partner-facing onboarding email linked the source FAQ, deck and quick
reference; the FLW guide hid 23 source screenshot links behind link text, so a
text export of it shows no id at all). A Doc cannot be rewritten as text — that
would flatten its formatting — so this builds Docs API ``batchUpdate`` requests
instead.

Pure: it reads a ``documents.get`` response and returns requests. ACE ships the
same logic in TypeScript (``lib/clone-readback.ts`` ``docTextAndLinks`` /
``docIdRewriteRequests``); keep the two in step.
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any


def id_pattern(ids: Iterable[str]) -> re.Pattern[str] | None:
    """One regex matching any of ``ids`` as a WHOLE id, longest first.

    Whole ids only: Drive ids are ``[A-Za-z0-9_-]``, so an id inside a longer
    token (or one id that is a prefix of another) must not match."""
    keys = [i for i in ids if i]
    if not keys:
        return None
    alternation = "|".join(re.escape(i) for i in sorted(keys, key=len, reverse=True))
    return re.compile(r"(?<![\w-])(" + alternation + r")(?![\w-])")


def text_and_links(doc: dict) -> tuple[str, list[dict[str, Any]]]:
    """The visible text of a Doc and every hyperlink in it.

    Walks the body, headers, footers and footnotes (a link outside the body
    needs its ``segmentId`` — the header/footer/footnote key — in the range),
    recursing into table cells and a table of contents. Each link is
    ``{"url", "startIndex", "endIndex", "segmentId"}`` (segmentId None in the
    body)."""
    parts: list[str] = []
    links: list[dict[str, Any]] = []

    def walk(content, segment_id: str | None) -> None:
        for el in content or []:
            for pe in (el.get("paragraph") or {}).get("elements") or []:
                tr = pe.get("textRun") or {}
                if tr.get("content"):
                    parts.append(tr["content"])
                url = ((tr.get("textStyle") or {}).get("link") or {}).get("url")
                if url:
                    links.append({
                        "url": url,
                        "startIndex": pe.get("startIndex", 0),
                        "endIndex": pe.get("endIndex", 0),
                        "segmentId": segment_id,
                    })
            for row in (el.get("table") or {}).get("tableRows") or []:
                for cell in row.get("tableCells") or []:
                    walk(cell.get("content"), segment_id)
            toc = el.get("tableOfContents")
            if toc:
                walk(toc.get("content"), segment_id)

    walk((doc.get("body") or {}).get("content"), None)
    for key in ("headers", "footers", "footnotes"):
        for seg_id, seg in (doc.get(key) or {}).items():
            walk((seg or {}).get("content"), seg_id)
    return "".join(parts), links


def retarget_requests(doc: dict, ids: dict[str, str]) -> tuple[list[dict], int]:
    """Docs ``batchUpdate`` requests that point ``doc`` at the copies in ``ids``
    (source id -> copy id), and how many occurrences they rewrite.

    Link retargets come FIRST: ``updateTextStyle`` addresses a link by index
    range, and a ``replaceAllText`` that changes text length ahead of it would
    shift those indexes. Then one ``replaceAllText`` per source id visible in
    the text — but only when every occurrence of that id is a whole id:
    ``replaceAllText`` is a substring replace, so an id that also sits inside a
    longer token would be corrupted there, and is left alone instead."""
    pattern = id_pattern(ids)
    if pattern is None:
        return [], 0
    text, links = text_and_links(doc)
    requests: list[dict] = []
    occurrences = 0
    for link in links:
        new_url, n = pattern.subn(lambda m: ids[m.group(1)], link["url"])
        if not n:
            continue
        rng: dict[str, Any] = {"startIndex": link["startIndex"], "endIndex": link["endIndex"]}
        if link["segmentId"]:
            rng["segmentId"] = link["segmentId"]
        requests.append({
            "updateTextStyle": {
                "range": rng,
                "textStyle": {"link": {"url": new_url}},
                "fields": "link",
            }
        })
        occurrences += 1
    whole: dict[str, int] = {}
    for m in pattern.finditer(text):
        whole[m.group(1)] = whole.get(m.group(1), 0) + 1
    for source_id, n in whole.items():
        if text.count(source_id) != n:
            continue
        requests.append({
            "replaceAllText": {
                "containsText": {"text": source_id, "matchCase": True},
                "replaceText": ids[source_id],
            }
        })
        occurrences += n
    return requests, occurrences
