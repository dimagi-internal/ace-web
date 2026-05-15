"""Walk every UI surface in the beat editor and capture screenshots.

Companion to ``beat_editor_e2e.py``. Focused on visual review, not
assertions. Produces a folder of full-page + focused screenshots:

    qa-results/<UTC-iso>/screenshots/
        00-list-view.png
        01-editor-clean.png
        02-narration-drawer.png
        02-narration-drawer-typed.png
        03-clip-trim-drawer.png
        04-stat-drawer.png
        04-stat-drawer-clear-source.png
        05-dirty-state.png
        06-save-in-flight.png
        07-saved.png
        08-discard-confirm.png
        09-trim-handle-focused.png
        10-bottom-of-list.png

Run with::

    BASE=http://localhost:8002/ace uv run --extra walkthrough \
        python scripts/qa/beat_editor_screenshots.py
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

BASE = os.environ.get("BASE", "http://localhost:8002/ace").rstrip("/")
WORKSPACE = os.environ.get("WORKSPACE", "dimagi-team")
SLUG = os.environ.get("PROGRAM_SLUG", "chc")
EMAIL = os.environ.get("LABS_EMAIL", "ace@dimagi-ai.com")

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "qa-results" / dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ") / "screenshots"


def shot(page: Page, name: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / f"{name}.png"
    page.screenshot(path=str(p), full_page=True)
    print(f"  ✓ {p.relative_to(REPO)}")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    print(f"[shots] base={BASE} workspace={WORKSPACE} slug={SLUG}")
    print(f"[shots] out={OUT.relative_to(REPO)}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1280, "height": 900})
        resp = ctx.request.post(
            f"{BASE}/auth/test-login/",
            data=json.dumps({"email": EMAIL, "display_name": "ACE Bot"}),
            headers={"Content-Type": "application/json"},
        )
        assert resp.status == 200, f"login failed: {resp.status}"

        page = ctx.new_page()

        # 00 — list view (programs index)
        page.goto(f"{BASE}/w/{WORKSPACE}/videos", wait_until="domcontentloaded")
        page.wait_for_timeout(2000)
        shot(page, "00-list-view")

        # 01 — editor clean (no edits)
        page.goto(f"{BASE}/w/{WORKSPACE}/videos/{SLUG}", wait_until="domcontentloaded")
        page.wait_for_selector("[data-beat-id]", timeout=20000)
        page.wait_for_timeout(800)
        shot(page, "01-editor-clean")

        # Hover a narration widget (show hover state)
        page.locator('[data-testid="narration-widget"]').first.hover()
        page.wait_for_timeout(200)
        shot(page, "01b-narration-hover")

        # 02 — narration drawer (just opened)
        page.locator('[data-testid="narration-widget"]').first.click()
        page.wait_for_selector("textarea", timeout=5000)
        page.wait_for_timeout(400)
        shot(page, "02-narration-drawer")

        # 02b — narration drawer with new text typed
        ta = page.locator("aside textarea, div[role='dialog'] textarea").first
        ta.fill("Pretend this is a new, dramatically rewritten voiceover line for the hook.")
        page.wait_for_timeout(200)
        shot(page, "02b-narration-typed")
        # Close without saving
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)

        # 03 — clip trim drawer (scroll to scene beat)
        page.locator('[data-beat-id="scene"]').scroll_into_view_if_needed()
        page.wait_for_timeout(200)
        scene_beat = page.locator('[data-beat-id="scene"]')
        scene_beat.locator('[data-testid="clip-slot-widget"]').first.click()
        page.wait_for_selector("text=Trim", timeout=5000)
        page.wait_for_timeout(800)  # video metadata load
        shot(page, "03-clip-trim-drawer")
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)

        # 04 — stat drawer
        page.locator('[data-beat-id="problem"]').scroll_into_view_if_needed()
        page.wait_for_timeout(200)
        problem_beat = page.locator('[data-beat-id="problem"]')
        problem_beat.locator('[data-testid="stats-widget"]').first.click()
        page.wait_for_selector("input[aria-label='big']", timeout=5000)
        page.wait_for_timeout(300)
        shot(page, "04-stat-drawer")
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)

        # 05 — dirty state (after committing narration edit)
        page.locator('[data-beat-id="hook"]').scroll_into_view_if_needed()
        page.locator('[data-testid="narration-widget"]').first.click()
        page.wait_for_selector("textarea", timeout=5000)
        page.locator("aside textarea, div[role='dialog'] textarea").first.fill(
            "Polished voiceover line for the dirty-state screenshot."
        )
        page.get_by_role("button", name="Done").click()
        page.wait_for_timeout(500)
        shot(page, "05-dirty-state")

        # 05b — pending-edits tooltip on TopBar hover
        page.get_by_text("edit pending", exact=False).hover()
        page.wait_for_timeout(400)
        shot(page, "05b-pending-tooltip")

        # 08 — discard confirm
        page.get_by_role("button", name="Discard all").click()
        page.wait_for_timeout(300)
        shot(page, "08-discard-confirm")
        page.get_by_role("button", name="Click again to confirm").click()
        page.wait_for_timeout(400)

        # 10 — bottom of list (impact, outro)
        page.locator('[data-beat-id="cta"]').scroll_into_view_if_needed()
        page.wait_for_timeout(300)
        shot(page, "10-bottom-of-list")

        # 09 — trim handle focused (keyboard nav)
        page.locator('[data-beat-id="scene"]').scroll_into_view_if_needed()
        scene_beat.locator('[data-testid="clip-slot-widget"]').first.click()
        page.wait_for_selector("[data-testid='trim-handle-left']", timeout=5000)
        page.wait_for_timeout(400)
        page.locator("[data-testid='trim-handle-left']").focus()
        page.wait_for_timeout(200)
        shot(page, "09-trim-handle-focused")
        # Keyboard nudge
        page.keyboard.press("ArrowRight")
        page.keyboard.press("ArrowRight")
        page.keyboard.press("ArrowRight")
        page.wait_for_timeout(200)
        shot(page, "09b-trim-handle-nudged")
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)

        # 11 — product beat (multiple clip slots)
        page.locator('[data-beat-id="product"]').scroll_into_view_if_needed()
        page.wait_for_timeout(300)
        shot(page, "11-product-beat-clips")

        # 12 — brand template beats (intro_hook has BrandTemplateWidget)
        page.locator('[data-beat-id="hook"]').scroll_into_view_if_needed()
        page.wait_for_timeout(300)
        shot(page, "12-hook-brand-template")

        browser.close()

    print(f"\n[shots] done — {len(list(OUT.iterdir()))} screenshots")
    print(f"[shots] dir: {OUT.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
