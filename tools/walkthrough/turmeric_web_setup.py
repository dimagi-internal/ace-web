"""Create a Turmeric smoke-test opp via the ace-web wizard on prod.

Uses a Playwright persistent profile at ~/.ace/playwright-profile/ so OAuth
cookies are reused across runs. First run requires an interactive login.

Exit codes:
  0 — opp created and visible in /opps/<slug>/
  2 — config error (missing env, missing profile dir)
  3 — PDD Finder failed (no Turmeric PDD, no PDD folder)
  4 — wizard flow failed (selector not found, form error)
  5 — opp-not-visible-after-create timeout
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from pathlib import Path

# Django bootstrap so we can use the Drive client via the PDD finder.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.production")
import django  # noqa: E402

django.setup()

from django.conf import settings  # noqa: E402

from apps.opps.drive_client import get_drive_client  # noqa: E402
from tools.walkthrough.turmeric_pdd_finder import (  # noqa: E402
    PDDFinderError,
    find_latest_turmeric_pdd,
)

BASE_URL = "https://labs.connect.dimagi.com/ace"
PROFILE_DIR = Path.home() / ".ace" / "playwright-profile"
SLUG_FILE = Path("/tmp/turmeric-smoketest-slug.txt")


def _log(msg: str) -> None:
    print(f"[web-setup] {msg}", file=sys.stderr)


def _compute_slug() -> str:
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M")
    return f"turmeric-smoketest-{stamp}"


def _ensure_profile_dir() -> None:
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)


def main() -> int:
    argparse.ArgumentParser().parse_args()  # accept --help; no flags today

    ace_root = getattr(settings, "ACE_DRIVE_ROOT_FOLDER_ID", "") or ""
    if not ace_root:
        _log("ACE_DRIVE_ROOT_FOLDER_ID not configured")
        return 2

    _log("looking up latest Turmeric PDD in Drive...")
    try:
        title, body = find_latest_turmeric_pdd(
            get_drive_client(), ace_folder_id=ace_root
        )
    except PDDFinderError as exc:
        _log(f"PDD finder failed: {exc}")
        return 3
    _log(f"using PDD: {title} ({len(body)} chars)")

    _ensure_profile_dir()
    slug = _compute_slug()
    display_name = f"Turmeric Smoketest {slug.split('-', 2)[-1]}"

    from playwright.sync_api import sync_playwright  # local import

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=False,
        )
        try:
            page = context.pages[0] if context.pages else context.new_page()

            _log(f"navigating to {BASE_URL}/opps")
            page.goto(f"{BASE_URL}/opps", wait_until="networkidle")
            if "oauth" in page.url.lower() or "login" in page.url.lower():
                _log("OAuth required — complete login in the open browser, then re-run.")
                return 2

            _log(f"opening New Opp wizard, slug={slug}")
            page.get_by_role("button", name="New Opp").click()
            page.get_by_placeholder("malaria-pilot-2026").fill(slug)
            page.get_by_placeholder("Malaria Pilot 2026").fill(display_name)
            page.get_by_placeholder("Describe the intervention").fill(body)
            page.get_by_role("button", name="Create opp").click()

            page.wait_for_url(f"**/opps/{slug}**", timeout=30_000)
            _log(f"landed on /opps/{slug}")

            # Poll the API to confirm Drive sync completed.
            api_resp = page.request.get(f"{BASE_URL}/api/opps/{slug}")
            if api_resp.status != 200:
                _log(f"GET /api/opps/{slug} returned {api_resp.status}")
                return 5

            SLUG_FILE.write_text(slug)
            _log(f"wrote slug to {SLUG_FILE}")
            return 0
        except Exception as exc:  # noqa: BLE001
            _log(f"wizard flow failed: {exc!r}")
            return 4
        finally:
            context.close()


if __name__ == "__main__":
    sys.exit(main())
