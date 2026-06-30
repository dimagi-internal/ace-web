"""Wave-4 run-reader swap: the ace-side shim that routes the three opp-read
chokepoints (``load_opp`` / ``load_opp_card`` / ``list_opp_runs``) through the
framework's ``canopy_agent_runs.drive.store.DriveRunStore`` instead of ace's own
inline sync logic, then maps the storage-agnostic read model back onto ace's
legacy dataclasses via ``apps.opps.framework_map``.

Why a shim layer (and not a rewrite of sync.py): the chokepoint SIGNATURES +
return types are a load-bearing public contract (api.py, freshness_overlays.py,
serializers.py, the OppSnapshot/RunDetail/StepSnapshot/RunSummary field names).
This module keeps those identical while the *engine* underneath becomes the
framework lib.

What the framework supplies vs. what ace supplies
-------------------------------------------------
``DriveRunStore`` returns the run lifecycle read model (per-step STATUS, judge
verdicts, QA results, the run header: mode/current_phase/current_step/started_at
/derived run status). As of the wave-4 enrichment ace is a TRUE single reader:
the framework ``Artifact`` now carries ``ref`` (the Drive file id) + ``path``
(run-relative), and the framework ``Decision`` ported ACE's full decisions-schema
(``id`` / ``phase`` / ``options_considered`` / ``source`` /
``override_reasoning`` / ``conflict_signals``). Both map straight across in
``framework_map`` — there is NO second pass over the run tree to re-attribute
artifacts or re-load decisions.

Only the genuinely framework-unavailable Drive-identity / body fields are still
supplied ace-side (opp manifest, pdd body, folder ids, per-run phase progress +
last_actor), plus the one-line raw run-mode override (the framework canonicalizes
``mode`` to review|auto; ace keeps the literal run_state value).

Cache + file-id tracking: every Drive read the store issues goes through the
SAME client instance the chokepoint received — in production a
``CachedDriveClient`` wrapping a ``TouchedFileTracker``-aware client — so the
store's ``list_folder`` / ``list_files`` / ``get_content`` calls populate the
snapshot-cache reverse index exactly as the legacy reader did. For the flat
layout the synthetic-run adapter (``_FlatRunClient``) only fabricates the two
virtual ``runs/`` + ``r1`` folder listings; every *real* read still flows
through the wrapped client, so touched file-ids keep being captured.

Both Drive layouts are handled:
  * **multi-run** — ``<opp>/runs/<run-id>/`` — the store reads natively.
  * **flat (legacy)** — ``run_state.yaml`` at the opp root, no ``runs/`` — the
    opp folder is presented to the store as a single synthetic run ``r1`` via
    ``_FlatRunClient``.
"""

from __future__ import annotations

import logging

import yaml
from canopy_agent_runs.drive.store import DriveRunStore

from apps.opps import framework_map as fm
from apps.opps.drive_client import DriveClient, DriveFile

log = logging.getLogger(__name__)

FOLDER_MIME = "application/vnd.google-apps.folder"


# --------------------------------------------------------------------------- #
# store construction (ace's own manifest + skill registry, INJECTED)
# --------------------------------------------------------------------------- #
def build_store(
    client: DriveClient,
    root_folder_id: str,
    slug: str,
    overview: dict,
    skill_registry,
) -> DriveRunStore:
    """Build a ``DriveRunStore`` bound to ``root_folder_id`` with ace's live
    artifact manifest + skill registry injected (never the lib defaults, and
    never via Django settings — the lib stays Django-free)."""
    return DriveRunStore(
        client,
        root_folder_id,
        agent_slug=slug,
        manifest=list(overview.get("artifacts") or []),
        skill_registry=list(skill_registry),
    )


