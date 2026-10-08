"""Public per-run summary payload — products.*-driven.

Reads structured `phases.<phase>.products.<block>` state from the run's
`run_state.yaml` (plus identity from `opp.yaml`) and projects it into the
JSON payload the public summary page renders. The plugin's
state-consolidation sweep (plugin v0.13.155–v0.13.172) puts every
typed handoff there; this loader does no markdown-body parsing.

What lives where:

- `ACE/<opp-slug>/opp.yaml`
    Identity: ``display_name``, ``slug``, ``tags``, ``created_at``,
    ``created_by``. Plus the durable Connect program reference at
    ``connect.program.{id, url, labs_int_id}`` — written once by
    ``connect-program-setup`` and reused across every run.

- ``ACE/<opp-slug>/runs/<run-id>/run_state.yaml``
    Per-run state under ``phases.<phase>.{status, products, steps}``.
    Every block this loader reads:

    | Phase                     | Block                                                |
    |---------------------------|------------------------------------------------------|
    | ``design``                | ``products.pdd.{title, description, file_id}``       |
    | ``commcare-setup``        | ``products.apps.{learn, deliver}.{name, nova_*, hq_*, build_status}`` |
    | ``connect-setup``         | ``products.connect.{program, opportunity, ace_test_user}``  |
    | ``ocs-setup``             | ``products.ocs_chatbot.{experiment_id, public_id, embed_key, admin_url, team_slug}`` |
    | ``qa-and-training``       | ``products.training.{deck, docs.*}``                  |
    | ``synthetic-data-and-workflows`` | ``products.synthetic.{walkthroughs, dashboards, workflows, labs_opp_id}`` |
    | ``solicitation-management`` | ``products.{solicitation, selected_llo}``           |
    | ``execution-management``  | ``products.launch``                                  |
    | ``closeout``              | ``products.{cycle_grade, opp_eval, learnings}``      |

No defensive fallbacks to the pre-consolidation Drive layout. Older
runs without the typed blocks simply render with the affected sections
empty — they get the same defensive ``dict.get`` chain that the rest
of the loader uses, so nothing 500s. Each section is independently
nullable.

One artifact still requires a Drive fetch — the orchestrator writes no
typed pointer for it:

- ``ACE/<opp>/runs/<run-id>/decisions.yaml``

It is an internal WORKING artifact that nobody shares, so this loader
carries its CONTENT rather than a link. It is the review surface: what we
decided and why, AND what we still need a person to answer. The open asks
are a FILTER of its rows (``_open_asks``), never a second document — the
legacy opp-level ``open-questions.md`` ledger and the generated
``open-asks.yaml`` are not read (operator decision 2026-10-07: "why isn't
that just a filter of decisions").

A THIRD reads from Drive by path, for a different reason — there is no
pointer to write:

- ``<run>/5-ocs/ocs-chatbot-eval_verdict-deep.yaml``
- ``<run>/6-qa-and-training/app-ux-eval_verdict-deep.yaml``

``/ace:qa-deep`` writes nothing into ``run_state.yaml`` on purpose, so a
later ``/ace:run`` resume is unaffected by the deep gate having been
taken. The presence of the two files is therefore the only honest signal
that it ran — which is exactly the signal the ``deep_qa`` section keys
on. See ``_read_deep_qa``.

The build memo section (ace-web#767) was removed in 2026-10 when ACE
retired the build memo; a run that still records one simply doesn't show it.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime
from urllib.parse import urlparse

import yaml
from django.conf import settings

from apps.opps.drive_client import DriveClient
from apps.opps.reactions import read_reactions

log = logging.getLogger(__name__)


# ─── Helpers ───────────────────────────────────────────────────────


def _read_yaml(drive: DriveClient, file_id: str,
               mime_type: str = "application/x-yaml") -> dict:
    """Fetch and parse a YAML file by id. Returns ``{}`` on any failure.

    Google Docs store YAML as plain text; pass the file's actual
    ``mime_type`` so ``get_content`` hits the export path instead of
    the raw-download path (which fails for Docs).
    """
    try:
        content = drive.get_content(file_id, mime_type)
        body = content.content or ""
    except Exception as exc:  # noqa: BLE001
        log.warning("summary: read yaml %s failed: %s", file_id, exc)
        return {}
    try:
        data = yaml.safe_load(body) or {}
        return data if isinstance(data, dict) else {}
    except yaml.YAMLError as exc:
        log.warning("summary: parse yaml %s failed: %s", file_id, exc)
        return {}


def _find_in_folder(drive: DriveClient, folder_id: str, name: str):
    try:
        for f in drive.list_files(folder_id):
            if f.name == name:
                return f
    except Exception as exc:  # noqa: BLE001
        log.warning("summary: list %s failed: %s", folder_id, exc)
    return None


def _find_folder(drive: DriveClient, parent_id: str, name: str):
    f = _find_in_folder(drive, parent_id, name)
    if f is None or f.mime_type != "application/vnd.google-apps.folder":
        return None
    return f


def _phase(state: dict, phase: str) -> dict:
    """Pull ``state.phases.<phase>`` with empty-dict fallback."""
    block = (state.get("phases") or {}).get(phase) or {}
    return block if isinstance(block, dict) else {}


def _phase_products(state: dict, phase: str, block: str | None = None) -> dict:
    """Pull ``state.phases.<phase>.products[.block]`` with empty-dict fallback."""
    products = (
        state.get("phases", {})
        .get(phase, {})
        .get("products", {})
    )
    if not isinstance(products, dict):
        return {}
    if block is None:
        return products
    sub = products.get(block) or {}
    return sub if isinstance(sub, dict) else {}


# ─── Link access classification ────────────────────────────────────
#
# Every link the page renders declares who can actually open it. This is
# a PROPERTY OF THE PAYLOAD, never a hostname table in the component:
# the URLs change every run, but each reader knows which SYSTEM it just
# read a link out of, and that system's access model is what's stable.
#
# ``admin`` ("admin only") means: a reviewer of this run will NEVER get
# access — the link stays Dimagi-internal. It used to mean "needs an account
# we cannot give an external partner today", which was true while every opp
# shared ACE's tenants (Jonathan, 2026-08-14). It is no longer true for an
# opp with its OWN tenancy (Jonathan, 2026-10-03: "admin only was meant to
# mean you needed to be dimagi because the things weren't properly
# isolated. That is no longer true and you should expect access, so the
# things that are truly dimagi admin only are what we should be using").
# `/ace:release` invites each reviewer into the opp's own HQ project space,
# Connect org and ace-web workspace, and Labs is opened to the tenancy's
# `labs_allowed_domains`. So each non-Drive link is classified PER LINK
# against the opp's tenancy (``apps.opps.tenancy.TenancyAccess``):
#
# ``reviewer`` — inside the opp's own tenancy. A released reviewer should
#   expect to open it; the page draws NO tag.
#   * CommCare HQ app pages   — when the URL's space is the opp's hq_domain.
#   * Connect opportunity     — when the URL's org is the opp's PM/holding org.
#   * connect-labs dashboards + solicitation — when labs_allowed_domains
#     reaches beyond Dimagi's own domains.
#   * ace-web Workbench       — when the opp has its own tenancy.
#
# ``admin`` — stays Dimagi-internal:
#   * any of the above on a SHARED-tenancy opp (`connect-ace-prod`,
#     `ace-pm-org` / `ace-nm-org`, Dimagi-only Labs domains — e.g.
#     `dimagi-team`'s opps), or a URL outside the opp's tenancy;
#   * the OCS team console, always — reviewers use the public chatbot;
#   * a Drive doc that is NOT anyone-with-link, on ANY tenancy —
#     `/ace:release` invites to HQ, Connect and ace-web only and shares no
#     Drive file, so a released reviewer cannot open it. The tag is
#     measured, so it clears itself once the doc is shared;
#   * a canopy-web walkthrough the run did not tag (see
#     ``_derive_walkthrough_access``).
#
# A gated link is never hidden and never silently 404s, and a workspace
# member sees no tag at all.
#
# ``public`` means: no ACE-side account gate.
#
# For a Google Drive link, ``public`` is now MEASURED, never asserted
# (ace-web#740). Every Drive deliverable — PDD, work order, training
# pack, learnings, feedback ledgers, open questions — used to be stamped
# ``public`` on the theory that ``/ace:share-run-access`` shares exactly
# these with reviewers. It does not always run, and nothing checked. An
# anonymous audit of ``spark-facilitator/20260820-0817`` found the PDD
# and the Work Order both rendering "Open" while
# ``.../export?format=txt`` answered **401** to a reader with no
# account, on a page whose whole job is to be forwarded to someone who
# has none. Three of that run's link classes were wrong the same way,
# and the run's verdict was NOT SAFE TO SHARE.
#
# So: a Drive link's tag comes from the file's own ACL, read through
# ``DriveClient.link_shared`` (an ``anyone`` permission ⇒ ``public``).
# When the ACL cannot be read the tag is ``unknown`` — a third value,
# added deliberately. "We could not check" and "anyone can open this"
# are different facts and the page must not print the second when it
# means the first; ``admin`` would be the same lie pointed the other
# way (see ``_derive_walkthrough_access``). ``unknown`` renders as
# "access unverified", which is honest and costs a reader one click to
# find out.
#
# NON-Drive links have nothing per-object to measure, so they are
# classified from the opp's tenancy as above. A measured Drive file that is
# NOT anyone-with-link is ``admin`` on every tenancy (see above).
ACCESS_PUBLIC = "public"
ACCESS_ADMIN = "admin"
ACCESS_UNKNOWN = "unknown"
ACCESS_REVIEWER = "reviewer"


def _tenant_tag(inside_own_tenancy: bool) -> str:
    """``reviewer`` (no tag) inside the opp's own tenancy, else ``admin``."""
    return ACCESS_REVIEWER if inside_own_tenancy else ACCESS_ADMIN


# Drive file-id shapes this page actually hands out. ``/d/<id>`` covers
# Docs, Sheets, Slides and Forms; ``/file/d/<id>`` covers the blob
# preview URL ``_learnings_link`` builds.
_DRIVE_ID_RE = re.compile(r"/(?:file/)?d/([A-Za-z0-9_-]{10,})")

_DRIVE_HOSTS = ("docs.google.com", "drive.google.com")


def drive_file_id(url: str | None) -> str | None:
    """The Drive file id a URL addresses, or ``None`` if it is not a
    Drive URL we can key on. Used to measure a link whose producer
    recorded a ``web_view_link`` but no ``file_id``."""
    if not isinstance(url, str) or not url:
        return None
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return None
    if host not in _DRIVE_HOSTS:
        return None
    m = _DRIVE_ID_RE.search(url)
    return m.group(1) if m else None


class LinkAccessReader:
    """Measures who can open a Drive link, with one batched ACL read.

    Built once per payload. ``prime()`` resolves a whole batch
    concurrently before the section readers run, so measuring ~10 links
    costs ONE round of concurrent calls rather than ten sequential ones
    — the summary endpoint is already latency-sensitive and this must
    not undo the batching work in ace-web#738.

    ``tag()`` answers from the primed memo. A miss falls through to a
    single read rather than silently guessing: a reader that forgot to
    prime should be slow, never wrong.
    """

    def __init__(self, drive: DriveClient, tenancy: dict | None = None) -> None:
        from apps.opps.tenancy import TenancyAccess

        self._drive = drive
        #: Where a released reviewer gets access — see the block above.
        self.tenancy = TenancyAccess(tenancy)
        self._memo: dict[str, bool] = {}
        self._resolved: set[str] = set()

    def prime(self, file_ids) -> None:
        pending = [
            fid for fid in dict.fromkeys(f for f in file_ids if f)
            if fid not in self._resolved
        ]
        if not pending:
            return
        try:
            found = self._drive.link_shared(pending)
        except Exception as exc:  # noqa: BLE001
            log.warning("summary: link_shared batch failed: %s", exc)
            found = {}
        self._memo.update(found)
        # Marked resolved either way: an id the client could not answer
        # for stays unknown for this payload rather than being retried
        # once per section.
        self._resolved.update(pending)

    def tag(self, *, file_id: str | None = None, url: str | None = None) -> str:
        fid = file_id or drive_file_id(url)
        if not fid:
            # Not a Drive link at all (or a producer wrote a bare URL on
            # a host we don't recognise). Nothing measurable here.
            return ACCESS_UNKNOWN
        if fid not in self._resolved:
            self.prime([fid])
        shared = self._memo.get(fid)
        if shared is None:
            return ACCESS_UNKNOWN
        # Not anyone-with-link ⇒ `admin` on every tenancy: `/ace:release`
        # shares no Drive file (commands/release.md — HQ invites, Connect org
        # members and ace-web only), so a released reviewer cannot open it.
        return ACCESS_PUBLIC if shared else ACCESS_ADMIN


def _state_drive_file_ids(state: dict) -> list[str]:
    """Every Drive file id the state-driven sections will need tagged.

    Collected up front so ``LinkAccessReader.prime`` can resolve them in
    one concurrent batch. Deliberately over-collects: an id that no
    section ends up rendering costs one cheap ACL read, while a missed
    one costs a sequential round-trip mid-render.
    """
    ids: list[str] = []

    def _add(block: dict, *keys: str) -> None:
        for key in keys:
            fid = block.get(key) or drive_file_id(
                block.get(key.replace("file_id", "web_view_link"))
            )
            if fid:
                ids.append(fid)

    design = (
        _phase_products(state, "idea-to-design")
        or _phase_products(state, "design")
    )
    for key in ("pdd", "work_order"):
        block = design.get(key)
        if isinstance(block, dict):
            ids.append(block.get("file_id") or drive_file_id(
                block.get("web_view_link") or block.get("url")) or "")

    training = _phase_products(state, "qa-and-training", "training")
    materials = _phase_products(state, "qa-and-training", "training_materials")
    docs_block = training.get("docs") or {}
    # The two guides get a plain title of our own, whatever the run wrote:
    # ACE titles them "LLO manager guide" / "FLW training guide", and an
    # outside reader knows neither acronym. The acronym stays, in brackets,
    # because the documents themselves use it throughout.
    candidates = [training.get("deck"), materials.get("deck")]
    for key in ("llo_guide", "flw_guide", "quick_reference", "faq", "onboarding_email"):
        candidates.append(docs_block.get(key))
        candidates.append(materials.get(key))
    for block in candidates:
        if isinstance(block, dict):
            ids.append(block.get("file_id") or drive_file_id(
                block.get("web_view_link") or block.get("url")) or "")

    learn = _phase_products(state, "closeout", "learnings")
    if isinstance(learn, dict):
        _add(learn, "summary_file_id", "new_pdd_file_id")

    return [fid for fid in ids if fid]


