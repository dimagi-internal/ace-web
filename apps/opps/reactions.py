"""Partner reactions to a run's decision rows — the write half of the
public review surface.

#708 put 42 decision rows on the public per-run summary and gave a
partner no way to say anything about any of them. Reading 42 rows and
reacting to none reproduces the exact failure the decisions log exists
to fix (skim a 24-page PDD, agree with all of it), just in a nicer
shape. This module is the response affordance's store.

Where a reaction goes, and why it is not one of the two write paths
that already exist:

* ``POST .../gates/{skill}`` (``apps.opps.api.record_gate_decision``)
  records a MEMBER's binary approve/reject against a SKILL, into
  ``run_state.yaml``'s ``gates:`` map. Wrong grain (skill, not decision
  row), wrong vocabulary (approved/rejected, not "here is what I think"),
  wrong identity model (an authenticated workspace member), and it writes
  into the file the ACE plugin's Phase Write-Back Contract owns.

* ``inputs/decision-overrides.yaml`` (``apps.opps.decision_overrides``)
  records a member CHANGING an answer, and is read by the next run as
  design input. A self-asserted name on an unauthenticated public page
  must not be able to silently rewrite the next run's inputs. An
  override is a decision; a partner reaction is evidence a human might
  decide on.

* So: a reaction is a **feedback record**, the store the ACE plugin's
  ``skills/feedback-ledger`` already defines for exactly this — an
  external reviewer's verbatim comment on an artifact, with a
  ``<record-slug>/<item-id>`` provenance stamp ("Feedback-Ref") that
  every downstream change cites, and a completeness property that
  renders an unactioned item as UNROUTED rather than dropping it.
  Writing the reaction in that shape means the next run's ledger picks
  it up with no new consumer.

The record we emit conforms to ``FeedbackRecordSchema`` in the plugin's
``lib/feedback-ledger.ts`` (schema_version 1) — a STRICT zod object, so
no extra keys may be added here. Everything this surface needs to say
about itself is therefore encoded in fields that schema already has:

* ``slug`` — ``<YYYYMMDD>-public-<reviewer-slug>``. The ``public``
  segment is the marker. It is what makes a self-reported name on an
  unauthenticated page distinguishable, in the fact store itself, from
  a verified gdoc comment — and it is what this module filters on when
  reading reactions back, so a privately-captured review record can
  never be republished on a public page by accident.
* ``channel: other`` — the enum has no ``public-summary`` member; adding
  one is a plugin-side change (dimagi-internal/ace).
* ``artifact`` — names the surface and says the identity is self-reported.
* ``anchor`` — ``decision:<decision-id> · <question>``: machine-parseable
  back to the row, legible to a human reading the ledger.

Item ids are the decision id, so a ``Feedback-Ref:`` trailer reads
``20260814-public-jane-doe/solicitation-expected-period`` — the stamp
names the row it is about.
"""
from __future__ import annotations

import logging
import re
from datetime import UTC, date, datetime
from typing import Any

import yaml

from apps.opps import public_input
from apps.opps.sync import _find_child, _find_child_folder

log = logging.getLogger(__name__)

FEEDBACK_FOLDER = "feedback"
FEEDBACK_SCHEMA_VERSION = 1
_YAML_MIME = "application/x-yaml"

#: Prefix that binds a feedback item back to a decision row.
ANCHOR_PREFIX = "decision:"

#: Marker segment in the record slug. See the module docstring.
PUBLIC_MARKER = "public"

_PUBLIC_SLUG_RE = re.compile(rf"^\d{{8}}-{PUBLIC_MARKER}-[a-z0-9]+(-[a-z0-9]+)*$")
_ANCHOR_RE = re.compile(rf"^{ANCHOR_PREFIX}([a-z0-9]+(?:-[a-z0-9]+)*)")

# --- Abuse controls. A public unauthenticated endpoint that accepts
# writes needs a ceiling on every dimension an actor controls: how long
# one submission can be, how many they can send, and how large the file
# they are appending to can grow. Input hygiene itself (control chars,
# HTML, name/email shape) is shared with the decision-edit surface in
# ``apps.opps.public_input`` — one public write surface's rules should
# never drift from the other's.
MIN_COMMENT_CHARS = 3
MAX_COMMENT_CHARS = 2000
MIN_NAME_CHARS = public_input.MIN_NAME_CHARS
MAX_NAME_CHARS = public_input.MAX_NAME_CHARS
MAX_EMAIL_CHARS = public_input.MAX_EMAIL_CHARS
#: Ceiling per (run, record) so one actor cannot balloon a Drive file.
MAX_ITEMS_PER_RECORD = 50
#: Ceiling across the whole run, counted over every public record.
MAX_ITEMS_PER_RUN = 300

#: The rejection type this module raises. Shared with the decision-edit
#: surface so the API layer has one exception to map to a status code.
ReactionRejected = public_input.PublicInputRejected


