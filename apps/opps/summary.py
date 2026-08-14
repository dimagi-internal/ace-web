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
    | ``connect-setup``         | ``products.connect.{program, opportunity, ace_test_user}`` |
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

Open Questions doc is the lone exception that still requires a Drive
fetch — the orchestrator doesn't yet write a typed pointer for it.
"""
from __future__ import annotations

import logging
from datetime import date

import yaml

from apps.opps.drive_client import DriveClient

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


def _read_apps(state: dict) -> list[dict]:
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
        })
    return out


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


def _read_connect(state: dict) -> dict | None:
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
    opp_url = opp.get("url") or connect.get("deep_link")
    if not (opp_id or opp_url):
        return None
    return {
        "opportunity": {
            "name": opp.get("name") or connect.get("opportunity_name") or "Connect opportunity",
            "url": opp_url,
            "start_date": opp.get("start_date") or connect.get("start_date"),
            "end_date": opp.get("end_date") or connect.get("end_date"),
        },
    }


def _read_training(state: dict) -> dict | None:
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
        }

    docs_block = training.get("docs") or {}
    docs: list[dict] = []
    # Preserve a stable display order matching agent-doc convention.
    for key in ("llo_guide", "flw_guide", "quick_reference", "faq", "onboarding_email"):
        doc = docs_block.get(key) or materials.get(key) or {}
        if doc.get("web_view_link") or doc.get("file_id"):
            docs.append({
                "title": doc.get("title") or key.replace("_", " ").title(),
                "url": doc.get("web_view_link"),
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
        "public_id": public_id,
        "embed_key": embed_key,
    }


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


_WALKTHROUGH_URL_KEYS = ("slideshow_url", "web_view_link", "url", "video_url")


def _read_walkthroughs(state: dict) -> list[dict]:
    """Persona walkthroughs, as one of three honest states per entry.

    ``availability`` is the point of this reader. A run can have

    - **nothing** — no entry at all; the section renders "Not created";
    - **withheld** — a walkthrough was produced but its concept eval
      failed, so we do not put it in front of a stakeholder. It still
      says so, with no link;
    - **available** — produced, passed, linked.

    Before this, a withheld walkthrough was indistinguishable from one
    that never existed: entries without a URL were dropped silently, so
    a rendered-but-failing walkthrough rendered as "Not created". A
    reviewer must never be told something does not exist when it does
    and we chose not to show it.

    An entry is withheld when its own ``eval_verdict`` is failing, or —
    for entries that carry no verdict of their own — when the phase's
    verdict is. Everything else needs a URL to be linkable; a URL-less,
    non-withheld entry is dropped, loudly.
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

        if withheld:
            out.append({
                "persona": persona,
                "url": None,
                "eval_score": None,
                "availability": "withheld",
                "withheld_reason": "Not shown — did not pass quality review",
            })
            continue
        if not url:
            log.warning(
                "summary: walkthrough %r has no url (keys=%s) — skipped",
                persona, sorted(w),
            )
            continue
        out.append({
            "persona": persona,
            "url": url,
            "eval_score": w.get("eval_score"),
            "availability": "available",
            "withheld_reason": None,
        })
    return out


def _read_dashboards(state: dict) -> list[dict]:
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
        out.append({"title": title, "url": url})
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