# ─── Per-section readers ───────────────────────────────────────────


def _read_opp(state: dict, opp_yaml: dict, *, workspace_slug: str,
              opp_slug: str, run_id: str) -> dict:
    pdd = _phase_products(state, "idea-to-design", "pdd") or _phase_products(state, "design", "pdd")
    connect = _phase_products(state, "connect-setup", "connect")
    connect_opp = connect.get("opportunity") or {}
    cycle_grade = _phase_products(state, "closeout", "cycle_grade")

    display_name = (
        pdd.get("title")
        or opp_yaml.get("display_name")
        or opp_slug
    )
    description = pdd.get("description") or ""
    end_date = connect_opp.get("end_date") or connect.get("end_date")

    return {
        "workspace_slug": workspace_slug,
        "slug": opp_slug,
        "run_id": run_id,
        "display_name": display_name,
        "description": description,
        "status": _resolve_status(cycle_grade, end_date),
        "end_date": end_date,
    }


def _resolve_status(cycle_grade: dict, end_date_iso: str | None) -> str:
    """Closed when cycle-grade exists; otherwise active if end_date is future."""
    if cycle_grade and cycle_grade.get("letter"):
        return "closed"
    if end_date_iso and _is_future(end_date_iso):
        return "active"
    return "in_progress"


def _is_future(date_iso: str) -> bool:
    try:
        d = date.fromisoformat(str(date_iso)[:10])
    except (TypeError, ValueError):
        return False
    return d >= date.today()


def _read_apps(state: dict, access: LinkAccessReader | None = None) -> list[dict]:
    all_products = _phase_products(state, "commcare-setup")
    apps_block = all_products.get("apps") or {}
    out: list[dict] = []
    for kind_key, kind_label in (("learn", "Learn"), ("deliver", "Deliver")):
        # Old schema: products.apps.learn / products.apps.deliver
        app = apps_block.get(kind_key) if isinstance(apps_block, dict) else None
        # New schema: products.learn_app / products.deliver_app
        if not app or not isinstance(app, dict):
            app = all_products.get(f"{kind_key}_app")
        if not isinstance(app, dict) or not app:
            continue
        # nova_url is deliberately NOT surfaced on the public payload: the
        # Nova build tool has no valid public URL (nova.dimagi.com fails DNS,
        # commcare.app/apps/<id> 404s) and it's an internal artifact anyway.
        # hq_url is the real, stakeholder-facing app link.
        hq_url = app.get("hq_url")
        if not hq_url and app.get("hq_app_id"):
            domain = app.get("domain") or apps_block.get("domain") or _connect_domain(state)
            if domain:
                hq_url = f"https://www.commcarehq.org/a/{domain}/apps/view/{app['hq_app_id']}/"
        out.append({
            "kind": kind_label,
            "name": app.get("name") or f"{kind_label} app",
            "hq_url": hq_url,
            # HQ app pages need project-space membership — which a released
            # reviewer HAS when the app is in the opp's own space.
            "access": _tenant_tag(bool(access) and access.tenancy.hq_app(hq_url)),
        })
    return out


#: Phase statuses that mean "this phase did NOT simply finish clean".
#: `partial` is the one the Phase Write-Back Contract actually produces
#: for a phase that shipped every artifact but failed a hard gate.
_INCOMPLETE_PHASE_STATUSES = {"partial", "blocked", "failed", "halted", "error"}

#: Phase verdicts that read as clean. Anything else — including the
#: compound verdicts ACE writes, like
#: `partial-deliver-eval-blocked-on-phase1-gap` — is a qualifier a reader
#: needs, not a value to swallow.
_CLEAN_PHASE_VERDICTS = {"pass", "passed", "clean", "ok", "done", ""}


def _read_build(state: dict, phase_key: str) -> dict | None:
    """The producing phase's own verdict on what it built, or ``None`` when
    it finished clean.

    The Phase Write-Back Contract makes every phase record
    ``{status, verdict, ...}``, and `commcare-setup` on
    ``spark-facilitator/20260828-0703`` recorded::

        status: partial
        verdict: partial-deliver-eval-blocked-on-phase1-gap
        steps.pdd-to-deliver-app-eval.verdict: fail   # entity_state_fidelity

    …and the ``COMMCARE APPS`` section rendered both apps with no
    qualifier of any kind. A reader could not tell that run apart from
    one where everything passed, which is ace-web#744's complaint in the
    section where it is most consequential: ``entity_state_fidelity`` is
    the payment-key gate.

    The vocabulary for saying this honestly already existed on this page
    — the Phase 7 walkthrough prints *"eval 2/5 · the review loop stopped
    before it converged"* rather than hiding a low score. This is that
    same treatment applied to Phase 3, so the fix is a consistency fix
    rather than a new idea. As there, a run that says nothing gets
    nothing invented on its behalf: no phase block, or a clean one, and
    this returns ``None`` and the section renders exactly as before.

    ``blocker_dispositions`` is read alongside, because a blocker the
    operator explicitly waved through is the case where the page most
    needs to say so, and some runs record it only there.
    """
    phase = _phase(state, phase_key)
    if not phase:
        return None

    status = str(phase.get("status") or "").strip().lower()
    verdict = str(phase.get("verdict") or "").strip()
    note = phase.get("status_note") or phase.get("blocked_reason")
    note = " ".join(note.split()) if isinstance(note, str) and note.strip() else None

    failing: list[dict] = []
    steps = phase.get("steps")
    if isinstance(steps, dict):
        for name, step in steps.items():
            if not isinstance(step, dict):
                continue
            step_verdict = str(step.get("verdict") or "").strip().lower()
            if step_verdict not in _FAILING_VERDICTS:
                continue
            detail = step.get("blocker_open_detail") or step.get("note")
            failing.append({
                "name": str(name),
                "verdict": step_verdict,
                "detail": (
                    " ".join(detail.split())
                    if isinstance(detail, str) and detail.strip()
                    else None
                ),
            })

    carried: list[dict] = []
    dispositions = state.get("blocker_dispositions")
    if isinstance(dispositions, dict):
        for disposition_id, entry in dispositions.items():
            if not isinstance(entry, dict):
                continue
            if str(entry.get("phase") or "").strip() != phase_key:
                continue
            carried.append({
                # NOT `key`: the contract's secret-shaped-value detector
                # keys on the NAME, and a public field called `key` is
                # exactly the shape it exists to catch. This is a
                # run_state identifier, so it is named as one.
                "id": str(disposition_id),
                "gate": entry.get("gate") or entry.get("eval") or None,
                "disposition": entry.get("disposition") or None,
                "residual_accepted": (
                    " ".join(str(entry["residual_accepted"]).split())
                    if entry.get("residual_accepted")
                    else None
                ),
            })

    incomplete = (
        status in _INCOMPLETE_PHASE_STATUSES
        or verdict.strip().lower() not in _CLEAN_PHASE_VERDICTS
    )
    if not (incomplete or failing or carried):
        return None

    return {
        "status": status or None,
        "verdict": verdict or None,
        "note": note,
        "failing_checks": failing,
        "carried_blockers": carried,
    }


def _read_carried_residuals(state: dict) -> list[str] | None:
    """Run-level residuals the run itself says still need a human (ace-web#744).

    ``blocker_dispositions`` (read per-phase above) covers a blocker the operator
    explicitly waved through. This is its RUN-level sibling:
    ``run_notes.carried_residuals_needing_a_human`` — a list of reviewer-facing
    prose the run wrote about what it did NOT prove.

    Why it belongs on the public page rather than in the internal record only:
    on ``bednet-check-2-visit/20260828-0629`` the run finished phases 1-8 carrying

        PAYMENT GATE UNPROVEN END-TO-END … the single most important server-side
        control in this programme is configured but never exercised.

    and the summary page rendered **identically to a clean run**. A reader could
    not tell the difference, which is the failure mode this whole section exists
    to prevent: a partial run that reads as a finished one.

    Phase-scoped, deliberately not: a residual is written when it CARRIES past the
    phase that found it, so pinning it to one phase would file it under a stage the
    reader has already scrolled past.

    Degrades to ``None`` — and so to rendering nothing at all — on every run
    without the key, which is every run before it was introduced. Entries are
    whitespace-collapsed because the source is wrapped YAML prose; non-string and
    empty entries are dropped rather than rendered as blanks.
    """
    notes = state.get("run_notes")
    if not isinstance(notes, dict):
        return None
    raw = notes.get("carried_residuals_needing_a_human")
    if not isinstance(raw, list):
        return None
    out = [
        " ".join(str(item).split())
        for item in raw
        if isinstance(item, str) and item.strip()
    ]
    return out or None


def _connect_domain(state: dict) -> str | None:
    """Extract the HQ domain from connect-setup products.

    Defensive: also looks at the products root, since some runs wrote the
    connect block flat (`products.domain`) instead of nested under
    `products.connect` (jjackson/ace#705).
    """
    connect = _phase_products(state, "connect-setup", "connect")
    root = _phase_products(state, "connect-setup")
    return (
        connect.get("domain")
        or connect.get("organization_slug")
        or root.get("domain")
        or root.get("organization_slug")
    )


def _display_opportunity_name(name: str, run_id: str | None) -> str:
    """The opportunity name without ACE's leading ``<run_id> · ``.

    ACE prefixes every per-run opportunity's name with its run id on
    purpose — several runs of one opp each create an opportunity, and the
    prefix is what tells them apart inside Connect. On this page the run
    id is already in the header, and a title that opens with
    ``20261001-2208 ·`` reads to an outsider as a code, not a name. Only
    the DISPLAYED name changes; the opportunity in Connect keeps it.
    """
    if not run_id:
        return name
    stripped = re.sub(
        rf"^\s*{re.escape(run_id)}\s*[·•|:—–-]\s*", "", name,
    )
    return stripped or name


def _read_connect(
    state: dict,
    access: LinkAccessReader | None = None,
    *,
    run_id: str | None = None,
) -> dict | None:
    """Public payload surfaces only the Connect *opportunity*.

    The program URL (``connect.dimagi.com/a/<domain>/program/<uuid>/``) is
    NOT a stakeholder page — it 404s even unauthenticated — so it's omitted.
    The opportunity URL correctly 302s to sign-in, so it stays.
    """
    connect = _phase_products(state, "connect-setup", "connect")
    # Defensive fallback: some runs wrote the opportunity flat at products.*
    # instead of nested under products.connect (jjackson/ace#705). Accept both.
    root = _phase_products(state, "connect-setup")
    # Old schema: connect.opportunity.{id, name, url}; new schema: connect.opportunity_id
    opp = connect.get("opportunity") or root.get("opportunity") or {}

    opp_id = opp.get("id") or connect.get("opportunity_id")
    # `connect-opp-setup` writes the live URL as `opportunity.deep_link`,
    # so check that level first; the `connect.deep_link` fallback covers
    # the flatter alt-schema some runs use.
    opp_url = opp.get("url") or opp.get("deep_link") or connect.get("deep_link")
    if not (opp_id or opp_url):
        return None
    return {
        "opportunity": {
            "name": _display_opportunity_name(
                opp.get("name") or connect.get("opportunity_name") or "Connect opportunity",
                run_id,
            ),
            "url": opp_url,
            "start_date": opp.get("start_date") or connect.get("start_date"),
            "end_date": opp.get("end_date") or connect.get("end_date"),
            # Connect gates opportunity pages on org membership — which a
            # released reviewer HAS for the opp's own PM / holding org.
            "access": _tenant_tag(bool(access) and access.tenancy.connect(opp_url)),
        },
    }


_TRAINING_DOC_TITLES = {
    "llo_guide": "Guide for the implementing organisation (LLO)",
    "flw_guide": "Guide for field workers (FLW)",
}


def _read_training(state: dict, access: LinkAccessReader) -> dict | None:
    """The training pack. Every entry's ``access`` is measured, not
    asserted — see ``_read_design``. On the audited run these documents
    happened to be anyone-with-link readable while the design docs were
    not, which is exactly why a blanket ``public`` on both was never
    evidence of anything."""
    training = _phase_products(state, "qa-and-training", "training")
    # Defensive fallback: some runs wrote the deck / onboarding email under
    # products.training_materials instead of products.training (jjackson/ace#705).
    materials = _phase_products(state, "qa-and-training", "training_materials")
    if not training and not materials:
        return None

    deck_block = None
    deck = training.get("deck") or materials.get("deck") or {}
    if deck.get("file_id") or deck.get("web_view_link"):
        deck_block = {
            "title": deck.get("title") or "Training deck",
            "url": deck.get("web_view_link"),
            "access": access.tag(
                file_id=deck.get("file_id"), url=deck.get("web_view_link"),
            ),
        }

    docs_block = training.get("docs") or {}
    # The two guides get a plain title of our own, whatever the run wrote:
    # ACE titles them "LLO manager guide" / "FLW training guide", and an
    # outside reader knows neither acronym. The acronym stays, in brackets,
    # because the documents themselves use it throughout.
    docs: list[dict] = []
    # Preserve a stable display order matching agent-doc convention.
    for key in ("llo_guide", "flw_guide", "quick_reference", "faq", "onboarding_email"):
        doc = docs_block.get(key) or materials.get(key) or {}
        if doc.get("web_view_link") or doc.get("file_id"):
            docs.append({
                "title": (
                    _TRAINING_DOC_TITLES.get(key)
                    or doc.get("title")
                    or key.replace("_", " ").title()
                ),
                "url": doc.get("web_view_link"),
                "access": access.tag(
                    file_id=doc.get("file_id"), url=doc.get("web_view_link"),
                ),
            })

    if deck_block is None and not docs:
        return None
    return {"deck": deck_block, "docs": docs}


