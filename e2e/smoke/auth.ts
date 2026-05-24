import type { Browser, BrowserContext, Page } from "@playwright/test";

/**
 * Authenticate against a live ace-web instance via
 * POST /ace/api/auth/pat-to-session with a Bearer PAT.
 *
 * Unlike e2e/helpers/auth.ts's `loginAs`, which uses the dev-only
 * /auth/test-login/ endpoint (gated by DEBUG=True), this helper trades
 * an ACE_WEB_PAT_TOKEN PAT for a Django session cookie via the
 * pat-to-session endpoint that exists on every deployed instance.
 * Mint a PAT one-time per machine via /ace:ace-web-pat-mint; the
 * token attributes back to the authorizing human (not a shared bot
 * identity).
 *
 * Returns the authenticated context — caller is responsible for
 * closing it. The returned `user.email` is whoever minted the PAT.
 */
export async function newSmokeContext(
  browser: Browser,
): Promise<{
  context: BrowserContext;
  page: Page;
  user: { userId: number; email: string };
}> {
  const token = process.env.ACE_WEB_PAT_TOKEN;
  if (!token) {
    throw new Error(
      "ACE_WEB_PAT_TOKEN env var is required for smoke tests. " +
        "Mint one via /ace:ace-web-pat-mint (one-time gh-style loopback flow).",
    );
  }

  const context = await browser.newContext();
  const page = await context.newPage();

  // Trade the PAT for a session cookie. The endpoint accepts Bearer
  // auth and calls login() so the response Set-Cookie carries the
  // tenant-specific sessionid_ace.
  const response = await page.request.post("/ace/api/auth/pat-to-session", {
    headers: { Authorization: `Bearer ${token}` },
  });

  if (!response.ok()) {
    throw new Error(
      `pat-to-session failed with status ${response.status()}: ${await response.text()}`,
    );
  }

  // Read the authenticated user via /api/auth/me — the smoke tests want
  // to know who they're logged in as so they can scope assertions.
  const meResp = await page.request.get("/ace/api/auth/me");
  if (!meResp.ok()) {
    throw new Error(`GET /api/auth/me failed with ${meResp.status()}`);
  }
  const me = await meResp.json();

  // Warm the CSRF cookie for any subsequent POSTs.
  const warm = await page.request.get("/ace/");
  if (!warm.ok()) {
    throw new Error(
      `CSRF cookie warm-up GET /ace/ failed with ${warm.status()}`,
    );
  }

  return {
    context,
    page,
    user: { userId: me.id, email: me.email },
  };
}