# --------------------------------------------------------------------------- #
# flat-layout synthetic-run adapter
# --------------------------------------------------------------------------- #
class _FlatRunClient:
    """Wrap a DriveClient so a FLAT opp folder (``run_state.yaml`` at the opp
    root, no ``runs/`` subfolder) reads to ``DriveRunStore`` as a single-run
    multi-run layout.

    The synthetic root (``ROOT``) contains one synthetic ``runs/`` folder
    (``RUNS``) whose only child ``r1`` IS the real opp folder. ``DriveRunStore``
    is constructed with ``root_folder_id=ROOT``; everything below ``r1`` is the
    real opp tree, so all real reads delegate to the wrapped client (preserving
    its caching + touched-file tracking). Only the two virtual folder listings
    are fabricated; no real Drive call is shadowed.
    """

    ROOT = "__flat_root__"
    RUNS = "__flat_runs__"
    RUN_ID = "r1"

    def __init__(self, inner: DriveClient, opp_folder: DriveFile) -> None:
        self._inner = inner
        self._opp_folder = opp_folder

    def _runs_df(self) -> DriveFile:
        return DriveFile(id=self.RUNS, name="runs", mime_type=FOLDER_MIME, web_view_link="")

    def _run_df(self) -> DriveFile:
        return DriveFile(
            id=self._opp_folder.id,
            name=self.RUN_ID,
            mime_type=FOLDER_MIME,
            web_view_link="",
        )

    def list_folder(self, folder_id: str) -> list[DriveFile]:
        if folder_id == self.ROOT:
            return [self._runs_df()]
        if folder_id == self.RUNS:
            return [self._run_df()]
        return self._inner.list_folder(folder_id)

    def list_files(
        self, folder_id: str, recursive: bool = False, page_size: int = 100
    ) -> list[DriveFile]:
        if folder_id == self.ROOT:
            return [self._runs_df(), self._run_df()] if recursive else [self._runs_df()]
        if folder_id == self.RUNS:
            return [self._run_df()]
        return self._inner.list_files(folder_id, recursive=recursive, page_size=page_size)

    def get_content(self, file_id: str, mime_type: str):
        return self._inner.get_content(file_id, mime_type)

    def get_file(self, file_id: str) -> DriveFile:
        return self._inner.get_file(file_id)

    def __getattr__(self, name: str):
        # Delegate the write + changes surface (unused by the read path) to the
        # wrapped client so the object still satisfies the DriveClient shape.
        return getattr(self._inner, name)


# --------------------------------------------------------------------------- #
# small Drive helpers (kept local so the shim doesn't hard-depend on sync's
# private helpers at import time — they're imported lazily where needed)
# --------------------------------------------------------------------------- #
def _find_child(files: list[DriveFile], name: str) -> DriveFile | None:
    for f in files:
        if f.name == name:
            return f
    return None


def _find_child_folder(files: list[DriveFile], name: str) -> DriveFile | None:
    f = _find_child(files, name)
    if f and f.mime_type == FOLDER_MIME:
        return f
    return None


def _read_state(client: DriveClient, run_children: list[DriveFile]) -> dict:
    state_file = _find_child(run_children, "run_state.yaml")
    if state_file is None:
        return {}
    try:
        data = yaml.safe_load(client.get_content(state_file.id, state_file.mime_type).content) or {}
    except yaml.YAMLError:
        log.warning("run_state.yaml is not valid YAML")
        return {}
    return data if isinstance(data, dict) else {}


def _run_folders_and_states(
    client: DriveClient, runs_folder: DriveFile
) -> tuple[dict[str, str], dict[str, dict]]:
    """Walk ``runs/`` once and return ``({run_id: folder_id}, {run_id: state})``
    for every run folder that carries a ``run_state.yaml`` (the framework's run
    definition + the legacy reader's, in agreement)."""
    folder_by_run: dict[str, str] = {}
    state_by_run: dict[str, dict] = {}
    for child in client.list_folder(runs_folder.id):
        if child.mime_type != FOLDER_MIME:
            continue
        run_children = client.list_folder(child.id)
        if _find_child(run_children, "run_state.yaml") is None:
            continue
        folder_by_run[child.name] = child.id
        state_by_run[child.name] = _read_state(client, run_children)
    return folder_by_run, state_by_run