def _read_assistant(state: dict) -> dict | None:
    """Support-assistant credentials for the OCS widget.

    ``embed_key`` is served on the PUBLIC payload, deliberately. The
    OCS widget is a browser component: it authenticates the anonymous
    visitor's chat session with ``chatbot-id`` + ``embed-key`` from the
    page itself, so any key that reaches the widget is by construction
    readable by anyone who can load the page. There is no server-side
    variant of the widget to proxy it behind, and dropping the key from
    the payload removes the "Need help?" assistant entirely — the one
    interactive thing an external reviewer can use.

    What that means in practice: the key authorises starting sessions
    against this opportunity's bot, and the same bot is used for QA. It
    is a per-chatbot public identifier, NOT an OCS account credential —
    it cannot read other chatbots, other teams, or existing transcripts.
    The exposure is therefore "someone can talk to this bot", bounded by
    whatever rate limiting OCS applies.

    Reviewed 2026-08-14 (ace-web#706) and left in place as an accepted,
    documented exposure rather than silently removed. If we ever want it
    gone, the fix is upstream: a session-scoped token minted server-side
    by OCS, or an ace-web proxy endpoint that starts the session and
    hands the widget a short-lived token. Both are OCS-side work.
    """
    chatbot = _phase_products(state, "ocs-setup", "ocs_chatbot")
    public_id = chatbot.get("public_id")
    embed_key = chatbot.get("embed_key")
    if not public_id or not embed_key:
        return None
    return {
        "ocs_url": chatbot.get("admin_url"),
        # The OCS console needs team membership and stays Dimagi-internal
        # even on an own-tenancy opp: reviewers use the public chatbot (the
        # WIDGET below needs no account, which is why the embed key stays
        # on the public payload).
        "access": ACCESS_ADMIN,
        "public_id": public_id,
        "embed_key": embed_key,
        "knowledge_sources": _knowledge_sources(chatbot),
    }


# What a producing phase may write to say what it actually indexed.
# ``knowledge_sources`` is the name to use; the others are accepted
# because a phase writing this for the first time reasonably reaches for
# either, and a miss here is silent (ace#1432).
_KNOWLEDGE_SOURCE_KEYS = ("knowledge_sources", "knowledge", "indexed_sources")


def _knowledge_sources(chatbot: dict) -> list[str]:
    """What the assistant was actually given, as the run recorded it.

    Empty when the run recorded nothing — which is the common case
    today, and the page MUST then say nothing about what the bot knows.

    Until ace-web#740 the page carried a hard-coded sentence: "Trained
    on the design doc, training pack, and app guides for this
    opportunity." It was derived from nothing. On
    ``spark-facilitator/20260820-0817`` the opp collection (OCS 567) held
    16 files — ``00-program-contacts.md`` through
    ``15-connect-setup-summary.md`` — and **none of the five training-pack
    documents the same page links were among them**; the run state says
    so in as many words ("Phase 6 training docs are not in collection 567
    - Phase 6 has not run"). The design doc and the app summaries WERE
    there, which is what made the sentence plausible enough to survive.

    ACE shipped ``ocs-knowledge-refresh`` (ace#1715) so later runs do
    index the training docs. That is exactly why this must be data: the
    claim becomes true for some runs and stays false for others, and a
    constant string cannot tell them apart.
    """
    for key in _KNOWLEDGE_SOURCE_KEYS:
        raw = chatbot.get(key)
        if isinstance(raw, str):
            raw = [raw]
        if not isinstance(raw, list):
            continue
        out = [
            " ".join(item.split())
            for item in raw
            if isinstance(item, str) and item.strip()
        ]
        if out:
            return out
    return []


_SYNTHETIC_PHASE = "synthetic-data-and-workflows"

# An eval verdict that means "produced, but we are not showing it".
_FAILING_VERDICTS = {"fail", "failed", "halt", "blocked", "reject"}

_DASHBOARD_URL_KEYS = ("url", "par_url", "run_url", "web_view_link")

# Tokens that should stay upper-case when a machine key is humanised.
_ACRONYMS = {"llo", "flw", "ocs", "qa", "ace", "kpi", "pdd", "cbf", "hq"}


def _humanize(key: str) -> str:
    """``llo_weekly`` → ``LLO weekly``; ``verification-integrity`` →
    ``Verification integrity``. Used only for machine keys — a real
    ``title`` is passed through verbatim."""
    words = key.replace("_", " ").replace("-", " ").split()
    if not words:
        return ""
    out = [w.upper() if w.lower() in _ACRONYMS else w.lower() for w in words]
    if out[0].lower() not in _ACRONYMS:
        out[0] = out[0].capitalize()
    return " ".join(out)


# Every key a producer has actually written a walkthrough URL under. This
# list is a compatibility surface, not a spec: Phase 7 writes whichever
# name reads well next to its siblings, and an unrecognised one used to
# mean the entry vanished from the page entirely (ace#1432 — the spark
# run wrote ``video_web_view_link`` and the walkthrough silently became
# ``walkthroughs: []``). Add to it freely; never let a miss be silent.
_WALKTHROUGH_URL_KEYS = (
    "slideshow_url",
    "web_view_link",
    "url",
    "video_url",
    "video_web_view_link",
    "video_link",
)


# ─── Author-declared walkthrough state ─────────────────────────────
#
# A producing phase may declare a walkthrough's own state in
# ``run_state.yaml`` — ``availability`` / ``access`` / ``withheld_reason``
# — and this reader honours it. Until ace-web#726 it did not: every entry
# was emitted ``access: public`` / ``availability: available`` /
# ``withheld_reason: null`` no matter what the run had written. That
# advertised a canopy-web DDD package sitting behind Dimagi OAuth to
# anonymous readers as public, which is worse than a dead link: a dead
# link reads as broken, this reads as an invitation. And there was no
# data-side workaround — leaving the entry in tripped the ACE auditor's
# ``LINK-ACCESS-MISLABELLED``, removing it tripped ``WALKTHROUGH-DROPPED``
# — so a correct run could not reach "safe to share" at all.
#
# The payload's ``access`` vocabulary stays two-valued (``public`` /
# ``admin``): the frozen contract in
# ``apps/opps/tests/test_public_surface_contract.py`` and the ACE auditor
# both key on exactly those. Author words are normalised INTO it rather
# than widening it, so a phase can write whichever word reads well
# ("auth-gated", "private", "internal") without inventing a third
# vocabulary every consumer would then have to learn.
_ACCESS_ALIASES = {
    "public": ACCESS_PUBLIC,
    "anonymous": ACCESS_PUBLIC,
    "anyone": ACCESS_PUBLIC,
    "anyone-with-link": ACCESS_PUBLIC,
    "link": ACCESS_PUBLIC,
    "open": ACCESS_PUBLIC,
    "shared": ACCESS_PUBLIC,
    "admin": ACCESS_ADMIN,
    "auth": ACCESS_ADMIN,
    "auth-gated": ACCESS_ADMIN,
    "authenticated": ACCESS_ADMIN,
    "dimagi": ACCESS_ADMIN,
    "gated": ACCESS_ADMIN,
    "internal": ACCESS_ADMIN,
    "login": ACCESS_ADMIN,
    "login-required": ACCESS_ADMIN,
    "member": ACCESS_ADMIN,
    "members-only": ACCESS_ADMIN,
    "oauth": ACCESS_ADMIN,
    "private": ACCESS_ADMIN,
    "restricted": ACCESS_ADMIN,
}

# ─── The DDD loop's own honesty record ─────────────────────────────
#
# A walkthrough's ``eval_score`` is produced by canopy's DDD loop, and
# the loop records ALONGSIDE it the facts that decide whether the score
# means anything. Until ace-web#740 this reader took the number and
# dropped every one of them, so the page showed a score with no way to
# read it. On ``spark-facilitator/20260820-0817`` the run state said:
#
#     ddd_terminal_status: stopped_not_converged
#     ddd_iterations_completed_end_to_end: 0
#     ddd_render_measures_pre_fix_artifact: true
#     ddd_honesty_note: "READ THIS BEFORE QUOTING THE 2.0. ..."
#
# and the page rendered "eval 2/10" and a link to the video. The video
# films the PRE-FIX product: four accuracy fixes landed during the
# iteration and appear in no captured frame.
#
# Two rules follow, and both are why this is not a boolean:
#
# 1. ``terminal_status`` is FOUR-VALUED and must stay that way.
#    "converged, good" and "converged, still failing" must not render
#    identically, so a pass/fail collapse is forbidden here — that is
#    precisely the information a reader needs.
# 2. ``render_measures_pre_fix_artifact`` is a HARD CAVEAT, not a note.
#    It says the score and the video measure an artifact that has since
#    been fixed. A published video filmed against a pre-fix product,
#    presented bare, is the specific thing this must never do again.
#
# The plugin writes these as SIBLINGS of ``walkthroughs`` under
# ``products.synthetic`` (they describe the loop, not one entry), but an
# entry may carry its own — a run with two narratives would need to.
# Entry-level wins; the phase-level block is the fallback.
_DDD_TERMINAL_STATUSES = frozenset({
    "converged_clean",
    "converged_with_open_questions",
    "stopped_not_converged",
    "diverging",
})

AVAILABILITY_AVAILABLE = "available"
AVAILABILITY_WITHHELD = "withheld"
AVAILABILITY_UNAVAILABLE = "unavailable"
_AVAILABILITY_VALUES = frozenset({
    AVAILABILITY_AVAILABLE, AVAILABILITY_WITHHELD, AVAILABILITY_UNAVAILABLE,
})

# canopy-web is served same-origin under ``/canopy/*`` on labs. Its own
# auth middleware is default-deny with a small allowlist of SPA shells
# that self-enforce a share token — canopy-web
# ``apps/common/middleware.py``, pinned by its
# ``tests/test_public_routes_reachable.py``, which asserts
# ``/ddd-release/<slug>/<run-id>`` is anonymously reachable and
# ``/ddd/<slug>`` — the operator console — is NOT
# (``test_the_ddd_console_is_gated_even_though_ddd_release_is_public``).
# So a canopy link is public only when its path is on that allowlist;
# every other canopy path is a Dimagi OAuth wall. This is the derived
# DEFAULT — an author-supplied tag always wins over it.
_CANOPY_PUBLIC_PREFIXES = (
    "/ddd-release/",
    "/invite/",
    "/narrative/",
    "/review/",
    "/share/",
    "/storyboard/",
    "/walkthrough/",
)


def _normalise_access(value: object) -> str | None:
    """An author's access word as one of this module's ``ACCESS_*``
    constants, or ``None`` when it is absent or unrecognised."""
    if not isinstance(value, str) or not value.strip():
        return None
    key = value.strip().lower().replace("_", "-").replace(" ", "-")
    resolved = _ACCESS_ALIASES.get(key)
    if resolved is None:
        log.warning(
            "summary: walkthrough declares access=%r, which is not a recognised "
            "alias of %r/%r — ignored, tag derived from the URL instead",
            value, ACCESS_PUBLIC, ACCESS_ADMIN,
        )
    return resolved


def _canopy_path(url: str) -> str | None:
    """The canopy-web path a URL addresses, or ``None`` if it is not a
    canopy-web URL. Labs mounts canopy under ``/canopy/``; a dedicated
    canopy host serves the same routes at the root."""
    if not isinstance(url, str):
        return None
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    path = parsed.path or "/"
    if path == "/canopy" or path.startswith("/canopy/"):
        return path[len("/canopy"):] or "/"
    host = (parsed.hostname or "").lower()
    if host.startswith("canopy.") or host.startswith("canopy-"):
        return path
    return None


def _derive_walkthrough_access(url: str) -> str:
    """Access tag for a walkthrough link the run did not tag itself.

    Only canopy-web URLs are reclassified: everything else keeps the
    long-standing ``public`` default (a walkthrough is otherwise a Drive
    file or a token-minted share, both of which circulate by design).
    Guessing ``admin`` for an unknown host would tell a reader they
    cannot open something they can — the same class of lie, pointed the
    other way.
    """
    path = _canopy_path(url)
    if path is None:
        return ACCESS_PUBLIC
    if any(path.startswith(prefix) for prefix in _CANOPY_PUBLIC_PREFIXES):
        return ACCESS_PUBLIC
    return ACCESS_ADMIN


def _ddd_honesty(entry: dict, phase_block: dict) -> dict:
    """The DDD loop's qualifiers for one walkthrough entry.

    Entry-level keys win; the ``products.synthetic``-level block is the
    fallback, because that is where the plugin actually writes them.
    Every field is independently nullable — a run that recorded none of
    them renders exactly as before, with no invented reassurance.

    An unrecognised ``terminal_status`` is passed through rather than
    dropped: a new status the loop invents should show up as itself, not
    vanish into "no status recorded" (the same failure class as the
    dropped walkthrough URL key, ace#1432). It is logged so the
    vocabulary above can be updated.
    """
    def _pick(key: str):
        if key in entry:
            return entry.get(key)
        return phase_block.get(key)

    status = _pick("ddd_terminal_status")
    status = status.strip() if isinstance(status, str) and status.strip() else None
    if status and status not in _DDD_TERMINAL_STATUSES:
        log.warning(
            "summary: walkthrough declares ddd_terminal_status=%r, not one of %s "
            "— surfaced verbatim; add it to _DDD_TERMINAL_STATUSES if it is real",
            status, sorted(_DDD_TERMINAL_STATUSES),
        )

    iterations = _pick("ddd_iterations_completed_end_to_end")
    if not isinstance(iterations, int) or isinstance(iterations, bool):
        iterations = None

    note = _pick("ddd_honesty_note")
    note = " ".join(note.split()) if isinstance(note, str) and note.strip() else None

    return {
        "terminal_status": status,
        "iterations_completed": iterations,
        # Default FALSE, not None: this is a caveat, and a run that says
        # nothing is not asserting the caveat. The honest-unknown case
        # here is "no DDD block at all", which the null status already
        # carries.
        "measures_pre_fix_artifact": bool(_pick("ddd_render_measures_pre_fix_artifact")),
        "note": note,
    }