def _read_solicitation(state: dict) -> dict | None:
    sol = _phase_products(state, "solicitation-management", "solicitation")
    if not sol or not (sol.get("url") or sol.get("public_url")):
        return None
    return {
        "url": sol.get("url") or sol.get("public_url"),
        "deadline": sol.get("deadline"),
        "status": sol.get("status"),
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


def _read_learnings(state: dict) -> dict | None:
    learn = _phase_products(state, "closeout", "learnings")
    if not learn or not (learn.get("summary_file_id") or learn.get("summary_web_view_link")):
        return None
    return {
        "summary_url": _learnings_link(
            learn.get("summary_web_view_link"), learn.get("summary_file_id"),
        ),
        "new_pdd_url": _learnings_link(
            learn.get("new_pdd_web_view_link"), learn.get("new_pdd_file_id"),
        ),
        "iteration_warranted": bool(learn.get("iteration_warranted")),
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


def _read_open_questions(
    drive: DriveClient,
    opp_folder_id: str,
    run_folder_id: str | None = None,
) -> dict | None:
    """Open Questions doc — no typed handoff yet; Drive fetch required.

    Lives at the OPP level (``ACE/<opp>/open-questions.md``), not in the
    run folder: ACE keeps it "per-opportunity and durable across runs —
    refreshed each run, never restarted." Reading only the run folder made
    every real opp render "Open questions — Not created" while the doc sat
    one level up, which is the one section a reviewer most needs.

    The run folder is still checked as a fallback so any older run that
    did write a run-local copy keeps rendering.
    """
    for folder_id in (opp_folder_id, run_folder_id):
        if not folder_id:
            continue
        f = _find_in_folder(drive, folder_id, "open-questions.md")
        if f is not None and f.web_view_link:
            return {"url": f.web_view_link}
    return None


def _read_design(state: dict) -> dict | None:
    """Design docs a reviewer needs: the PDD, and the Work Order if present.

    The PDD is the artifact every downstream phase builds on and the one
    a reviewer actually comments on, yet it had no section on the summary
    at all — reviewers were sent a page that linked the training pack but
    not the design it came from.

    Accepts the legacy ``design`` phase key alongside ``idea-to-design``,
    matching ``_read_opp``.
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
            docs.append({"title": block.get("title") or fallback_title, "url": url})

    return {"docs": docs} if docs else None


def _read_feedback(drive: DriveClient, opp_folder_id: str) -> list[dict]:
    """Rendered reviewer feedback ledgers — "where did my comment go?".

    Derived views produced by skills/feedback-ledger, one stable doc per
    review event at ``ACE/<opp>/feedback/<slug>-ledger``. Surfacing them
    here is what makes the summary a review surface rather than a link
    list: a returning reviewer opens the run and sees the diff against
    their own last set of comments.
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

    for f in files:
        if not f.name.endswith("-ledger") or not f.web_view_link:
            continue
        # "20260727-sophie-feintuch-ledger" -> "2026-07-27 · Sophie Feintuch"
        stem = f.name[: -len("-ledger")]
        date, _, who = stem.partition("-")
        title = who.replace("-", " ").title() or stem
        if len(date) == 8 and date.isdigit():
            title = f"{date[:4]}-{date[4:6]}-{date[6:]} · {title}"
        ledgers.append({"title": title, "url": f.web_view_link})

    return sorted(ledgers, key=lambda d: d["title"], reverse=True)


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

# A phase in one of these states has not run yet — the sections it owns
# are "not started", not "missing".
_NOT_STARTED_STATUSES = {"", "pending", "not_started", "not-started", "queued", "todo"}


def _read_stage(state: dict) -> dict | None:
    """Where the run stopped, and which sections that makes premature.

    A run that halts at the Phase 8→9 boundary by design has no LLO, no
    launch, no score and no learnings — correctly. Rendering all four as
    "Not created" alongside genuinely-missing things made a healthy
    paused run read as an abandoned build. This block lets the page say
    "not started yet" for sections whose phase simply hasn't run.

    ``pending_sections`` names payload keys, so the page can look each
    section up directly. ``label`` is the furthest phase that HAS run.
    """
    phases = state.get("phases")
    if not isinstance(phases, dict) or not phases:
        return None

    current_label: str | None = None
    pending: list[str] = []
    for name, label, sections in _PHASE_ORDER:
        block = phases.get(name)
        if not isinstance(block, dict):
            continue
        status = str(block.get("status") or "").strip().lower()
        # A phase that wrote products has run, whatever its status says —
        # older runs (and every test fixture) carry products with no
        # status at all, and calling those "not started" would be worse
        # than the bug this fixes.
        started = status not in _NOT_STARTED_STATUSES or bool(block.get("products"))
        if started:
            current_label = label
        else:
            pending.extend(sections)

    if current_label is None and not pending:
        return None
    return {
        "label": current_label,
        "pending_sections": sorted(set(pending)),
    }


# ─── Top-level entry point ─────────────────────────────────────────


def build_summary_payload(
    drive: DriveClient,
    *,
    workspace,
    opp_slug: str,
    run_id: str,
    include_internal_links: bool = True,
) -> dict | None:
    """Build the public summary JSON payload for a per-run summary page.

    Returns ``None`` when the workspace's ACE root, the opp folder, or
    the requested run folder can't be located, so callers can map to a
    404 without leaking which segment was the miss.

    ``include_internal_links=False`` drops links that only work for a
    signed-in workspace member — currently the Workbench URL, which
    404s (not "sign in") for anyone else and can never work for an
    external reviewer, since ace-web only admits @dimagi.com accounts.
    The public endpoint passes the requesting user's auth state.
    """
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

    # run_state.yaml — every per-run product.
    state_file = _find_in_folder(drive, run_folder.id, "run_state.yaml")
    state: dict = {}
    if state_file is not None:
        state = _read_yaml(drive, state_file.id, state_file.mime_type)

    workspace_slug = getattr(workspace, "slug", "")
    workbench_url = (
        f"/w/{workspace_slug}/opps/{opp_slug}/runs/{run_id}"
        if workspace_slug and include_internal_links
        else None
    )

    return {
        "opp": _read_opp(
            state, opp_yaml,
            workspace_slug=workspace_slug,
            opp_slug=opp_slug,
            run_id=run_id,
        ),
        "design": _read_design(state),
        "apps": _read_apps(state),
        "connect": _read_connect(state),
        "training": _read_training(state),
        "assistant": _read_assistant(state),
        "walkthroughs": _read_walkthroughs(state),
        "dashboards": _read_dashboards(state),
        "selected_llo": _read_selected_llo(state),
        "solicitation": _read_solicitation(state),
        "launch": _read_launch(state),
        "cycle_grade": _read_cycle_grade(state),
        "opp_eval": _read_opp_eval(state),
        "learnings": _read_learnings(state),
        "open_questions": _read_open_questions(
            drive, opp_folder.id, run_folder.id
        ),
        "stage": _read_stage(state),
        "feedback": _read_feedback(drive, opp_folder.id),
        "workbench_url": workbench_url,
    }
