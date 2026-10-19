"""Fill each opp's `connect_program_ids` from its `opp.yaml` (ace-web#914).

ACE records an opp's Connect program once, in `ACE/<slug>/opp.yaml` at
`connect.program.connect_int_id` (Connect's integer program id — the id labs
calls `program_id`). This copies that id into the opp's tenancy so ACE's
tenancy guard can check program-scoped labs writes against it.

Same rules as the 0006/0007 tenancy backfills: fill-empty-only (an opp whose
tenancy already carries `connect_program_ids` is never touched, so an owner's
edit wins), and every change is a `TenancyChange` row attributed to the person
who ran it. An opp with no program in its opp.yaml yet (it has not reached
ACE's Phase 4) is reported and skipped; ACE adds the program to the tenancy
itself when it creates one (`bin/ace-bind --add-program`), and this is safe to
re-run.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import yaml

from apps.opps import tenancy as tenancy_mod
from apps.opps.drive_client import DriveClient

log = logging.getLogger(__name__)

FIELD = "connect_program_ids"
_FOLDER = "application/vnd.google-apps.folder"


@dataclass
class Result:
    slug: str
    action: str  # "set" | "would-set" | "already-set" | "no-program" | "unreadable"
    program_ids: list[int] | None = None
    detail: str = ""


def program_id_from_opp_yaml(data: dict) -> int | None:
    """`connect.program.connect_int_id` as a positive int, or None."""
    program = ((data or {}).get("connect") or {}).get("program") or {}
    raw = program.get("connect_int_id") if isinstance(program, dict) else None
    if isinstance(raw, bool):
        return None
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _read_opp_yaml(client: DriveClient, folder_id: str) -> dict | None:
    """The opp's parsed opp.yaml; {} when it has none; None when unreadable."""
    for f in client.list_folder(folder_id):
        if f.name == "opp.yaml" and f.mime_type != _FOLDER:
            try:
                return yaml.safe_load(client.get_content(f.id, f.mime_type).content) or {}
            except Exception as exc:  # noqa: BLE001 — one bad file must not stop the sweep
                log.warning("opp.yaml unreadable in folder %s: %s", folder_id, exc)
                return None
    return {}


def backfill_workspace(workspace, client: DriveClient, *, apply: bool, user=None) -> list[Result]:
    """Walk every opp folder under the workspace's Drive root.

    `apply=False` reports what would change. `apply=True` needs `user`: it is
    the audit attribution, and the `created_by` of an opp row this has to
    materialise (a Drive-only opp has no `OppWorkspace` row until something
    writes its tenancy, exactly like the tenancy PATCH)."""
    from django.db import transaction

    from apps.opps.models import OppWorkspace

    if apply and user is None:
        raise ValueError("apply=True needs the user the changes are attributed to")
    root = workspace.drive_root_folder_id
    if not root:
        return []
    results: list[Result] = []
    for folder in sorted(client.list_folder(root), key=lambda f: f.name):
        if folder.mime_type != _FOLDER or folder.name.startswith(("_", ".")):
            continue
        slug = folder.name
        data = _read_opp_yaml(client, folder.id)
        if data is None:
            results.append(Result(slug, "unreadable", detail="opp.yaml did not parse"))
            continue
        if not data:
            # No opp.yaml: not an opp folder (Projects/, a legacy flat opp).
            continue
        program_id = program_id_from_opp_yaml(data)
        row = OppWorkspace.objects.filter(workspace=workspace, slug=slug).first()
        current = tenancy_mod.clean(
            row.tenancy if row is not None else workspace.default_tenancy
        )
        if current.get(FIELD):
            results.append(Result(slug, "already-set", current[FIELD]))
            continue
        if program_id is None:
            results.append(Result(slug, "no-program",
                                  detail="opp.yaml has no connect.program.connect_int_id"))
            continue
        if not apply:
            results.append(Result(slug, "would-set", [program_id]))
            continue
        with transaction.atomic():
            row, _ = OppWorkspace.objects.select_for_update().get_or_create(
                workspace=workspace,
                slug=slug,
                defaults={
                    "display_name": data.get("display_name") or slug,
                    "created_by": user,
                    "tenancy": tenancy_mod.clean(workspace.default_tenancy),
                },
            )
            before = tenancy_mod.clean(row.tenancy)
            if before.get(FIELD):  # set by someone else since we looked
                results.append(Result(slug, "already-set", before[FIELD]))
                continue
            after = tenancy_mod.merge(before, {FIELD: [program_id]})
            row.tenancy = after
            row.save(update_fields=["tenancy", "updated_at"])
            tenancy_mod.record_change(
                workspace=workspace, opp_slug=slug, user=user, before=before, after=after,
            )
        results.append(Result(slug, "set", [program_id]))
    return results