def _read_walkthroughs(state: dict) -> list[dict]:
    """Persona walkthroughs, as one of four honest states per entry.

    ``availability`` is the point of this reader. A run can have

    - **nothing** — no entry at all; the section renders "Not created";
    - **withheld** — a walkthrough was produced but its concept eval
      failed, so we do not put it in front of a stakeholder. It still
      says so, with no link;
    - **unavailable** — produced, and either carrying no URL under any
      key this reader recognises, or deliberately not shared (the run
      said so itself);
    - **available** — produced, cleared, linked.

    Every state above exists to serve one rule: **a reviewer must never
    be told something does not exist when it does.** The first version
    of this reader broke that rule for withheld walkthroughs, which
    rendered as "Not created". Its docstring then claimed a URL-less
    entry was "dropped, loudly" — but loud meant ``log.warning``, which
    no reviewer will ever read, and the page still said nothing was
    produced. That is the same bug wearing the word "loudly", and it
    cost a real run: spark-facilitator/20260813-2126 wrote its video
    under ``video_web_view_link``, the key list did not include it, and
    a passing walkthrough served as ``walkthroughs: []`` (ace#1432).

    So: loud now means *visible on the page*. A URL-less non-withheld
    entry is surfaced as ``unavailable`` with its keys logged for the
    one-line fix. Nothing a run produced is ever dropped here.

    **The run gets a say (ace-web#726).** An entry may declare its own
    ``availability`` / ``access`` / ``withheld_reason``, and those win
    over anything derived here — that is how a producing phase says
    "produced, deliberately not shared" (a DDD package whose
    ``external_release`` gate resolved HOLD) or "this link needs a
    Dimagi login". One asymmetry, deliberate: an author declaration may
    only make an entry LESS visible, never more. A failing eval verdict
    is a guard against putting a bad demo in front of a stakeholder, and
    an ``availability: available`` in the run state does not lift it.

    An entry is withheld when its own ``eval_verdict`` is failing, or —
    for entries that carry no verdict of their own — when the phase's
    verdict is. Note that ``warn`` is deliberately *not* failing: a
    warn-verdict walkthrough is shown, because withholding everything
    short of a clean pass withholds permanently.
    """
    synthetic = _phase_products(state, _SYNTHETIC_PHASE, "synthetic")
    phase_verdict = str(_phase(state, _SYNTHETIC_PHASE).get("verdict") or "").lower()
    phase_failed = phase_verdict in _FAILING_VERDICTS

    raw = synthetic.get("walkthroughs") or []
    if not isinstance(raw, list):
        return []

    # Converged Phase 7 (the /ace:demo pipeline) writes one narrative-wide
    # walkthrough with no persona, so name it after the narrative.
    narrative = synthetic.get("narrative") or {}
    default_name = _humanize(
        str(narrative.get("narrative_slug") or "") if isinstance(narrative, dict) else ""
    ) or "Walkthrough"

    out: list[dict] = []
    for w in raw:
        if not isinstance(w, dict):
            log.warning("summary: walkthrough entry is not a mapping — skipped")
            continue
        url = next((w[k] for k in _WALKTHROUGH_URL_KEYS if w.get(k)), None)
        verdict = str(w.get("eval_verdict") or "").lower()
        withheld = verdict in _FAILING_VERDICTS or (not verdict and phase_failed)
        persona = w.get("persona") or default_name
        declared_reason = w.get("withheld_reason")
        declared_reason = (
            declared_reason.strip()
            if isinstance(declared_reason, str) and declared_reason.strip()
            else None
        )

        declared = w.get("availability")
        declared = declared.strip().lower() if isinstance(declared, str) else None
        if declared is not None and declared not in _AVAILABILITY_VALUES:
            log.warning(
                "summary: walkthrough %r declares availability=%r, which is not one "
                "of %s — ignored, state derived instead",
                persona, w.get("availability"), sorted(_AVAILABILITY_VALUES),
            )
            declared = None

        # The loop's own qualifiers ride on EVERY state, including the
        # ones that show no score: a reader looking at a withheld
        # walkthrough still needs to know the loop stopped without
        # converging.
        ddd = _ddd_honesty(w, synthetic)

        if withheld or declared == AVAILABILITY_WITHHELD:
            out.append({
                "persona": persona,
                "url": None,
                "eval_score": None,
                "availability": AVAILABILITY_WITHHELD,
                "withheld_reason": (
                    declared_reason or "Not shown — did not pass quality review"
                ),
                "ddd": ddd,
            })
            continue
        if declared == AVAILABILITY_UNAVAILABLE:
            # The run produced this and chose not to share it — e.g. a DDD
            # package whose external_release gate resolved HOLD. Name it,
            # say why, hand out no link.
            out.append({
                "persona": persona,
                "url": None,
                "eval_score": w.get("eval_score"),
                "availability": AVAILABILITY_UNAVAILABLE,
                "withheld_reason": (
                    declared_reason or "Produced, but not shared for this run."
                ),
                "ddd": ddd,
            })
            continue
        if not url:
            # A produced walkthrough with no URL we recognise is the one
            # case that must never be silent. Dropping it renders the page
            # as if Phase 7 produced nothing, which is indistinguishable
            # from a run that genuinely didn't — the reader is then lying
            # by omission about work that exists. Surface it instead, and
            # name the keys the entry did carry so the fix is one line.
            log.warning(
                "summary: walkthrough %r has no recognised url key "
                "(carried=%s, accepted=%s) — surfaced as unavailable",
                persona, sorted(w), list(_WALKTHROUGH_URL_KEYS),
            )
            out.append({
                "persona": persona,
                "url": None,
                "eval_score": w.get("eval_score"),
                "availability": AVAILABILITY_UNAVAILABLE,
                "withheld_reason": declared_reason or (
                    "Produced, but no shareable link was recorded in a "
                    "form this page recognises."
                ),
                "ddd": ddd,
            })
            continue
        out.append({
            "persona": persona,
            "url": url,
            "eval_score": w.get("eval_score"),
            "availability": AVAILABILITY_AVAILABLE,
            "withheld_reason": None,
            # The run's own tag wins; otherwise derive it from the link.
            # A published walkthrough is usually a Drive file or a
            # canopy-web share minted with a link-visibility token — both
            # circulate by design — but a canopy OPERATOR URL sits behind
            # Dimagi OAuth and the page has to say so.
            "access": _normalise_access(w.get("access")) or _derive_walkthrough_access(url),
            "ddd": ddd,
        })
    return out


def _read_synthetic(state: dict) -> dict | None:
    """Where the numbers on the dashboards and in the demo came from.

    Phase 7 generates a dataset. Nothing on this page said so. On
    ``spark-facilitator/20260828-0703`` the ``DASHBOARDS`` section listed
    *Verification* and *Weekly review* with no qualifier at all, while
    the run state recorded ``provider: ace-run``,
    ``labs_synthetic_opp_id: 10054``, ``user_visits: 223``,
    ``user_data: 12`` and ``completed_works: 0`` — 223 generated visit
    records attributed to 12 invented facilitators, none of them real
    programme activity. An external reader opening those dashboards had
    nothing telling them the cohort is fictional, and the named
    facilitators, the coaching task and the three planted anomalies all
    read as observations.

    This is the sibling of the walkthrough caveats and the build verdict:
    a number the page shows must carry what it is a number OF. Every
    field is read from the run's own ``products.synthetic.source`` block
    — nothing is hardcoded and nothing is inferred, so a run that
    recorded no counts renders the label without them rather than
    inventing a figure.

    Returns ``None`` when the run has no synthetic block at all, so a run
    that generated nothing is not labelled as if it had.
    """
    synthetic = _phase_products(state, _SYNTHETIC_PHASE, "synthetic")
    if not isinstance(synthetic, dict) or not synthetic:
        return None
    source = synthetic.get("source")
    source = source if isinstance(source, dict) else {}

    counts = source.get("record_counts")
    counts = counts if isinstance(counts, dict) else {}

    def _count(key: str) -> int | None:
        value = counts.get(key)
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    shape = source.get("data_shape")
    shape = shape if isinstance(shape, dict) else {}
    cohort = shape.get("rows")
    if not (isinstance(cohort, int) and not isinstance(cohort, bool)):
        cohort = _count("user_data")

    population = shape.get("rows_population")
    # The run writes this as "user_data — the facilitator cohort, …";
    # the schema key is machinery, the clause after it is the English.
    if isinstance(population, str) and population.strip():
        population = population.split("\u2014", 1)[-1].strip().rstrip(".")
        population = population or None
    else:
        population = None

    labs_opp_id = source.get("labs_synthetic_opp_id")
    if not (isinstance(labs_opp_id, int) and not isinstance(labs_opp_id, bool)):
        labs_opp_id = None

    return {
        "is_synthetic": True,
        "provider": str(source.get("provider") or "").strip() or None,
        "labs_opp_id": labs_opp_id,
        "visits": _count("user_visits"),
        "completed_works": _count("completed_works"),
        "cohort_size": cohort,
        "cohort_population": population,
    }


def _read_dashboards(state: dict, access: LinkAccessReader | None = None) -> list[dict]:
    """Demo dashboards for the run — every shape Phase 7 actually writes.

    The reader used to accept exactly one shape:
    ``synthetic.dashboards[] = {title, url}``. Phase 7 writes
    ``synthetic.source.dashboards[] = {key, par_url, ...}`` and
    ``synthetic.workflows{<key>: {run_url}}`` — so entries were dropped
    for having no ``url`` key and the page told reviewers "Dashboards —
    Not created" while two live dashboards existed
    (spark-facilitator/20260813-2126, workflows 5117 + 5125).

    All three locations are read; entries are de-duplicated by URL in
    first-seen order. A dropped entry is logged rather than swallowed —
    a silent key-contract mismatch is what caused the original bug.
    """
    synthetic = _phase_products(state, _SYNTHETIC_PHASE, "synthetic")
    source = synthetic.get("source") or {}
    if not isinstance(source, dict):
        source = {}

    candidates: list[tuple[str, dict]] = []
    for where, block in (
        ("synthetic.dashboards", synthetic.get("dashboards")),
        ("synthetic.source.dashboards", source.get("dashboards")),
    ):
        if block is None:
            continue
        if not isinstance(block, list):
            log.warning("summary: %s is not a list — ignored", where)
            continue
        for entry in block:
            candidates.append((where, entry))

    workflows = synthetic.get("workflows")
    if isinstance(workflows, dict):
        for key, wf in workflows.items():
            if isinstance(wf, dict):
                candidates.append(("synthetic.workflows", {"key": key, **wf}))

    out: list[dict] = []
    seen: set[str] = set()
    for where, d in candidates:
        if not isinstance(d, dict):
            log.warning("summary: dashboard entry at %s is not a mapping — skipped", where)
            continue
        url = next((d[k] for k in _DASHBOARD_URL_KEYS if d.get(k)), None)
        if not url:
            log.warning(
                "summary: dashboard entry at %s has no url (keys=%s) — skipped",
                where, sorted(d),
            )
            continue
        if url in seen:
            continue
        seen.add(url)
        title = d.get("title") or d.get("name")
        if not title:
            title = _humanize(str(d.get("key") or "")) or "Dashboard"
        out.append({
            "title": title,
            "url": url,
            # connect-labs is opened to the tenancy's labs_allowed_domains;
            # Dimagi-only domains mean only Dimagi can open it.
            "access": _tenant_tag(bool(access) and access.tenancy.labs()),
        })
    return out


def _read_selected_llo(state: dict) -> dict | None:
    llo = _phase_products(state, "solicitation-management", "selected_llo")
    if not llo or not llo.get("org_slug"):
        return None
    return {
        "org_slug": llo.get("org_slug"),
        "org_display_name": llo.get("org_display_name") or llo.get("org_slug"),
        "contact_email": llo.get("contact_email"),
        "awarded_at": llo.get("awarded_at"),
    }


def _read_solicitation(state: dict, access: LinkAccessReader | None = None) -> dict | None:
    sol = _phase_products(state, "solicitation-management", "solicitation")
    if not sol or not (sol.get("url") or sol.get("public_url")):
        return None
    return {
        "url": sol.get("url") or sol.get("public_url"),
        "deadline": sol.get("deadline"),
        "status": sol.get("status"),
        # Published on connect-labs — same rule as the dashboards.
        "access": _tenant_tag(bool(access) and access.tenancy.labs()),
    }


def _read_launch(state: dict) -> dict | None:
    launch = _phase_products(state, "execution-management", "launch")
    if not launch or not launch.get("went_live_at"):
        return None
    return {
        "went_live_at": launch.get("went_live_at"),
        "llo_org_display_name": launch.get("llo_org_display_name") or launch.get("llo_org_slug"),
    }


def _read_cycle_grade(state: dict) -> dict | None:
    grade = _phase_products(state, "closeout", "cycle_grade")
    if not grade or not grade.get("letter"):
        return None
    return {
        "letter": grade.get("letter"),
        "headline": grade.get("headline") or "",
        "overall_score": grade.get("overall_score"),
    }


def _read_opp_eval(state: dict) -> dict | None:
    ev = _phase_products(state, "closeout", "opp_eval")
    if not ev or ev.get("overall_score") is None:
        return None
    return {
        "overall_score": ev.get("overall_score"),
        "verdict": ev.get("verdict"),
        "mode": ev.get("mode"),
    }