# --------------------------------------------------------------------------- #
# run-summary list (backs list_opp_runs + load_opp_card's runs_summary)
# --------------------------------------------------------------------------- #
def runs_summary_via_store(
    client: DriveClient,
    *,
    opp_folder: DriveFile,
    runs_folder: DriveFile,
    slug: str,
    overview: dict,
    skill_registry,
) -> list:
    """Return ace ``RunSummary`` rows (newest-first by run-id) for a multi-run
    opp, sourced from ``DriveRunStore.list_runs`` and mapped via
    ``framework_map.map_run_summary``.

    Per-run ``folder_id`` + raw ``run_state`` (the framework RunSummary lacks
    both) are supplied from a single ``runs/`` walk; phase-progress + last_actor
    are derived by the mapper through ace's own ``_derive_phase_progress`` so the
    list view stays parity-exact. ``mode`` is overridden to the raw run_state
    value (the framework canonicalizes it to review/auto)."""
    store = build_store(client, opp_folder.id, slug, overview, skill_registry)
    fw_summaries = store.list_runs(slug)
    folder_by_run, state_by_run = _run_folders_and_states(client, runs_folder)

    out = []
    for fw in fw_summaries:
        state = state_by_run.get(fw.id) or {}
        rs = fm.map_run_summary(
            fw,
            folder_id=folder_by_run.get(fw.id, ""),
            run_state=state,
        )
        _apply_legacy_summary_overrides(rs, state)
        out.append(rs)
    out.sort(key=lambda r: r.run_id, reverse=True)
    return out


def _apply_legacy_summary_overrides(rs, state: dict) -> None:
    """Reconcile the framework RunSummary back to the legacy ace reader's exact
    values for the fields the framework reduces/canonicalizes:

      * ``mode`` — framework RunMode is review|auto; ace keeps the literal
        run_state value (e.g. ``default``).
      * ``current_phase`` / ``current_step`` — the framework header reads only
        ``current_phase`` / ``current_step``; ACE's older run_state uses bare
        ``phase`` / ``step``. Restore the legacy precedence.
      * phase-progress (``lifecycle_status`` / ``phases_*`` / ``latest_phase_done``)
        — re-derived via ace's own ``_derive_phase_progress`` against the
        (now-corrected) current_phase, since ``map_run_summary`` computed it
        from the framework's empty current_phase.
    """
    from apps.opps.sync import _derive_phase_progress

    rs.mode = state.get("mode")
    rs.current_phase = state.get("phase") or state.get("current_phase")
    rs.current_step = state.get("step") or state.get("current_step")
    progress = _derive_phase_progress(state, rs.current_phase)
    rs.lifecycle_status = progress["status"]
    rs.phases_total = progress["phases_total"]
    rs.phases_done = progress["phases_done"]
    rs.latest_phase_done = progress["latest_phase_done"]


def flat_runs_summary_via_store(
    client: DriveClient,
    *,
    opp_folder: DriveFile,
    slug: str,
    overview: dict,
    skill_registry,
) -> list:
    """Single-row ace ``RunSummary`` list for a FLAT-layout opp (the synthetic
    ``r1`` run), sourced from the store via ``_FlatRunClient``. Returns ``[]``
    when the opp has no ``run_state.yaml`` at its root."""
    flat_client = _FlatRunClient(client, opp_folder)
    store = build_store(flat_client, _FlatRunClient.ROOT, slug, overview, skill_registry)
    fw_summaries = store.list_runs(slug)
    if not fw_summaries:
        return []
    state = _read_state(client, client.list_folder(opp_folder.id))
    out = []
    for fw in fw_summaries:
        rs = fm.map_run_summary(fw, folder_id=opp_folder.id, run_state=state)
        _apply_legacy_summary_overrides(rs, state)
        out.append(rs)
    return out