# ─── Input hygiene ─────────────────────────────────────────────────
# Thin bindings over the shared rules — see ``apps.opps.public_input``.


def clean_reviewer(raw: str | None) -> str:
    return public_input.clean_name(
        raw,
        missing_message=(
            "Tell us who you are — a comment nobody can attribute can't be "
            "answered or credited."
        ),
    )


def clean_email(raw: str | None) -> str | None:
    return public_input.clean_email(raw)


def clean_comment(raw: str | None) -> str:
    return public_input.clean_text(
        raw,
        field="Comment",
        min_chars=MIN_COMMENT_CHARS,
        max_chars=MAX_COMMENT_CHARS,
        too_short="Say a little more than that.",
    )


def reviewer_slug(name: str) -> str:
    """Kebab-case the reviewer's name for the record slug.

    Falls back to ``reviewer`` when a name is entirely non-latin — the
    slug only has to be a stable filename, the display name is carried
    verbatim in ``reviewer``.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    return slug or "reviewer"


# ─── Anchors ───────────────────────────────────────────────────────


def build_anchor(decision_id: str, question: str) -> str:
    """``decision:<id> · <question>`` — parseable AND readable.

    ``anchor`` is the schema's "where in the artifact it was left" field.
    Prefixing it binds the item to the row without inventing a key the
    strict schema would reject.
    """
    q = " ".join(str(question or "").split())
    if len(q) > 160:
        q = q[:159].rstrip() + "…"
    return f"{ANCHOR_PREFIX}{decision_id} · {q}" if q else f"{ANCHOR_PREFIX}{decision_id}"


def parse_decision_id(anchor: str | None) -> str | None:
    m = _ANCHOR_RE.match(str(anchor or ""))
    return m.group(1) if m else None


def is_public_record_slug(slug: str | None) -> bool:
    return bool(_PUBLIC_SLUG_RE.match(str(slug or "")))


# ─── Drive plumbing ────────────────────────────────────────────────


def _parse_record(body: str) -> dict[str, Any]:
    try:
        data = yaml.safe_load(body)
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def _list_feedback_files(drive, opp_folder_id: str) -> list:
    folder = _find_child_folder(drive.list_files(opp_folder_id), FEEDBACK_FOLDER)
    if folder is None:
        return []
    return [f for f in drive.list_files(folder.id) if f.name.endswith(".yaml")]


def _render_record(record: dict) -> str:
    return yaml.safe_dump(record, sort_keys=False, allow_unicode=True, width=100)


def next_item_id(existing_ids: set[str], decision_id: str) -> str:
    """``<decision-id>``, then ``-2``, ``-3``… within one record.

    Kept kebab-case because ``FeedbackItemSchema.id`` enforces it.
    """
    if decision_id not in existing_ids:
        return decision_id
    n = 2
    while f"{decision_id}-{n}" in existing_ids:
        n += 1
    return f"{decision_id}-{n}"


def _lookup_decision(drive, run_folder_id: str, decision_id: str) -> dict | None:
    """Find the row in the run's ``decisions.yaml``.

    A reaction that names a row which does not exist is not routable —
    the ``feedback_ref`` would dangle and the ledger would render it
    under "Broken stamps". So this is a hard precondition, not a warning.
    """
    f = _find_child(drive.list_files(run_folder_id), "decisions.yaml")
    if f is None:
        return None
    data = _parse_record(drive.get_content(f.id, f.mime_type).content or "")
    rows = data.get("decisions")
    if not isinstance(rows, list):
        return None
    for row in rows:
        if isinstance(row, dict) and str(row.get("id") or "") == decision_id:
            return row
    return None


def submit_decision_reaction(
    *,
    drive,
    opp_folder_id: str,
    run_folder_id: str,
    run_id: str,
    decision_id: str,
    reviewer: str,
    reviewer_email: str | None,
    comment: str,
    artifact_url: str,
    today: date | None = None,
) -> dict:
    """Append one reaction to the reviewer's feedback record for this run.

    Returns ``{"feedback_ref", "record_slug", "item_id", "reviewer",
    "comment", "received_at"}``.

    Read-modify-write against a single small Drive file. Two reviewers
    submitting in the same second to the SAME record (same name, same
    day, same run) could lose one write; the rate limiter makes that
    window vanishingly small and the cost of losing it is one comment,
    not a corrupted store. A stronger guarantee needs a lock we do not
    have a place to put yet.
    """
    reviewer = clean_reviewer(reviewer)
    reviewer_email = clean_email(reviewer_email)
    comment = clean_comment(comment)

    row = _lookup_decision(drive, run_folder_id, decision_id)
    if row is None:
        raise ReactionRejected(
            "not-found", f"no decision named {decision_id!r} in run {run_id!r}",
        )

    day = (today or datetime.now(UTC).date()).strftime("%Y%m%d")
    base_slug = f"{day}-{PUBLIC_MARKER}-{reviewer_slug(reviewer)}"

    folder = _find_child_folder(drive.list_files(opp_folder_id), FEEDBACK_FOLDER)
    files = list(drive.list_files(folder.id)) if folder is not None else []
    by_name = {f.name: f for f in files}

    # Count what this run already carries, across every public record.
    run_total = 0
    for f in files:
        if not f.name.endswith(".yaml"):
            continue
        rec = _parse_record(drive.get_content(f.id, f.mime_type).content or "")
        if not is_public_record_slug(rec.get("slug")) or rec.get("against_run") != run_id:
            continue
        run_total += len(rec.get("items") or [])
    if run_total >= MAX_ITEMS_PER_RUN:
        raise ReactionRejected(
            "too-many", "This run has collected all the comments it can hold.",
        )

    # Same reviewer + same day can be looking at two different runs, and a
    # record carries exactly one `against_run`. Walk suffixes until we find
    # this run's record or a free slot.
    target_file = None
    record: dict[str, Any] | None = None
    slug = base_slug
    n = 1
    while True:
        existing = by_name.get(f"{slug}.yaml")
        if existing is None:
            break
        candidate = _parse_record(
            drive.get_content(existing.id, existing.mime_type).content or "",
        )
        if candidate.get("against_run") == run_id:
            target_file, record = existing, candidate
            break
        n += 1
        slug = f"{base_slug}-{n}"

    if record is None:
        record = {
            "schema_version": FEEDBACK_SCHEMA_VERSION,
            "slug": slug,
            "reviewer": reviewer,
            "received_at": (today or datetime.now(UTC).date()).isoformat(),
            "channel": "other",
            "artifact": "Decisions — public run summary (name self-reported)",
            "artifact_url": artifact_url,
            "against_run": run_id,
            "items": [],
        }
        if reviewer_email:
            record["reviewer_email"] = reviewer_email
    elif reviewer_email and not record.get("reviewer_email"):
        record["reviewer_email"] = reviewer_email

    items = record.get("items")
    if not isinstance(items, list):
        items = []
    if len(items) >= MAX_ITEMS_PER_RECORD:
        raise ReactionRejected(
            "too-many", "You've left as many comments as one visit can carry.",
        )

    item_id = next_item_id(
        {str(i.get("id")) for i in items if isinstance(i, dict)}, decision_id,
    )
    items.append({
        "id": item_id,
        "verbatim": comment,
        "anchor": build_anchor(decision_id, str(row.get("question") or "")),
    })
    record["items"] = items
    record["slug"] = slug

    body = _render_record(record)
    if target_file is not None:
        drive.update_file(target_file.id, body, _YAML_MIME)
    else:
        if folder is None:
            folder_id = drive.create_folder(opp_folder_id, FEEDBACK_FOLDER)
        else:
            folder_id = folder.id
        drive.upload_file(folder_id, f"{slug}.yaml", body, _YAML_MIME)

    return {
        "feedback_ref": f"{slug}/{item_id}",
        "record_slug": slug,
        "item_id": item_id,
        "reviewer": reviewer,
        "comment": comment,
        "received_at": record["received_at"],
    }


def read_reactions(drive, opp_folder_id: str, *, run_id: str) -> dict:
    """Reactions this run has collected, grouped by decision id.

    Only records whose slug carries the ``public`` marker are read back.
    A review ACE captured privately (an email, a meeting, gdoc comments)
    lives in the same folder and must never be republished on a page
    anyone can open — the marker, not a heuristic, is what keeps them
    apart. ``reviewer_email`` is deliberately not projected.

    Any failure degrades to "no reactions": the page must still render.
    """
    out: dict[str, list[dict]] = {}
    total = 0
    try:
        files = _list_feedback_files(drive, opp_folder_id)
    except Exception as exc:  # noqa: BLE001
        log.warning("reactions: list feedback failed: %s", exc)
        return {"total": 0, "by_decision": {}}

    for f in files:
        try:
            rec = _parse_record(drive.get_content(f.id, f.mime_type).content or "")
        except Exception as exc:  # noqa: BLE001
            log.warning("reactions: read %s failed: %s", f.name, exc)
            continue
        slug = rec.get("slug")
        if not is_public_record_slug(slug) or rec.get("against_run") != run_id:
            continue
        reviewer = str(rec.get("reviewer") or "").strip() or "Anonymous"
        received_at = str(rec.get("received_at") or "")
        for item in rec.get("items") or []:
            if not isinstance(item, dict):
                continue
            decision_id = parse_decision_id(item.get("anchor"))
            verbatim = str(item.get("verbatim") or "").strip()
            if not decision_id or not verbatim:
                continue
            out.setdefault(decision_id, []).append({
                "reviewer": reviewer,
                "comment": verbatim,
                "received_at": received_at,
                "feedback_ref": f"{slug}/{item.get('id')}",
            })
            total += 1

    return {"total": total, "by_decision": out}
