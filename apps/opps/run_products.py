"""The run's products — what an ACE run brought into the world — as one list.

``run_state.yaml`` records every phase's typed handoffs under
``phases.<phase>.products.*`` (the products contract,
docs/specs/2026-05-11-products-block-contract.md): the PDD, the Learn and
Deliver apps, the Connect program and opportunity, the OCS chatbot, the
training pack, the demo dashboards. This module flattens those blocks into a
catalogue the Phases screen can show — a strip of "what this run built", a
viewer per item, and a replay that pops each one up at the beat that made it.

It WALKS the blocks instead of carrying one reader per product (the public
summary's approach, apps/opps/summary.py). The summary is a frozen external
contract that decides section by section what a partner may see; this is an
internal view whose job is to miss nothing, so a product the plugin starts
writing tomorrow shows up here without a code change. Any mapping carrying a
locator is an item, and the walk does not descend into an item.

The few shapes known to drift are handled explicitly — they are the same
drifts the summary absorbs (ace#705): a Connect block written flat at the
products root instead of under ``connect``, apps written as
``apps.{learn,deliver}`` or as ``learn_app`` / ``deliver_app``, and an HQ app
recorded as ``hq_app_id`` + domain with no ``hq_url``.

Two rules carried over from the summary:

* ``nova_url`` is never surfaced — the Nova build tool has no public URL that
  resolves; ``hq_url`` is the real app link.
* ``ace_test_user`` is ACE's own emulator login, not something the run built.

Pure: no Drive, no Django models. The one plugin read is producer
attribution (:func:`apps.opps.skills.resolve_product_producer`), which is
cached and answers ``None`` on a plugin that declares none.
"""
from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urlparse

from apps.opps.summary import drive_file_id

log = logging.getLogger(__name__)

#: Keys whose presence makes a mapping a product rather than a container.
_LOCATOR_KEYS = (
    "file_id",
    "web_view_link",
    "url",
    "deep_link",
    "hq_url",
    "hq_app_id",
    "public_url",
    "par_url",
    "run_url",
    "admin_url",
)

#: URL-bearing keys in the order to prefer them as THE link for an item.
#: ``nova_url`` is deliberately absent.
_URL_KEYS = (
    "web_view_link",
    "url",
    "deep_link",
    "hq_url",
    "public_url",
    "par_url",
    "run_url",
    "admin_url",
)

#: Blocks that are not things the run built.
_SKIP_KEYS = frozenset({"ace_test_user"})

_ACRONYMS = {
    "llo", "flw", "ocs", "qa", "kpi", "pdd", "hq", "faq", "uat", "rag", "ddd", "id",
}

_INDEX_SEGMENT = re.compile(r"^\d+$")


def build_products(
    phase_products: dict[str, Any] | None,
    *,
    phase_order: list[str] | None = None,
) -> list[dict]:
    """Flatten ``{phase: products}`` into the catalogue, in phase order.

    Each item::

        {id, phase, key, kind, title, subtitle, url, file_id, facts,
         producer, chatbot}

    ``key`` is the dotted path under ``products`` (list indexes included);
    ``producer`` the skill that wrote it per the plugin, or ``None``;
    ``chatbot`` is ``{public_id, embed_key}`` for an OCS bot that can be
    embedded, else ``None``. Items are de-duplicated by Drive file id, then
    by URL, first seen wins.
    """
    if not isinstance(phase_products, dict):
        return []
    order = list(phase_order or [])
    phases = sorted(
        (str(p) for p in phase_products),
        key=lambda p: (order.index(p) if p in order else len(order), p),
    )
    domain = _hq_domain(phase_products)

    out: list[dict] = []
    seen: set[str] = set()
    for phase in phases:
        block = phase_products.get(phase)
        if not isinstance(block, dict):
            continue
        for key, node, parent in _walk(block, []):
            item = _item(phase, key, node, parent, domain)
            if item is None:
                continue
            ident = item["file_id"] or item["url"]
            if ident in seen:
                continue
            seen.add(ident)
            out.append(item)
    return out