def _read_learnings(state: dict, access: LinkAccessReader) -> dict | None:
    """Closeout learnings. ``access`` measured, not asserted — see
    ``_read_design``. One tag covers both links here because the section
    renders one row; it is taken from the summary doc, which is the link
    that is always present."""
    learn = _phase_products(state, "closeout", "learnings")
    if not learn or not (learn.get("summary_file_id") or learn.get("summary_web_view_link")):
        return None
    summary_url = _learnings_link(
        learn.get("summary_web_view_link"), learn.get("summary_file_id"),
    )
    return {
        "summary_url": summary_url,
        "new_pdd_url": _learnings_link(
            learn.get("new_pdd_web_view_link"), learn.get("new_pdd_file_id"),
        ),
        "iteration_warranted": bool(learn.get("iteration_warranted")),
        "access": access.tag(
            file_id=learn.get("summary_file_id"), url=summary_url,
        ),
    }


def _learnings_link(web_view_link: str | None, file_id: str | None) -> str | None:
    """Prefer the producer-recorded webViewLink (plugin v0.13.174+); fall
    back to a constructed Drive blob-preview URL when only file_id is
    present (briefly-populated pre-v0.13.174 runs).
    """
    if web_view_link:
        return web_view_link
    if file_id:
        return f"https://drive.google.com/file/d/{file_id}/view"
    return None


def _read_design(state: dict, access: LinkAccessReader) -> dict | None:
    """Design docs a reviewer needs: the PDD, and the Work Order if present.

    The PDD is the artifact every downstream phase builds on and the one
    a reviewer actually comments on, yet it had no section on the summary
    at all — reviewers were sent a page that linked the training pack but
    not the design it came from.

    Accepts the legacy ``design`` phase key alongside ``idea-to-design``,
    matching ``_read_opp``.

    ``access`` is MEASURED per document (ace-web#740). This reader used
    to stamp ``ACCESS_PUBLIC`` on both entries unconditionally; on the
    audited spark-facilitator run both documents answered 401 to an
    anonymous reader while the page said "Open".
    """
    products = (
        _phase_products(state, "idea-to-design")
        or _phase_products(state, "design")
    )
    docs: list[dict] = []

    for key, fallback_title in (
        ("pdd", "Program Design Document"),
        ("work_order", "Work Order"),
    ):
        block = products.get(key) or {}
        if not isinstance(block, dict):
            continue
        url = block.get("web_view_link") or block.get("url")
        if not url and block.get("file_id"):
            url = f"https://docs.google.com/document/d/{block['file_id']}/edit"
        if url:
            docs.append({
                "title": block.get("title") or fallback_title,
                "url": url,
                "access": access.tag(file_id=block.get("file_id"), url=url),
            })

    return {"docs": docs} if docs else None


# ---------------------------------------------------------------------------
# "What changed because you asked" — the run's frozen claim set.
# ---------------------------------------------------------------------------

#: The verdict vocabulary, from ``lib/run-claims.ts`` in the ACE plugin. A
#: value outside it is carried as "no verdict" rather than coerced onto a
#: known one: a page that quietly mapped an unrecognised verdict onto MET
#: would render an unanswered claim as an answered one, which is the exact
#: silence the claims mechanism exists to kill.
_CLAIM_VERDICTS = ("MET", "UNMET", "NOT REACHED", "INDETERMINATE")


def _claim_summary_line(counts: dict[str, int], total: int) -> str:
    """The tally, word for word as ``summarizeClaims`` composes it.

    Mirrored rather than imported — the plugin is TypeScript and what the
    two share is the CONTRACT, not code. Kept in this shape so the page
    and the reply lead with the same sentence.
    """
    parts = [f"{counts['met']}/{total} met"]
    if counts["unmet"]:
        parts.append(f"{counts['unmet']} not met")
    if counts["not_reached"]:
        parts.append(f"{counts['not_reached']} never reached")
    if counts["indeterminate"]:
        parts.append(f"{counts['indeterminate']} indeterminate")
    if counts["unanswered"]:
        parts.append(f"{counts['unanswered']} still open")
    return ", ".join(parts)


def _read_claims(
    drive: DriveClient, run_folder_id: str, *, viewer_is_member: bool,
) -> dict | None:
    """The run's claim set — "what changed because you asked" (ace#2420).

    A CLAIM is a falsifiable statement about what THIS run's output must
    look like, authored because a named counterpart decided something
    between runs. The design
    (``docs/superpowers/specs/2026-09-15-pre-run-claims-post-run-validation-design.md``
    § Rendering) puts it on two surfaces — this page and the reply — and
    it existed on neither, so a verdict reached the person who made the
    decision only if somebody remembered to write her an email. That
    dependency on a human remembering is what the mechanism was built to
    remove.

    Three properties carry the design's weight, and this reader exists to
    serve them rather than to list claims:

    * **Every claim is carried, whichever way it went.** The claim set is
      the DENOMINATOR, so an UNMET one appears as an accusation rather
      than as an absence — the same completeness property that makes
      ``UNROUTED`` work in the feedback ledger. Nothing here filters.
    * **A claim the counterpart authored is marked as theirs**
      (``authored_by``). ACE writes its own exam here, and the design's
      only mitigation is that the reviewer can see which bar was hers and
      say so when ACE's is too low. A page that did not distinguish them
      would remove the mitigation while looking complete.
    * **``evidence_kind`` is carried** so a ``judged`` verdict renders as
      weaker than a ``probed`` one instead of borrowing its authority.

    ``says`` vs ``evidence``: ``says`` is the counterpart-facing sentence
    and is served to everyone. ``evidence`` is the AUDIT record — Drive
    file ids, MCP atom signatures, internal field names, read-path
    reliability caveats — and is served to workspace MEMBERS only, the
    same confidentiality-shaped exception ``_read_feedback`` makes to this
    module's "every link is served to everyone" rule. For everyone else it
    is ``None`` rather than absent, so both variants of the payload carry
    one shape.

    Returns ``None`` when the run has no ``claims.yaml``, and the section
    then does not render at all: most opportunities have none, and a "no
    claims" heading on every other run teaches reviewers to skip it. An
    UNREADABLE file sets ``error`` and still returns a section, matching
    ``classifyRunClaims``'s ``ok: false`` posture — failing silently would
    put the reviewer back in front of a page that renders an omission as
    an absence.
    """
    f = _find_in_folder(drive, run_folder_id, "claims.yaml")
    if f is None:
        return None

    def _broken(message: str) -> dict:
        return {
            "summary": "the claims recorded for this run could not be read",
            "total": 0,
            "all_met": False,
            "counts": {
                "met": 0, "unmet": 0, "not_reached": 0,
                "indeterminate": 0, "unanswered": 0,
            },
            "error": message,
            "people": [],
        }

    try:
        content = drive.get_content(f.id, f.mime_type)
        body = content.content or ""
    except Exception as exc:  # noqa: BLE001
        log.warning("summary: read claims %s failed: %s", f.id, exc)
        return _broken("The claims recorded for this run could not be read from Drive.")
    try:
        data = yaml.safe_load(body)
    except yaml.YAMLError as exc:
        log.warning("summary: parse claims %s failed: %s", f.id, exc)
        return _broken("The claims file for this run is not valid YAML.")

    if not isinstance(data, dict):
        return _broken("The claims file for this run is not a claim set.")
    raw_claims = data.get("claims")
    if not isinstance(raw_claims, list):
        return _broken("The claims file for this run records no list of claims.")

    # Phase order, for "ordered by `checkable_at`". Empty when the plugin
    # registry is unreadable, and the claims then keep FILE order — which
    # is authoring order, so it degrades to something sensible rather than
    # to alphabetical.
    ordinals = {name: ordinal for name, (_label, ordinal) in _plugin_phase_index().items()}

    rows: list[dict] = []
    malformed = 0
    for raw in raw_claims:
        if not isinstance(raw, dict):
            malformed += 1
            continue
        claim_id = str(raw.get("id") or "").strip()
        text = str(raw.get("claim") or "").strip()
        if not claim_id or not text:
            malformed += 1
            continue
        origin = raw.get("origin") if isinstance(raw.get("origin"), dict) else {}
        checkable_at = str(raw.get("checkable_at") or "").strip()
        rows.append({
            "id": claim_id,
            "claim": text,
            # `None` means "no verdict yet" and renders as still open.
            # Never defaulted to MET, and never dropped.
            "verdict": (
                raw.get("verdict") if raw.get("verdict") in _CLAIM_VERDICTS else None
            ),
            "evidence_kind": (
                raw.get("evidence_kind")
                if raw.get("evidence_kind") in ("probed", "judged") else None
            ),
            "authored_by": (
                "counterpart" if raw.get("authored_by") == "counterpart" else "ace"
            ),
            "person": str(origin.get("person") or "").strip() or "Unattributed",
            "quote": str(origin.get("quote") or "").strip() or None,
            "artifact": str(raw.get("artifact") or "").strip() or None,
            "checkable_at": checkable_at or None,
            "says": str(raw.get("says") or "").strip() or None,
            # Members only. See the docstring.
            "evidence": (
                (str(raw.get("evidence") or "").strip() or None)
                if viewer_is_member else None
            ),
            "would_settle_it": str(raw.get("would_settle_it") or "").strip() or None,
            "_order": ordinals.get(checkable_at, 10_000),
        })

    if not rows:
        if malformed:
            return _broken(
                f"{malformed} claim(s) in this run's claims file are malformed "
                "and could not be read."
            )
        return None

    counts = {
        "met": sum(1 for r in rows if r["verdict"] == "MET"),
        "unmet": sum(1 for r in rows if r["verdict"] == "UNMET"),
        "not_reached": sum(1 for r in rows if r["verdict"] == "NOT REACHED"),
        "indeterminate": sum(1 for r in rows if r["verdict"] == "INDETERMINATE"),
        "unanswered": sum(1 for r in rows if r["verdict"] is None),
    }
    total = len(rows)

    # Grouped by person, ordered by `checkable_at` within the group.
    # `sorted` is stable, so claims sharing a phase keep file order.
    people: list[dict] = []
    for row in sorted(rows, key=lambda r: r["_order"]):
        group = next((g for g in people if g["person"] == row["person"]), None)
        if group is None:
            group = {"person": row["person"], "claims": []}
            people.append(group)
        group["claims"].append({k: v for k, v in row.items() if k != "_order"})

    return {
        "summary": _claim_summary_line(counts, total),
        "total": total,
        # TRUE only when EVERY claim is MET. A run where every ANSWERED
        # claim passed but a checkpoint never ran has NOT met its claims;
        # reporting otherwise recreates the silence being removed.
        "all_met": total > 0 and counts["met"] == total,
        "counts": counts,
        # A file that read but carried unusable rows: the good ones still
        # render AND the page says some could not be read. Dropping them
        # quietly would corrupt the denominator, which is the one thing
        # this section has to get right.
        "error": (
            f"{malformed} further claim(s) in this run's claims file are malformed "
            "and could not be read."
        ) if malformed else None,
        "people": people,
    }


def _read_feedback(
    drive: DriveClient, opp_folder_id: str, *, viewer_is_member: bool,
    access: LinkAccessReader | None = None,
) -> list[dict]:
    """Rendered reviewer feedback ledgers — "where did my comment go?".

    Derived views produced by skills/feedback-ledger, one stable doc per
    review event at ``ACE/<opp>/feedback/<slug>-ledger``. Surfacing them
    here is what makes the summary a review surface rather than a link
    list: a returning reviewer opens the run and sees the diff against
    their own last set of comments.

    A PRIVATE review's ledger is omitted for a non-member, and that is
    the one exception to this module's "every link is served to
    everyone, each declaring its own ``access``" rule. That rule is
    about USABILITY — hiding a link an external reviewer can't use is as
    bad as letting it 404. Confidentiality is a different rule, and it
    removes the row: ``read_reactions`` in the very same payload refuses
    to republish a privately-captured review, and linking the ledger
    RENDERED FROM that review would walk straight around it. The title
    alone ("2026-07-27 · Sophie Feintuch") discloses that a named person
    reviewed this run; the doc behind it is one anyone-with-link grant
    away from disclosing everything they said.

    So: default-deny by the same predicate the reactions reader uses
    (``reactions.is_public_record`` — the ``public-summary`` channel, or
    the legacy ``-public-`` slug marker). A ledger whose record is
    missing or unparseable counts as private. Members see everything,
    with the private ones tagged ``admin`` so the page can say why.
    """
    folder = _find_folder(drive, opp_folder_id, "feedback")
    if folder is None:
        return []

    ledgers: list[dict] = []
    try:
        files = drive.list_files(folder.id)
    except Exception as exc:  # noqa: BLE001
        log.warning("summary: list feedback %s failed: %s", folder.id, exc)
        return []

    from apps.opps.reactions import public_record_slugs

    public_slugs = public_record_slugs(drive, opp_folder_id)

    # One batch for the whole section — see LinkAccessReader.prime.
    if access is not None:
        access.prime(
            f.id for f in files if f.name.endswith("-ledger") and f.web_view_link
        )

    for f in files:
        if not f.name.endswith("-ledger") or not f.web_view_link:
            continue
        # "20260727-sophie-feintuch-ledger" -> "2026-07-27 · Sophie Feintuch"
        stem = f.name[: -len("-ledger")]
        is_public = stem in public_slugs
        if not is_public and not viewer_is_member:
            continue
        date, _, who = stem.partition("-")
        title = who.replace("-", " ").title() or stem
        if len(date) == 8 and date.isdigit():
            title = f"{date[:4]}-{date[4:6]}-{date[6:]} · {title}"
        # `is_public` is a CONFIDENTIALITY decision about the review (may
        # this ledger be shown to a non-member at all?) and still gates
        # visibility above. It is not a claim about the Drive file's ACL,
        # and conflating the two is how a privately-shared ledger came to
        # be tagged `public`. The tag is measured; the gate is not.
        ledgers.append({
            "title": title,
            "url": f.web_view_link,
            "access": (
                access.tag(file_id=f.id) if access is not None else ACCESS_UNKNOWN
            ),
        })

    return sorted(ledgers, key=lambda d: d["title"], reverse=True)


