"""Django Ninja v2 router for the opps Workbench surface."""
from __future__ import annotations

import datetime as dt
import logging
from typing import Annotated

from django.http import HttpRequest
from ninja import Path, Router

from apps.api_v2.auth import session_auth
from apps.api_v2.deps import resolve_workspace_for_member
from apps.api_v2.pagination import Page, paginate

from .schemas import OppCardOut

log = logging.getLogger(__name__)

router = Router(auth=session_auth, tags=["opps"])

_EPOCH = dt.datetime(1970, 1, 1, tzinfo=dt.UTC)


def list_opp_cards(workspace) -> list[dict]:
    """Return a list of dicts shaped for OppCardOut from the workspace's Drive root.

    Wraps the Drive-reading machinery in apps/opps/sync.py and
    apps/opps/views._opp_list_impl. The monkeypatch target in contract
    tests is this module-level function.

    Field mapping from OppCard / OppManifest to OppCardOut:
      title        <- card.opp.display_name
      current_phase <- card.current_phase (unchanged)
      current_skill <- card.current_step
      run_count    <- card.run_count
      last_run_id  <- card.opp.current_run_id
      updated_at   <- card.last_activity_at (ISO-8601 string) or epoch fallback
    """
    from apps.opps import access, snapshot_cache
    from apps.opps.drive_cache import CachedDriveClient
    from apps.opps.drive_client import get_drive_client
    from apps.opps.sync import load_opp_card
    from apps.opps.touched_tracker import TouchedFileTracker
    from apps.service_accounts.exceptions import ServiceAccountNotFound

    ace_folder_id = access.resolve_ace_root_folder_id(workspace)
    if ace_folder_id is None:
        return []

    try:
        inner = get_drive_client(workspace=workspace)
    except ServiceAccountNotFound:
        log.warning("list_opp_cards: Drive not configured for workspace %s", workspace.slug)
        return []

    client = CachedDriveClient(inner, bypass=False)

    try:
        root_children = client.list_files(ace_folder_id)
    except Exception as exc:  # noqa: BLE001
        log.warning("list_opp_cards: root Drive listing failed: %s", exc)
        return []

    out: list[dict] = []
    for child in root_children:
        if child.mime_type != "application/vnd.google-apps.folder":
            continue
        opp_children = client.list_files(child.id)
        names = {f.name for f in opp_children}
        if not (
            "idea.md" in names
            or "run_state.yaml" in names
            or "opp.yaml" in names
            or "runs" in names
        ):
            continue

        card = snapshot_cache.get_card(workspace.pk, child.name)
        if card is None:
            try:
                cold_client = snapshot_cache.cold_load_client(client)
                with TouchedFileTracker() as tracker:
                    tracker.record(child.id, child.modified_time)
                    for f in opp_children:
                        tracker.record(f.id, f.modified_time)
                    card = load_opp_card(cold_client, opp_folder=child, opp_children=opp_children)
                access.overlay_workspace_display_name(card.opp, child.name, workspace=workspace)
                snapshot_cache.set_card(
                    workspace_id=workspace.pk,
                    slug=child.name,
                    card=card,
                    file_ids=tracker.file_ids,
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("list_opp_cards: failed to load card for %r: %s", child.name, exc)
                continue
        else:
            access.overlay_workspace_display_name(card.opp, child.name, workspace=workspace)

        # Normalise last_activity_at (Drive ISO-8601 string) to a datetime.
        raw_ts = card.last_activity_at
        if raw_ts:
            try:
                updated_at = dt.datetime.fromisoformat(
                    raw_ts.replace("Z", "+00:00") if raw_ts.endswith("Z") else raw_ts
                )
            except ValueError:
                updated_at = _EPOCH
        else:
            updated_at = _EPOCH

        out.append({
            "slug": card.opp.slug,
            "title": card.opp.display_name,
            "current_phase": card.current_phase,
            "current_skill": card.current_step,
            "run_count": card.run_count,
            "last_run_id": card.opp.current_run_id,
            "updated_at": updated_at,
        })

    return out


@router.get("", response=Page[OppCardOut], summary="List opps in workspace")
def list_opps(
    request: HttpRequest,
    workspace_slug: Annotated[str, Path()],
    offset: int = 0,
    limit: int = 100,
) -> Page[OppCardOut]:
    workspace = resolve_workspace_for_member(request, workspace_slug)
    cards = list_opp_cards(workspace)
    return paginate(
        [OppCardOut.model_validate(c) for c in cards],
        offset=offset,
        limit=limit,
    )