# --------------------------------------------------------------------------- #
# walk
# --------------------------------------------------------------------------- #
def _walk(node: dict, path: list[str], parent: dict | None = None):
    """Yield ``(dotted_path_segments, mapping, parent_mapping)`` for every
    item under ``node``, depth-first in the order the block was written."""
    for key, value in node.items():
        key = str(key)
        if key in _SKIP_KEYS:
            continue
        if isinstance(value, dict):
            if _is_item(value):
                yield [*path, key], value, node
            else:
                yield from _walk(value, [*path, key], node)
        elif isinstance(value, list):
            for i, entry in enumerate(value):
                if not isinstance(entry, dict):
                    continue
                if _is_item(entry):
                    yield [*path, key, str(i)], entry, node
                else:
                    yield from _walk(entry, [*path, key, str(i)], node)


def _is_item(node: dict) -> bool:
    return any(node.get(k) for k in _LOCATOR_KEYS)


# --------------------------------------------------------------------------- #
# item
# --------------------------------------------------------------------------- #
def _item(
    phase: str,
    segments: list[str],
    node: dict,
    parent: dict | None,
    domain: str | None,
) -> dict | None:
    names = [s for s in segments if not _INDEX_SEGMENT.match(s)]
    last = names[-1] if names else ""
    parent_name = names[-2] if len(names) > 1 else ""
    kind = _kind(last, parent_name, node)

    url = next((node[k] for k in _URL_KEYS if _is_http(node.get(k))), None)
    file_id = _str(node.get("file_id")) or drive_file_id(url)
    facts: list[dict] = []
    chatbot = None

    if kind == "commcare_app":
        app_domain = _str(node.get("domain")) or _str((parent or {}).get("domain")) or domain
        hq_url = node.get("hq_url") if _is_http(node.get("hq_url")) else None
        if not hq_url and node.get("hq_app_id") and app_domain:
            hq_url = (
                f"https://www.commcarehq.org/a/{app_domain}/apps/view/{node['hq_app_id']}/"
            )
        url = hq_url
        file_id = None
        _fact(facts, "Build", node.get("build_status"))
        _fact(facts, "Project space", app_domain)
    elif kind == "connect_opportunity":
        _fact(facts, "Starts", node.get("start_date"))
        _fact(facts, "Ends", node.get("end_date"))
    elif kind == "chatbot":
        url = node.get("admin_url") if _is_http(node.get("admin_url")) else url
        _fact(facts, "Team", node.get("team_slug"))
        _fact(facts, "Published version", node.get("published_version"))
        if node.get("public_id") and node.get("embed_key"):
            chatbot = {"public_id": str(node["public_id"]), "embed_key": str(node["embed_key"])}
    elif kind == "solicitation":
        _fact(facts, "Deadline", node.get("deadline"))
        _fact(facts, "Status", node.get("status"))

    if not url and file_id:
        url = f"https://drive.google.com/open?id={file_id}"
    if not url and not file_id:
        return None

    # A list entry's own ``key`` (Phase 7 dashboards: ``{key, par_url}``)
    # names it better than the list does.
    title = (
        _str(node.get("title"))
        or _str(node.get("name"))
        or humanize(_str(node.get("key")) or "")
        or _default_title(kind, last)
    )
    subtitle = _str(node.get("description"))
    if subtitle and len(subtitle) > 240:
        subtitle = subtitle[:237].rstrip() + "…"

    return {
        "id": f"{phase}:{'.'.join(segments)}",
        "phase": phase,
        "key": ".".join(segments),
        "kind": kind,
        "title": title,
        "subtitle": subtitle,
        "url": url,
        "file_id": file_id,
        "facts": facts,
        "producer": _producer(phase, names),
        "chatbot": chatbot,
    }