# ─── Decisions log ─────────────────────────────────────────────────

# Ordinal-prefixed phase tags (``1-design``, ``8-solicitation-management``)
# are what the decisions log writes. Only the ordinal is load-bearing for
# ordering; the tail is humanised for the label.
#
# The tag is an ABBREVIATION of the phase, though — ``3-commcare`` for the
# ``commcare-setup`` phase — so humanising it yields "Commcare" where the
# Workbench says "CommCare setup". The public review surface is organised
# by phase precisely so a reader can see which part of the flow produced a
# call; two names for the same phase across the two surfaces defeats that.
# So prefer the plugin's own phase registry (the same source the Workbench
# renders from, keyed on the decision's real ``phase`` name) and fall back
# to humanising the tag only when the plugin can't be read.
def _decision_phase_label(phase_raw: str) -> str:
    head, _, tail = str(phase_raw or "").partition("-")
    if head.isdigit() and tail:
        return _humanize(tail)
    return _humanize(str(phase_raw or "")) or "Other"


def _decision_phase_ordinal(phase_raw: str) -> int:
    head, _, _tail = str(phase_raw or "").partition("-")
    return int(head) if head.isdigit() else 99


def _plugin_phase_index() -> dict[str, tuple[str, int]]:
    """{phase_name: (display_name, ordinal)} from the ACE plugin registry.

    Empty dict when the plugin isn't readable (local dev, a broken
    checkout) — callers degrade to the tag-derived label, which is what
    this surface shipped with.
    """
    try:
        from apps.opps.api import _phase_display_index

        return _phase_display_index()
    except Exception as exc:  # noqa: BLE001
        log.warning("summary: phase registry unavailable (%s) — using tag labels", exc)
        return {}


def _words(text: str) -> set[str]:
    return {w for w in re.split(r"[^a-z0-9]+", str(text or "").lower()) if w}


def _registry_label_agrees(phase_raw: str, display: str) -> bool:
    """Does the registry's display name describe the phase the ROW claims?

    ``serialize_decision`` projects a row's tag onto a phase NAME by
    ORDINAL (``4-connect`` → whatever the plugin currently calls phase 4).
    That is fine while the pipeline is stable and actively wrong after a
    re-order: the ACE plugin's phase 4 used to be OCS setup, so a run that
    recorded ``4-connect`` would be published under "OCS Setup" — a
    confident, wrong statement about where a decision came from, on a page
    an outside partner reads.

    So the registry is used to make the label FULLER, never to overrule
    the run: take the display name only when every word of the row's own
    tag appears in it (``connect`` ⊂ "Connect Setup" ✓,
    ``connect`` ⊄ "OCS Setup" ✗). Otherwise keep what the run wrote.
    """
    _, _, tail = str(phase_raw or "").partition("-")
    tag_words = _words(tail or phase_raw)
    return bool(tag_words) and tag_words <= _words(display)


def _read_decisions(drive: DriveClient, run_folder_id: str) -> dict | None:
    """The run's decisions log — "what we decided, and why".

    A 24-page PDD is a poor instrument for eliciting decisions: people
    skim prose. Every load-bearing default a phase applied is already
    recorded as a typed row in ``runs/<run-id>/decisions.yaml`` — the
    question, the value the AI picked, the alternatives it weighed, its
    reasoning, and (v4) an ``evidence_basis`` saying whether the value was
    *stated* in a source, *inferred* beyond one, or a resolution of
    *conflicting* signals. That is the artifact a partner can react to.

    Rows are projected through the SAME ``serialize_decision`` the
    Workbench uses, so the public review surface and the Workbench render
    one shape and can't drift apart. Grouping/filtering is left to the
    page; this returns the rows plus the counts that let the page lead
    with the interesting ones (``conflicting`` and ``overridden``).

    The doc itself is an internal working artifact and is not shared, so
    no link is emitted — the content is the payload.
    """
    from apps.opps.parsers import (
        RECOMMENDED_CONFIRMATION,
        REQUIRED_BEFORE,
        Decision,
        decision_extras,
        normalize_decision_status,
    )
    from apps.opps.serializers import serialize_decision

    f = _find_in_folder(drive, run_folder_id, "decisions.yaml")
    if f is None:
        return None
    log_data = _read_yaml(drive, f.id, f.mime_type)
    raw_rows = log_data.get("decisions")
    if not isinstance(raw_rows, list) or not raw_rows:
        return None

    rows: list[dict] = []
    live = 0
    counts = {
        "stated": 0, "inferred": 0, "conflicting": 0, "overridden": 0,
        # Asks (ACE 2026-10-04): rows a reviewer is asked to confirm or
        # answer, and rows parked as "not needed for this pilot".
        "to_confirm": 0, "to_answer": 0, "deferred": 0,
    }
    phase_index = _plugin_phase_index()
    for raw in raw_rows:
        if not isinstance(raw, dict):
            log.warning("summary: decision entry is not a mapping — skipped")
            continue
        superseded_by = str(raw.get("superseded_by") or "").strip()
        row_id = str(raw.get("id") or "").strip()
        question = str(raw.get("question") or "").strip()
        if not row_id or not question:
            log.warning("summary: decision row missing id/question (keys=%s) — skipped",
                        sorted(raw))
            continue
        status = normalize_decision_status(raw.get("status"))
        basis = raw.get("evidence_basis")
        basis = basis if basis in ("stated", "inferred", "conflicting") else "stated"
        decision = Decision(
            id=row_id,
            phase=str(raw.get("phase") or ""),
            skill=str(raw.get("skill") or ""),
            question=question,
            ai_default=str(raw.get("ai-default") or raw.get("ai_default") or ""),
            override=str(raw.get("override") or ""),
            options_considered=[
                str(o) for o in (raw.get("options") or raw.get("options_considered") or [])
            ],
            source=str(raw.get("source") or ""),
            status=status,
            notes=str(raw.get("reasoning") or raw.get("notes") or ""),
            override_reasoning=str(raw.get("override_reasoning") or ""),
            evidence_basis=basis,
            conflict_signals=[str(c) for c in (raw.get("conflict_signals") or [])],
            superseded_by=superseded_by,
            **decision_extras(raw),
        )
        serialized = serialize_decision(decision)
        # ``decision.phase`` is the phase TAG the log writes (``3-commcare``);
        # the phase NAME it projects onto (``commcare-setup``) rides on the
        # serialized ``phase`` field, which is what the registry is keyed on.
        # The tag is an abbreviation, so humanising it gives "Commcare"
        # where the Workbench says "CommCare Setup" — two names for one
        # phase across the two surfaces, which defeats the point of
        # organising this page by phase at all.
        display, _ordinal = phase_index.get(str(serialized.get("phase") or ""), ("", 0))
        serialized["phase_label"] = (
            display
            if _registry_label_agrees(decision.phase, display)
            else _decision_phase_label(decision.phase)
        )
        # Ordinal always comes from the tag the RUN wrote — see
        # ``_registry_label_agrees``.
        serialized["phase_ordinal"] = _decision_phase_ordinal(decision.phase)
        # The plain stage name an outside reader sees instead of
        # "Phase 3 · CommCare Setup" — the same names `stage` uses. Read
        # from the run's own TAG, not the ordinal-projected ``phase``,
        # for the reason ``_registry_label_agrees`` gives.
        serialized["stage_label"] = _stage_name_for_tag(decision.phase)
        rows.append(serialized)
        if superseded_by:
            # HISTORY, not a choice this run stands behind: a row a later row
            # corrected (ace#1421), or one a fork retired because this run
            # re-runs its phase (ace#2582). It is served (with
            # ``superseded_by`` set) so the page can show it behind a
            # "show history" toggle, hidden by default — but it never counts
            # toward ``total`` / ``counts``, which describe the live choices.
            continue
        live += 1
        counts[basis] += 1
        if status in ("overridden", "human-decided"):
            counts["overridden"] += 1
        if status == "deferred":
            counts["deferred"] += 1
        elif serialized.get("review_ask") == RECOMMENDED_CONFIRMATION:
            counts["to_confirm"] += 1
        elif serialized.get("review_ask") == REQUIRED_BEFORE:
            counts["to_answer"] += 1

    if not live:
        return None
    return {"total": live, "counts": counts, "rows": rows}


# ─── Deep QA (/ace:qa-deep) ─────────────────────────────────────────
#
# The one section on this page that is NOT reachable from `run_state`.
#
# `/ace:qa-deep` deliberately writes nothing into `run_state.yaml` —
# `commands/qa-deep.md` says so in as many words, so that a later
# `/ace:run` resume is unaffected by a deep gate having been taken. That
# is a good decision and this reader does not ask for it to change: it
# means there is no machine-readable pointer to the deep verdicts, so the
# two files are read from Drive BY PATH, the way `_read_decisions` reads
# `decisions.yaml`.
#
# Which gives the section's visibility rule for free, with no flag to
# maintain and nothing to keep in sync: the files exist iff the deep gate
# was actually run, so
#
#   * neither present  → `deep_qa` is None and the section is ABSENT;
#   * one present      → that stage is rendered and the other says, in
#                        the payload, that it has not run (`ran: False`);
#   * both present     → both rendered.
#
# **Do not key this on `run_state.yaml`.** A top-level `qa_deep:` block
# exists on `spark-facilitator/20260828-0703` because a human wrote it
# there by hand while taking the gate. No skill produces it, nothing
# validates it, and it is not in the Phase Write-Back Contract — keying
# on it would work for exactly one run in the world.

#: Where each stage's verdict lives inside the run folder, and what the
#: page calls it. The filenames are the ones `/ace:qa-deep` documents as
#: its outputs (`commands/qa-deep.md` § Stage A / § Stage B).
_DEEP_QA_STAGES = (
    {
        "stage": "assistant",
        "label": "Support assistant",
        "folder": "5-ocs",
        "filename": "ocs-chatbot-eval_verdict-deep.yaml",
    },
    {
        "stage": "apps",
        "label": "CommCare apps",
        "folder": "6-qa-and-training",
        "filename": "app-ux-eval_verdict-deep.yaml",
    },
)

#: `gate.disposition` values `lib/verdict-schema.ts` allows. An
#: unrecognised one is passed through verbatim rather than dropped — the
#: same rule `_ddd_honesty` applies to `terminal_status`, and for the same
#: reason: a disposition we have not heard of must show up as itself, not
#: as silence.
_DEEP_QA_DISPOSITIONS = frozenset({"approve", "reject", "iterate"})

_DEEP_QA_ITEM_VERDICTS = ("fail", "warn", "pass")


