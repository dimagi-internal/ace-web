"""Find the most recently modified Turmeric PDD under the ACE Drive root.

Used by both the web and CLI Turmeric smoke-test setup scripts. Reads through
the shared DriveClient abstraction so tests run against FakeDriveClient.
"""
from __future__ import annotations

from apps.opps.drive_client import DriveClient


class PDDFinderError(RuntimeError):
    """Raised when the PDD folder or the Turmeric file cannot be located."""


def _is_folder(mime: str) -> bool:
    return mime == "application/vnd.google-apps.folder"


def find_latest_turmeric_pdd(
    client: DriveClient, *, ace_folder_id: str
) -> tuple[str, str]:
    """Return (title, body) of the most recent Turmeric PDD.

    Two-step lookup:
      1. Under ace_folder_id, find a subfolder whose name contains
         'PDD' or 'Program Design Doc' (case-insensitive). If multiple
         match, pick the most recently modified.
      2. Inside that folder, find files whose name contains 'turmeric'
         (case-insensitive). Pick the most recent by modified_time.

    Raises PDDFinderError if either step finds nothing.
    """
    pdd_folders = [
        f for f in client.list_files(ace_folder_id)
        if _is_folder(f.mime_type)
        and (
            "pdd" in f.name.lower()
            or "program design doc" in f.name.lower()
        )
    ]
    if not pdd_folders:
        raise PDDFinderError(
            f"no PDD folder found under ACE root {ace_folder_id!r} "
            "(looked for names containing 'PDD' or 'Program Design Doc')"
        )
    pdd_folders.sort(key=lambda f: f.modified_time or "", reverse=True)
    pdd_folder = pdd_folders[0]

    turmeric_files = [
        f for f in client.list_files(pdd_folder.id)
        if not _is_folder(f.mime_type) and "turmeric" in f.name.lower()
    ]
    if not turmeric_files:
        raise PDDFinderError(
            f"no turmeric file in PDD folder {pdd_folder.name!r}"
        )
    turmeric_files.sort(key=lambda f: f.modified_time or "", reverse=True)
    picked = turmeric_files[0]

    content = client.get_content(picked.id, picked.mime_type)
    return picked.name, content.content


if __name__ == "__main__":
    # Convenience: `python -m tools.walkthrough.turmeric_pdd_finder --print-body`
    # prints only the body to stdout. Used by turmeric_cli_setup.sh.
    import argparse
    import os
    import sys

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.production")
    import django
    django.setup()

    from django.conf import settings

    from apps.opps.drive_client import get_drive_client

    parser = argparse.ArgumentParser()
    parser.add_argument("--print-body", action="store_true")
    parser.add_argument("--print-title", action="store_true")
    args = parser.parse_args()

    ace_root = getattr(settings, "ACE_DRIVE_ROOT_FOLDER_ID", "") or ""
    if not ace_root:
        print("ACE_DRIVE_ROOT_FOLDER_ID not configured", file=sys.stderr)
        sys.exit(2)

    client = get_drive_client()
    try:
        title, body = find_latest_turmeric_pdd(client, ace_folder_id=ace_root)
    except PDDFinderError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(3)

    if args.print_title:
        print(title)
    elif args.print_body:
        print(body)
    else:
        print(f"{title}\n---\n{body}")