# --------------------------------------------------------------------------- #
# full opp snapshot — multi-run layout
# --------------------------------------------------------------------------- #
def load_opp_run_via_store(
    client: DriveClient,
    *,
    opp_folder: DriveFile,
    run_id: str | None,
    runs_summary: list,
    slug: str,
    overview: dict,
    skill_registry,
):
    """Assemble an ``OppSnapshot`` for a specific run of a multi-run opp from
    ``DriveRunStore.get_run`` + ``framework_map.map_run_detail``, recovering the
    reduced field-groups ace-side."""
    from apps.opps.parsers import OppManifest
    from apps.opps.sync import OppSnapshot, _read_opp_yaml

    if run_id is None:
        target_id = runs_summary[0].run_id
    else:
        if not any(r.run_id == run_id for r in runs_summary):
            raise FileNotFoundError(f"run {run_id!r} not found under opp {slug!r}")
        target_id = run_id

    run_folder_id = next(r.folder_id for r in runs_summary if r.run_id == target_id)

    store = build_store(client, opp_folder.id, slug, overview, skill_registry)
    fw_run = store.get_run(slug, target_id)

    run_children = client.list_folder(run_folder_id)
    state_data = _read_state(client, run_children)
    opp_folder_children = client.list_folder(opp_folder.id)

    # pdd.md / idea.md: prefer run folder, fall back to opp-root inputs/.
    pdd_file = (
        _find_child(run_children, "pdd.md")
        or _find_child(run_children, "idd.md")
        or _find_child(run_children, "idea.md")
    )
    if pdd_file is None:
        inputs_folder = _find_child_folder(opp_folder_children, "inputs")
        if inputs_folder is not None:
            inputs_children = client.list_folder(inputs_folder.id)
            pdd_file = _find_child(inputs_children, "pdd.md") or _find_child(
                inputs_children, "idea.md"
            )
    pdd_body = client.get_content(pdd_file.id, pdd_file.mime_type).content if pdd_file else ""

    rd = fm.map_run_detail(fw_run, folder_id=run_folder_id, run_state=state_data)
    # Framework canonicalizes mode to review|auto; ace keeps the literal.
    rd.mode = state_data.get("mode") or rd.mode
    # current_phase/current_step: mirror the legacy ``_load_opp_run`` exactly —
    # take them from the matching run-summary row (which already applied the
    # ``phase``/``step`` → ``current_*`` precedence).
    target_summary = next(r for r in runs_summary if r.run_id == target_id)
    rd.current_phase = target_summary.current_phase
    rd.current_step = target_summary.current_step

    opp_data = _read_opp_yaml(client, opp_folder.id)
    display_name = opp_data.get("display_name") or state_data.get("display_name") or slug
    opp_manifest = OppManifest(
        slug=slug,
        display_name=display_name,
        created_at=opp_data.get("created_at") or state_data.get("started_at"),
        created_by=opp_data.get("created_by") or state_data.get("initiated_by"),
        labels=[],
        current_run_id=target_id,
    )

    return OppSnapshot(
        opp=opp_manifest,
        pdd_body=pdd_body,
        opp_folder_id=opp_folder.id,
        current_run=rd,
        runs_summary=runs_summary,
    )


# --------------------------------------------------------------------------- #
# full opp snapshot — flat (legacy) layout
# --------------------------------------------------------------------------- #
def load_opp_flat_via_store(
    client: DriveClient,
    *,
    opp_folder: DriveFile,
    slug: str,
    overview: dict,
    skill_registry,
):
    """Assemble an ``OppSnapshot`` for a FLAT-layout opp (``run_state.yaml`` at
    the opp root, no ``runs/``). The opp folder is presented to
    ``DriveRunStore`` as a single synthetic run ``r1`` via ``_FlatRunClient``;
    artifacts + decisions come straight from the framework read model."""
    from apps.opps.parsers import OppManifest
    from apps.opps.sync import OppSnapshot

    opp_children = client.list_folder(opp_folder.id)
    state_data = _read_state(client, opp_children)

    # IDD→PDD rename transition: accept either primary-doc filename.
    pdd_file = _find_child(opp_children, "pdd.md") or _find_child(opp_children, "idd.md")
    pdd_body = client.get_content(pdd_file.id, pdd_file.mime_type).content if pdd_file else ""

    flat_client = _FlatRunClient(client, opp_folder)
    store = build_store(flat_client, _FlatRunClient.ROOT, slug, overview, skill_registry)
    fw_run = store.get_run(slug, _FlatRunClient.RUN_ID)

    rd = fm.map_run_detail(fw_run, folder_id=opp_folder.id, run_state=state_data)
    # Framework canonicalizes mode to review|auto; ace keeps the literal.
    rd.mode = state_data.get("mode") or rd.mode
    # Flat layout: the legacy ``_load_opp_flat`` reads current_phase/current_step
    # from the opp-root run_state's ``current_*`` keys only (no phase/step
    # fallback).
    rd.current_phase = state_data.get("current_phase")
    rd.current_step = state_data.get("current_step")

    opp_manifest = OppManifest(
        slug=slug,
        display_name=state_data.get("display_name", slug),
        created_at=state_data.get("started_at") or state_data.get("created"),
        created_by=state_data.get("created_by") or state_data.get("initiated_by"),
        labels=[],
        current_run_id=_FlatRunClient.RUN_ID,
    )

    return OppSnapshot(
        opp=opp_manifest,
        pdd_body=pdd_body,
        opp_folder_id=opp_folder.id,
        current_run=rd,
        runs_summary=[],
    )