def _num(value: object) -> float | None:
    """A YAML scalar as a float, or ``None``. ``bool`` is not a number."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _clean(value: object) -> str | None:
    """Collapse a YAML string to one line, or ``None`` when it is empty."""
    if not isinstance(value, str) or not value.strip():
        return None
    return " ".join(value.split())


def _timestamp(value: object) -> str | None:
    """A verdict's ``ran_at``, as a string, however YAML gave it to us.

    Not cosmetic. An UNQUOTED ISO timestamp is a native YAML type, so
    ``yaml.safe_load`` returns ``datetime``/``date`` — and the two real
    verdicts disagree: ``ocs-chatbot-eval`` writes
    ``ran_at: 2026-09-01T15:05:00Z`` bare while ``app-ux-eval`` quotes
    its own. Treating this as a string would have shipped a null
    timestamp on the OCS stage and only the OCS stage, which is exactly
    the "renders as absence, throws nothing" failure this page keeps
    being bitten by. When the timestamp is the ONLY staleness signal a
    reader gets, dropping it silently is the whole bug.
    """
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return _clean(value)


def _deep_qa_freshness(stage: str, verdict: dict, state: dict) -> list[dict]:
    """What the deep verdict was measured against, versus what is deployed.

    This is the whole reason the section exists. Phase 9 `llo-launch`
    refuses activation when the deep verdicts are missing **or stale**,
    because a verdict produced before the current released build or the
    current published chatbot version is not evidence about what is
    deployed now — it is evidence about something that no longer exists.

    Both sides are read as EXACTLY-named fields, never inferred:

    * assistant — the verdict's own ``published_version`` against
      ``products.ocs_chatbot.published_version``;
    * apps — the verdict's ``artifact_refs.<app>_build_id`` against
      ``products.apps.<app>.released_build_id``.

    A comparison is emitted only when BOTH sides are present. When a
    verdict carries no identifier this returns ``[]``, the stage's
    ``is_stale`` is ``None``, and the page shows the timestamp and leaves
    the judgement to the reader. That is deliberate: a staleness check
    that can be wrong is worse than none, because "fresh" is exactly the
    claim a reader would act on.
    """
    out: list[dict] = []

    def compare(basis: str, observed: object, current: object) -> None:
        if observed in (None, "") or current in (None, ""):
            return
        out.append({
            "basis": basis,
            "verdict_value": str(observed),
            "current_value": str(current),
            "is_current": str(observed) == str(current),
        })

    if stage == "assistant":
        chatbot = _phase_products(state, "ocs-setup", "ocs_chatbot")
        compare(
            "published chatbot version",
            verdict.get("published_version"),
            chatbot.get("published_version"),
        )
        return out

    if stage == "apps":
        refs = verdict.get("artifact_refs")
        refs = refs if isinstance(refs, dict) else {}
        apps = _phase_products(state, "commcare-setup", "apps")
        for kind in ("deliver", "learn"):
            app = apps.get(kind)
            compare(
                f"{kind} build",
                refs.get(f"{kind}_build_id"),
                (app or {}).get("released_build_id") if isinstance(app, dict) else None,
            )
        return out

    return out


def _deep_qa_stage(spec: dict, verdict: dict | None, state: dict) -> dict:
    """One stage, in the SAME shape whether or not it ran.

    A stage that has not run keeps every key and nulls the values rather
    than being dropped, so the page can say "the app stage has not been
    deep-QA'd" instead of leaving a reader to infer it from a section
    that is one row shorter than they expected. It is the same reasoning
    that keeps an `unavailable` walkthrough on the page.

    **The gate leads, and the score is context.** On
    ``spark-facilitator/20260828-0703`` Stage A scored 8.03 against a 7.0
    threshold and its gate is ``iterate``, because ``--deep`` requires
    zero Fail entries and two prompts fabricated safety-adjacent
    operational procedure — an invented cash-handover pathway and an
    invented PersonalID recovery chain. A page that printed "8.03" beside
    a tick would tell a reader this opportunity is ready to launch. It is
    not. So the payload carries `gate`, `verdict` and the Fail count as
    first-class fields alongside the score, and never derives a
    pass/fail appearance from the number.
    """
    stage = {
        "stage": spec["stage"],
        "label": spec["label"],
        "ran": verdict is not None,
        "ran_at": None,
        "gate": None,
        "verdict": None,
        "score": None,
        "threshold": None,
        "counts": {"total": 0, "pass": 0, "warn": 0, "fail": 0},
        "dimensions": [],
        "findings": [],
        "items": [],
        "freshness": [],
        "is_stale": None,
    }
    if verdict is None:
        return stage

    stage["ran_at"] = _timestamp(verdict.get("ran_at"))
    stage["verdict"] = _clean(verdict.get("verdict"))
    stage["score"] = _num(verdict.get("overall_score"))

    gate = verdict.get("gate")
    if isinstance(gate, dict):
        disposition = _clean(gate.get("disposition"))
        if disposition and disposition not in _DEEP_QA_DISPOSITIONS:
            log.warning(
                "summary: deep-qa stage %s declares gate.disposition=%r, not one "
                "of %s — surfaced verbatim",
                spec["stage"], disposition, sorted(_DEEP_QA_DISPOSITIONS),
            )
        stage["gate"] = disposition
        stage["threshold"] = _num(gate.get("threshold"))

    dimensions = verdict.get("dimensions")
    if isinstance(dimensions, dict):
        for name, entry in dimensions.items():
            if not isinstance(entry, dict):
                continue
            stage["dimensions"].append({
                "name": str(name),
                "score": _num(entry.get("score")),
                "weight": _num(entry.get("weight")),
            })

    # Counts over EVERY graded item; rows only for the ones that did not
    # pass. A deep OCS suite is ~68 prompts and a prompt-by-prompt log is
    # not what an external reader is here for — but "58 of 68 passed" with
    # the ten that did not, named, is. The count is what stops the short
    # list reading as the whole story.
    per_item = verdict.get("per_item")
    rows: dict[str, list[dict]] = {v: [] for v in _DEEP_QA_ITEM_VERDICTS}
    if isinstance(per_item, list):
        for raw in per_item:
            if not isinstance(raw, dict):
                continue
            item_verdict = _clean(raw.get("verdict")) or ""
            item_verdict = item_verdict.lower()
            stage["counts"]["total"] += 1
            if item_verdict in rows:
                rows[item_verdict].append({
                    "ref": str(raw.get("ref") or raw.get("journey") or ""),
                    "verdict": item_verdict,
                    "score": _num(raw.get("score")),
                    "note": _clean(raw.get("note")),
                })
                stage["counts"][item_verdict] += 1
            else:
                log.warning(
                    "summary: deep-qa stage %s item %r declares verdict=%r — "
                    "counted in total, not attributed",
                    spec["stage"], raw.get("ref"), raw.get("verdict"),
                )
    stage["items"] = rows["fail"] + rows["warn"]

    # `auto_surfaced` is carried WHOLE, severity and all. Filtering it
    # here is how a page ends up rendering a clean-looking absence: the
    # BLOCKERs are the two fabrications above, and a severity this reader
    # has not heard of is a reason to show it, not to drop it.
    surfaced = verdict.get("auto_surfaced")
    if isinstance(surfaced, list):
        for raw in surfaced:
            if not isinstance(raw, dict):
                continue
            message = _clean(raw.get("message"))
            if not message:
                continue
            stage["findings"].append({
                "severity": _clean(raw.get("severity")),
                "message": message,
            })

    stage["freshness"] = _deep_qa_freshness(spec["stage"], verdict, state)
    if stage["freshness"]:
        stage["is_stale"] = any(not c["is_current"] for c in stage["freshness"])

    return stage


def _read_deep_qa(drive: DriveClient, run_folder_id: str, state: dict) -> dict | None:
    """The `/ace:qa-deep` verdicts, or ``None`` when the gate never ran.

    See the block comment above for why this reads Drive by path instead
    of taking a pointer out of ``state`` like every other reader here.

    One listing of the run folder is reused for both stages rather than
    resolving each subfolder from scratch — this endpoint has been
    through two rounds of Drive-call batching (ace-web#741, #742) and a
    section that quietly adds a per-stage folder walk would undo part of
    it.
    """
    try:
        entries = list(drive.list_files(run_folder_id))
    except Exception as exc:  # noqa: BLE001
        log.warning("summary: deep-qa list %s failed: %s", run_folder_id, exc)
        return None
    folders = {
        f.name: f for f in entries
        if f.mime_type == "application/vnd.google-apps.folder"
    }

    stages: list[dict] = []
    any_ran = False
    for spec in _DEEP_QA_STAGES:
        folder = folders.get(spec["folder"])
        verdict: dict | None = None
        if folder is not None:
            f = _find_in_folder(drive, folder.id, spec["filename"])
            if f is not None:
                parsed = _read_yaml(drive, f.id, f.mime_type)
                # An unreadable or empty verdict file is NOT "the stage
                # did not run" — the file being there is the evidence it
                # did. Fall through to the not-ran shape only when the
                # file is genuinely absent; a present-but-unparseable one
                # is logged and rendered as not-ran, which is the least
                # bad of two wrong answers and is loud in the log.
                if parsed:
                    verdict = parsed
                else:
                    log.warning(
                        "summary: deep-qa %s/%s is present but unreadable",
                        spec["folder"], spec["filename"],
                    )
        any_ran = any_ran or verdict is not None
        stages.append(_deep_qa_stage(spec, verdict, state))

    if not any_ran:
        return None
    return {"stages": stages}


def _read_decision_edits(drive: DriveClient, opp_folder_id: str) -> dict:
    """Saved decision overrides, keyed by row id, emails stripped.

    Degrades to ``{}`` on any Drive failure: an unreadable overrides file
    must not take the whole summary down, and "nobody has changed
    anything" is the correct rendering of "we could not read the file"
    only in the sense that the page still loads — the rows themselves
    still show what the run decided.
    """
    from apps.opps.decision_overrides import fetch_saved_overrides

    try:
        return fetch_saved_overrides(
            drive, opp_folder_id=opp_folder_id, include_email=False,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("summary: read decision overrides failed: %s", exc)
        return {}


#: A person ruled on the row itself (ACE ``lib/open-asks.ts`` ``isAnswered``).
_ANSWERED_STATUSES = frozenset({"overridden", "human-decided"})


def _ask_kind(row: dict) -> str | None:
    """``confirm`` / ``answer`` / ``deferred`` for a live row that asks
    something, else ``None``. Mirrors ACE's ``isOpenAsk``: an unanswered
    ``review_ask`` (``recommended-confirmation`` or ``required-before``), or
    ``status: deferred``. A deferred row never asks, whatever else it says."""
    from apps.opps.parsers import RECOMMENDED_CONFIRMATION, REQUIRED_BEFORE

    if str(row.get("superseded_by") or "").strip():
        return None
    if row.get("status") == "deferred":
        return "deferred"
    ask = str(row.get("review_ask") or "")
    if ask == RECOMMENDED_CONFIRMATION:
        return "confirm"
    if ask == REQUIRED_BEFORE:
        return "answer"
    return None


def _is_answered(row: dict, edit: dict | None) -> bool:
    """A person ruled: the row is ``overridden`` / ``human-decided``, or a
    saved ruling in ``inputs/decision-overrides.yaml`` binds to it — a
    confirmation, or a change. A revert to the AI default with nothing to
    say is not an answer (the page's ``isConfirmationHandled``)."""
    if row.get("status") in _ANSWERED_STATUSES:
        return True
    if not isinstance(edit, dict):
        return False
    return bool(edit.get("confirmed")) or not edit.get("is_revert")


def _open_asks(decisions: dict | None, edits: dict | None) -> dict | None:
    """What this run still asks a reviewer — a FILTER of its decision rows.

    There is no second store. An "open question" is a decision whose
    default someone outside ACE must confirm (``review_ask:
    recommended-confirmation``) or answer before a lifecycle gate
    (``review_ask: required-before`` + ``needed_by``), or one this pilot
    does not need answered (``status: deferred``) — ACE
    ``docs/decisions-contract.md`` § Open asks. The rows themselves are
    rendered on the Decisions tab ("Confirm before launch", "Answer before
    …", "Not needed for this pilot"); this is the run-level tally of the
    same predicate, so the Overview headline and any API reader (ACE's
    run-surface audit) agree with the tab.

    ``null`` when the run has no decisions log. Superseded rows are
    history and never ask anything.
    """
    if not decisions:
        return None
    edits = edits or {}
    confirm = {"total": 0, "outstanding": 0}
    answer = {"total": 0, "outstanding": 0}
    by_needed_by: dict[str, dict[str, int]] = {}
    deferred = 0
    outstanding_ids: list[str] = []
    for row in decisions.get("rows") or []:
        kind = _ask_kind(row)
        if kind is None:
            continue
        if kind == "deferred":
            deferred += 1
            continue
        answered = _is_answered(row, edits.get(row.get("id")))
        bucket = confirm if kind == "confirm" else answer
        bucket["total"] += 1
        if kind == "answer":
            stage = by_needed_by.setdefault(
                str(row.get("needed_by") or ""), {"total": 0, "outstanding": 0},
            )
            stage["total"] += 1
        if not answered:
            bucket["outstanding"] += 1
            if kind == "answer":
                stage["outstanding"] += 1
            outstanding_ids.append(str(row.get("id")))
    return {
        "confirm": confirm,
        "answer": {**answer, "by_needed_by": by_needed_by},
        "deferred": deferred,
        "total": confirm["total"] + answer["total"],
        "outstanding": confirm["outstanding"] + answer["outstanding"],
        "outstanding_ids": outstanding_ids,
    }


# ─── Lifecycle stage ───────────────────────────────────────────────

# Canonical phase order, with the short label the page shows and the
# payload sections each phase is responsible for producing.
_PHASE_ORDER: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("idea-to-design", "design", ("design",)),
    ("design", "design", ("design",)),                       # legacy key
    ("scenarios-and-acceptance", "scenarios", ()),
    ("commcare-setup", "app build", ("apps",)),
    ("connect-setup", "Connect setup", ("connect",)),
    ("ocs-setup", "assistant setup", ("assistant",)),
    ("qa-and-training", "QA and training", ("training",)),
    (_SYNTHETIC_PHASE, "demo", ("walkthroughs", "dashboards")),
    # `selected_llo` sits with execution, not solicitation: an awarded
    # partner is what STARTS execution, so "no LLO yet" is expected for
    # as long as the run hasn't reached Phase 9.
    ("solicitation-management", "solicitation", ("solicitation",)),
    ("execution-management", "execution", ("selected_llo", "launch")),
    ("closeout", "closeout", ("cycle_grade", "opp_eval", "learnings")),
)


def _stage_name_for_tag(phase_raw: str) -> str | None:
    """The capitalised stage label ("App build") for a decision row's phase
    TAG (``3-commcare``): the first phase whose name contains every word of
    the tag. ``None`` when none does — the page keeps ``phase_label``."""
    _, _, tail = str(phase_raw or "").partition("-")
    tag_words = _words(tail or phase_raw)
    if not tag_words:
        return None
    for name, label, _sections in _PHASE_ORDER:
        if tag_words <= _words(name):
            return label[:1].upper() + label[1:]
    return None


# A phase in one of these states has not run yet — the sections it owns
# are "not started", not "missing".
_NOT_STARTED_STATUSES = {"", "pending", "not_started", "not-started", "queued", "todo"}

#: A phase the run deliberately did not do. NOT "not started" (nothing is
#: coming) and NOT "started" (nothing was made): spark-facilitator/
#: 20261001-2208 halted by design at the Phase 8→9 boundary and wrote
#: `execution-management` and `closeout` as `status: skipped`, which the
#: old two-way split counted as STARTED — so `stage.label` read
#: "closeout" and LLO / Live / Score / Learnings rendered "Not created".
_SKIPPED_STATUSES = {"skipped", "skip", "not-applicable", "n/a"}

#: The phase block keys that may carry the run's own reason for a skip,
#: in preference order. The run's words beat anything derived here.
_SKIP_REASON_KEYS = ("reason", "skip_reason", "skipped_reason", "note", "status_note")

#: Phases whose sections already carry a dedicated verdict qualifier, so a
#: second, generic caveat would only repeat it: Phase 3 has `build`.
_CAVEAT_COVERED_ELSEWHERE = {"commcare-setup"}


def _skip_reason(block: dict, last_ran: tuple[str, dict] | None) -> str:
    """One plain line for a skipped phase's sections.

    The phase's own ``reason`` / ``note`` wins. Otherwise it is derived
    from the last phase that DID run: a ``halt-…`` verdict there (ACE
    writes ``halt-at-phase-8-to-9-boundary``) means the run stopped on
    purpose, which is exactly what a reader needs to hear instead of
    "Not created".
    """
    for key in _SKIP_REASON_KEYS:
        value = block.get(key)
        if isinstance(value, str) and value.strip():
            return f"Not part of this run — {' '.join(value.split())}"
    if last_ran is not None:
        label, ran_block = last_ran
        verdict = str(ran_block.get("verdict") or "").strip().lower()
        if verdict.startswith("halt"):
            return (
                f"Not part of this run — it stopped after the {label} stage, by design"
            )
    return "Not part of this run — this stage was skipped"


def _verdict_caveat(status: str, verdict: str) -> str | None:
    """A plain one-line caveat for a phase that did not finish clean, or
    ``None`` when there is nothing to say.

    ACE's verdict vocabulary is open-ended (``proceed-with-warn``,
    ``passed-with-deferred-evals``, ``partial-…``), so this matches on
    the words that carry the meaning and falls back to a generic line
    that quotes the verdict verbatim — an unknown verdict must not
    become silence, and must not be guessed into something friendlier.

    Not caveated: clean verdicts, ``seeded`` (the phase was carried from
    an earlier run rather than rebuilt — provenance, not quality), and a
    ``halt-…`` verdict (the run stopping on purpose is what `stage`
    reports; it says nothing about the phase's own work).
    """
    v = verdict.strip().lower()
    if v.startswith("halt") or v == "seeded":
        v = ""
    if v in _CLEAN_PHASE_VERDICTS:
        if status in _INCOMPLETE_PHASE_STATUSES:
            return "Only partly finished — some of this stage's work did not complete."
        return None
    if "deferred" in v:
        return "Built; some quality checks were deferred."
    if "warn" in v:
        return "Finished with warnings that were accepted so the run could continue."
    if "partial" in v:
        return "Only partly finished — some of this stage's checks did not pass."
    if any(token in v for token in _FAILING_VERDICTS):
        return "Did not pass its own quality checks."
    return f"Finished without a clean pass (ACE recorded “{verdict.strip()}”)."


def _phase_state(block: dict) -> str:
    """``"skipped"``, ``"pending"`` or ``"ran"`` for one phase block —
    the three-way split `_read_stage` uses.

    A phase that wrote products has run, whatever its status says —
    older runs (and every test fixture) carry products with no status at
    all, and calling those "not started" would be worse than the bug
    this fixes.
    """
    status = str(block.get("status") or "").strip().lower()
    if status in _SKIPPED_STATUSES:
        return "skipped"
    if status not in _NOT_STARTED_STATUSES or bool(block.get("products")):
        return "ran"
    return "pending"


def _paused_text(last_ran: tuple[str, str, dict] | None) -> str:
    """The plain status for a run that stopped by design. Stopping after
    the solicitation is the common case and has a precise reason: no
    implementing organisation has been chosen yet."""
    if last_ran is None:
        return "Paused"
    name, label, _block = last_ran
    if name == "solicitation-management":
        return "Paused — waiting for an implementing organisation"
    return f"Paused after the {label} stage"


def _read_stage(state: dict) -> dict | None:
    """Where the run stopped, and which sections that makes premature.

    A run that halts at the Phase 8→9 boundary by design has no LLO, no
    launch, no score and no learnings — correctly. Rendering all four as
    "Not created" alongside genuinely-missing things made a healthy
    paused run read as an abandoned build. This block lets the page say
    "not started yet" for sections whose phase simply hasn't run, and
    "not part of this run" for those whose phase was skipped.

    ``pending_sections`` names payload keys, so the page can look each
    section up directly. ``label`` is the furthest phase that HAS run —
    a skipped phase does not count. ``skipped[]`` carries each skipped
    phase's sections with one plain reason. ``caveats[]`` carries each
    phase that ran without a clean verdict, so the page can qualify the
    sections it produced (a training pack from a ``proceed-with-warn``
    phase used to render exactly like a clean one).

    ``paused`` is the plain status for a run that STOPPED BY DESIGN, else
    ``None``: the furthest phase that ran carries a ``halt-…`` verdict and
    a later phase was skipped, or every phase after it was skipped and
    none is pending. Without it the hero said "In progress" over a page
    whose every later section says the run stopped on purpose.
    """
    phases = state.get("phases")
    if not isinstance(phases, dict) or not phases:
        return None

    current_label: str | None = None
    last_ran: tuple[str, str, dict] | None = None
    skipped_after_last_ran = False
    pending: list[str] = []
    skipped: list[dict] = []
    caveats: list[dict] = []
    for name, label, sections in _PHASE_ORDER:
        block = phases.get(name)
        if not isinstance(block, dict):
            continue
        status = str(block.get("status") or "").strip().lower()
        phase_state = _phase_state(block)
        if phase_state == "skipped":
            skipped.append({
                "phase": name,
                "sections": list(sections),
                "reason": _skip_reason(block, last_ran[1:] if last_ran else None),
            })
            skipped_after_last_ran = True
            continue
        if phase_state == "pending":
            pending.extend(sections)
            continue
        current_label = label
        last_ran = (name, label, block)
        skipped_after_last_ran = False
        verdict = str(block.get("verdict") or "")
        caveat = _verdict_caveat(status, verdict)
        if caveat and sections and name not in _CAVEAT_COVERED_ELSEWHERE:
            caveats.append({
                "phase": name,
                "sections": list(sections),
                "verdict": verdict.strip() or None,
                "text": caveat,
            })

    if current_label is None and not pending and not skipped:
        return None
    halted = last_ran is not None and str(
        last_ran[2].get("verdict") or ""
    ).strip().lower().startswith("halt")
    stopped = (halted and bool(skipped)) or (skipped_after_last_ran and not pending)
    return {
        "label": current_label,
        "pending_sections": sorted(set(pending)),
        "skipped": skipped,
        "caveats": caveats,
        "paused": _paused_text(last_ran) if stopped else None,
    }


# ─── Top-level entry point ─────────────────────────────────────────


def build_summary_payload(
    drive: DriveClient,
    *,
    workspace,
    opp_slug: str,
    run_id: str,
    viewer_is_member: bool = True,
    tenancy: dict | None = None,
    viewer_plain: bool | None = None,
) -> dict | None:
    """Build the public summary JSON payload for a per-run summary page.

    ``tenancy`` is the opp's tenancy (``apps.opps.tenancy``); it decides
    which links a released reviewer can open. ``None`` (unknown) classifies
    every non-Drive link as internal — the pre-tenancy behaviour.

    Returns ``None`` when the workspace's ACE root, the opp folder, or
    the requested run folder can't be located, so callers can map to a
    404 without leaking which segment was the miss.

    ``viewer_plain`` asks for the PARTNER view (defaults to ``not
    viewer_is_member``): the API passes ``True`` for a ``viewer``-role
    member, a partner reviewer who may still write but is shown what an
    outsider is shown. It is echoed as ``viewer.plain``, and the
    member-only payload details below (claim ``evidence``, a private
    review's ledger) follow the TEAM view, ``viewer_is_member and not
    viewer_plain`` — the page draws one version per reader, not a hybrid.

    ``viewer_is_member`` is echoed back as ``viewer.is_member``. It does
    NOT change which links are served — with ONE exception: a privately
    captured review's feedback ledger is omitted for a non-member, on
    confidentiality rather than usability grounds (see
    ``_read_feedback``). Every other link is always present and always
    declares its ``access`` (see the classification block above).
    Membership only decides whether the page draws the ``admin only``
    tag — a member already knows, and the tag would be noise. This
    replaces the earlier ``include_internal_links``, which HID the
    Workbench link from non-members; hiding a link an external reviewer
    can\'t use is the same failure as letting it 404 silently, just
    quieter. Both variants stay separately cached.
    """
    if viewer_plain is None:
        viewer_plain = not viewer_is_member
    team_view = bool(viewer_is_member) and not viewer_plain
    ace_root_id = getattr(workspace, "drive_root_folder_id", None)
    if not ace_root_id:
        return None

    opp_folder = _find_folder(drive, ace_root_id, opp_slug)
    if opp_folder is None:
        return None

    # opp.yaml — identity + Connect program reference.
    opp_yaml_file = _find_in_folder(drive, opp_folder.id, "opp.yaml")
    opp_yaml: dict = {}
    if opp_yaml_file is not None:
        opp_yaml = _read_yaml(drive, opp_yaml_file.id, opp_yaml_file.mime_type)

    runs_folder = _find_folder(drive, opp_folder.id, "runs")
    if runs_folder is None:
        return None
    run_folder = _find_folder(drive, runs_folder.id, run_id)
    if run_folder is None:
        return None

    # run_state.yaml — every per-run product. Its ABSENCE means the run
    # folder is not a run: `/ace:run` derives execution order from
    # `phases.*.status`, and every section below reads out of `state`.
    #
    # Returning a payload built from `{}` (as this did until ace-web#734)
    # served HTTP 200 with an empty body for a fork that stalled before
    # writing its state file — making "the fork failed" and "the run has
    # not started" indistinguishable from the API, and rendering a
    # summary page with nothing on it. `None` maps to 404 in the caller,
    # which is the honest answer.
    state_file = _find_in_folder(drive, run_folder.id, "run_state.yaml")
    if state_file is None:
        return None
    state: dict = _read_yaml(drive, state_file.id, state_file.mime_type) or {}

    # Measure every Drive link's real sharing state in ONE concurrent
    # batch before the section readers run (ace-web#740). Sequential
    # per-link reads would undo ace-web#738's batching on the very
    # endpoint it was written for.
    access = LinkAccessReader(drive, tenancy)
    access.prime(_state_drive_file_ids(state))

    workspace_slug = getattr(workspace, "slug", "")
    # Prefix the deployment mount (dimagi-internal/ace#1329). This link is
    # rendered as a plain `href`, so a ROOT-relative path resolves against the
    # origin rather than the mount: on labs the app is served under `/ace`, and
    # `/w/<ws>/opps/<opp>/runs/<run>` 404s while `/ace/w/...` is 200. Every
    # reader of the run summary who clicked "See the full build process" got a
    # 404, on every run.
    #
    # It went unnoticed because `scripts/check-summary-links.py` collected URLs
    # with `if v.startswith("http")`, so every RELATIVE value in the payload
    # was invisible to it (ace#1328 fixed the checker; this is the serializer
    # half).
    #
    # `.rstrip("/")` matters for the same reason FORCE_SCRIPT_NAME coerces ""
    # to None in settings: a trailing slash produces `//w/...`, which browsers
    # read as a protocol-relative URL to a host named "w".
    script_name = (settings.FORCE_SCRIPT_NAME or "").rstrip("/")
    workbench = (
        {
            "url": f"{script_name}/w/{workspace_slug}/opps/{opp_slug}/runs/{run_id}",
            # ace-web workspace membership — `/ace:release` invites a
            # reviewer of an own-tenancy opp into its workspace.
            "access": _tenant_tag(access.tenancy.workbench()),
        }
        if workspace_slug
        else None
    )
    decisions = _read_decisions(drive, run_folder.id)
    decision_edits = _read_decision_edits(drive, opp_folder.id)

    return {
        "opp": _read_opp(
            state, opp_yaml,
            workspace_slug=workspace_slug,
            opp_slug=opp_slug,
            run_id=run_id,
        ),
        "design": _read_design(state, access),
        "apps": _read_apps(state, access),
        # The producing phase's own verdict on those apps — null when
        # Phase 3 finished clean, so a clean run renders as before.
        "build": _read_build(state, "commcare-setup"),
        # The `/ace:qa-deep` gate's verdicts, read from Drive by path
        # because that command deliberately writes no pointer into
        # `run_state.yaml`. `None` — and so absent from the page
        # entirely — on every run that never took the deep gate.
        "deep_qa": _read_deep_qa(drive, run_folder.id, state),
        "connect": _read_connect(state, access, run_id=run_id),
        "training": _read_training(state, access),
        "assistant": _read_assistant(state),
        "walkthroughs": _read_walkthroughs(state),
        "dashboards": _read_dashboards(state, access),
        # What the dashboards and the demo are showing NUMBERS of. Read
        # from the run's own synthetic block; null when it generated none.
        "synthetic": _read_synthetic(state),
        "selected_llo": _read_selected_llo(state),
        "solicitation": _read_solicitation(state, access),
        "launch": _read_launch(state),
        "cycle_grade": _read_cycle_grade(state),
        "opp_eval": _read_opp_eval(state),
        "learnings": _read_learnings(state, access),
        # What a reviewer is still asked — a FILTER of this run's own
        # decision rows, with the saved rulings applied. Not a ledger.
        "open_asks": _open_asks(decisions, decision_edits),
        "stage": _read_stage(state),
        # What the run itself says is still unproven and needs a human
        # (ace-web#744). Null on a run that carried nothing, so a clean run
        # renders exactly as before — but a partial one can no longer read
        # as finished.
        "carried_residuals": _read_carried_residuals(state),
        # "What changed because you asked" — the run's frozen claim set
        # (ace#2420). `null` on every run that authored none, which is
        # most of them: the auditor must read absence as "this run has no
        # claims", not as a missing section.
        "claims": _read_claims(
            drive, run_folder.id, viewer_is_member=team_view,
        ),
        "feedback": _read_feedback(
            drive, opp_folder.id, viewer_is_member=team_view, access=access,
        ),
        "decisions": decisions,
        # Partner reactions collected on this page, keyed by decision id.
        # Written by apps.opps.reactions into the same feedback records
        # the ledgers above are rendered from, so a comment left here is
        # reachable from the ledger the next run publishes — not a write
        # into a store nothing reads.
        "reactions": read_reactions(drive, opp_folder.id, run_id=run_id),
        # Human-set answers, keyed by decision id — the SAME
        # `inputs/decision-overrides.yaml` the Workbench's authenticated
        # editor writes and the plugin binds on the next run, projected
        # without emails. The decisions rows above are what the RUN
        # recorded; this is what humans have changed since, with who and
        # when and every prior value, so the page can render an edit as a
        # reversible change rather than a fait accompli.
        "decision_edits": decision_edits,
        "workbench": workbench,
        "viewer": {"is_member": bool(viewer_is_member), "plain": bool(viewer_plain)},
    }
