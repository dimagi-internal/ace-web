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
    | ``synthetic-data-and-workflows`` | ``products.synthetic.{walkthroughs, workflows, labs_opp_id}`` |
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


def _read_yaml(drive: DriveClient, file_id: str) -> dict:
    """Fetch and parse a YAML file by id. Returns ``{}`` on any failure."""
    try:
        content = drive.get_content(file_id, "application/x-yaml")
        body = content.content or ""
    except Exception as exc:  # noqa: BLE001
        log.warning("summary: read yaml %s failed: %s", file_id, exc)
        return ""
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
    pdd = _phase_products(state, "design", "pdd")
    connect_opp = _phase_products(state, "connect-setup", "connect").get("opportunity") or {}
    cycle_grade = _phase_products(state, "closeout", "cycle_grade")

    display_name = (
        pdd.get("title")
        or opp_yaml.get("display_name")
        or opp_slug
    )
    description = pdd.get("description") or ""
    end_date = connect_opp.get("end_date")

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
    apps_block = _phase_products(state, "commcare-setup", "apps")
    out: list[dict] = []
    for kind_key, kind_label in (("learn", "Learn"), ("deliver", "Deliver")):
        app = apps_block.get(kind_key)
        if not isinstance(app, dict) or not app:
            continue
        out.append({
            "kind": kind_label,
            "name": app.get("name") or f"{kind_label} app",
            "nova_url": app.get("nova_url"),
            "hq_url": app.get("hq_url"),
        })
    return out


def _read_connect(state: dict, opp_yaml: dict) -> dict | None:
    connect = _phase_products(state, "connect-setup", "connect")
    program = (opp_yaml.get("connect") or {}).get("program") or connect.get("program") or {}
    opp = connect.get("opportunity") or {}

    opp_block = None
    if opp.get("id") or opp.get("url"):
        opp_block = {
            "name": opp.get("name") or "Connect opportunity",
            "url": opp.get("url"),
            "start_date": opp.get("start_date"),
            "end_date": opp.get("end_date"),
        }

    prog_block = None
    if program.get("id") or program.get("url"):
        prog_block = {
            "name": program.get("name") or "Program",
            "url": program.get("url"),
        }

    if not opp_block and not prog_block:
        return None
    return {"opportunity": opp_block, "program": prog_block}


def _read_training(state: dict) -> dict | None:
    training = _phase_products(state, "qa-and-training", "training")
    if not training:
        return None

    deck_block = None
    deck = training.get("deck") or {}
    if deck.get("file_id") or deck.get("web_view_link"):
        deck_block = {
            "title": deck.get("title") or "Training deck",
            "url": deck.get("web_view_link"),
        }

    docs_block = training.get("docs") or {}
    docs: list[dict] = []
    # Preserve a stable display order matching agent-doc convention.
    for key in ("llo_guide", "flw_guide", "quick_reference", "faq", "onboarding_email"):
        doc = docs_block.get(key) or {}
        if doc.get("web_view_link") or doc.get("file_id"):
            docs.append({
                "title": doc.get("title") or key.replace("_", " ").title(),
                "url": doc.get("web_view_link"),
            })

    if deck_block is None and not docs:
        return None
    return {"deck": deck_block, "docs": docs}


def _read_assistant(state: dict) -> dict | None:
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


def _read_walkthroughs(state: dict) -> list[dict]:
    synthetic = _phase_products(state, "synthetic-data-and-workflows", "synthetic")
    raw = synthetic.get("walkthroughs") or []
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    for w in raw:
        if not isinstance(w, dict):
            continue
        url = w.get("slideshow_url") or w.get("web_view_link")
        if not url:
            continue
        out.append({
            "persona": w.get("persona") or "walkthrough",
            "url": url,
            "eval_score": w.get("eval_score"),
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
    if not learn or not learn.get("summary_file_id"):
        return None
    # File-id-only; we don't render the body, just the deep-link.
    return {
        "summary_file_id": learn.get("summary_file_id"),
        "new_pdd_file_id": learn.get("new_pdd_file_id"),
        "iteration_warranted": bool(learn.get("iteration_warranted")),
    }


def _read_open_questions(drive: DriveClient, run_folder_id: str) -> dict | None:
    """Open Questions doc — no typed handoff yet; Drive fetch required."""
    f = _find_in_folder(drive, run_folder_id, "open-questions.md")
    if f is None or not f.web_view_link:
        return None
    return {"url": f.web_view_link}


# ─── Top-level entry point ─────────────────────────────────────────


def build_summary_payload(
    drive: DriveClient,
    *,
    workspace,
    opp_slug: str,
    run_id: str,
) -> dict | None:
    """Build the public summary JSON payload for a per-run summary page.

    Returns ``None`` when the workspace's ACE root, the opp folder, or
    the requested run folder can't be located, so callers can map to a
    404 without leaking which segment was the miss.
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
        opp_yaml = _read_yaml(drive, opp_yaml_file.id)

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
        state = _read_yaml(drive, state_file.id)

    workspace_slug = getattr(workspace, "slug", "")
    workbench_url = (
        f"/w/{workspace_slug}/opps/{opp_slug}/runs/{run_id}"
        if workspace_slug
        else None
    )

    return {
        "opp": _read_opp(
            state, opp_yaml,
            workspace_slug=workspace_slug,
            opp_slug=opp_slug,
            run_id=run_id,
        ),
        "apps": _read_apps(state),
        "connect": _read_connect(state, opp_yaml),
        "training": _read_training(state),
        "assistant": _read_assistant(state),
        "walkthroughs": _read_walkthroughs(state),
        "selected_llo": _read_selected_llo(state),
        "solicitation": _read_solicitation(state),
        "launch": _read_launch(state),
        "cycle_grade": _read_cycle_grade(state),
        "opp_eval": _read_opp_eval(state),
        "learnings": _read_learnings(state),
        "open_questions": _read_open_questions(drive, run_folder.id),
        "workbench_url": workbench_url,
    }