def _kind(last: str, parent_name: str, node: dict) -> str:
    """What sort of thing this is, from its key first and its URL second."""
    lowered = last.lower()
    if (parent_name == "apps" and lowered in {"learn", "deliver"}) or lowered in {
        "learn_app",
        "deliver_app",
    }:
        return "commcare_app"
    if lowered == "opportunity":
        return "connect_opportunity"
    if lowered == "program":
        return "connect_program"
    if lowered == "ocs_chatbot" or (node.get("public_id") and node.get("embed_key")):
        return "chatbot"
    if "solicitation" in lowered:
        return "solicitation"

    url = next((node[k] for k in _URL_KEYS if _is_http(node.get(k))), "") or ""
    host, path = _host_path(url)
    if host == "docs.google.com":
        if path.startswith("/presentation"):
            return "deck"
        if path.startswith("/spreadsheets"):
            return "sheet"
        if path.startswith("/document"):
            return "document"
    if node.get("par_url") or node.get("run_url") or "dashboard" in lowered:
        return "dashboard"
    if "deck" in lowered or "slides" in lowered:
        return "deck"
    if node.get("file_id") or host == "drive.google.com":
        # Everything ACE writes to Drive lands as a Google Doc unless its URL
        # says otherwise (docs/learnings/drive-prose-export.md).
        return "document"
    return "link"


def _default_title(kind: str, last: str) -> str:
    if kind == "commcare_app" and last.lower().startswith(("learn", "deliver")):
        return f"{last.split('_')[0].capitalize()} app"
    if kind == "connect_opportunity":
        return "Connect opportunity"
    if kind == "connect_program":
        return "Connect program"
    if kind == "chatbot":
        return "Support chatbot"
    return humanize(last) or "Product"


def _producer(phase: str, names: list[str]) -> str | None:
    """The skill that wrote ``products.<names>``, per the plugin, or None."""
    from apps.opps.skills import product_producers, resolve_product_producer

    try:
        producers = product_producers(phase)
    except Exception:  # noqa: BLE001 — attribution is a nicety, never a failure
        log.debug("run_products: product_producers(%s) failed", phase, exc_info=True)
        return None
    if not producers or not names:
        return None
    return resolve_product_producer(producers, ".".join(names))


def _hq_domain(phase_products: dict) -> str | None:
    """The HQ project space, for building an app URL from ``hq_app_id``.

    Same places the summary looks (``summary._connect_domain``): the
    commcare-setup ``apps.domain``, then connect-setup's nested or flat
    ``domain`` / ``organization_slug``.
    """
    cc = phase_products.get("commcare-setup") or {}
    apps = cc.get("apps") if isinstance(cc, dict) else None
    if isinstance(apps, dict) and _str(apps.get("domain")):
        return _str(apps.get("domain"))
    cs = phase_products.get("connect-setup") or {}
    if not isinstance(cs, dict):
        return None
    connect = cs.get("connect") if isinstance(cs.get("connect"), dict) else {}
    for block in (connect, cs):
        for key in ("domain", "organization_slug"):
            if _str(block.get(key)):
                return _str(block.get(key))
    return None


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def humanize(key: str) -> str:
    """``llo_guide`` → ``LLO guide``; ``work-order`` → ``Work order``."""
    words = [w for w in re.split(r"[_\-\s]+", str(key or "")) if w]
    out = []
    for i, w in enumerate(words):
        if w.lower() in _ACRONYMS:
            out.append(w.upper())
        elif i == 0:
            out.append(w[:1].upper() + w[1:])
        else:
            out.append(w.lower())
    return " ".join(out)


def _fact(facts: list[dict], label: str, value: Any) -> None:
    if value is None or isinstance(value, (dict, list)):
        return
    text = str(value).strip()
    if text:
        facts.append({"label": label, "value": text})


def _str(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _is_http(value: Any) -> bool:
    return isinstance(value, str) and value.startswith(("http://", "https://"))


def _host_path(url: str) -> tuple[str, str]:
    try:
        parsed = urlparse(url)
    except ValueError:
        return "", ""
    return (parsed.hostname or "").lower(), parsed.path or ""
