import type { Browser, BrowserContext, Page } from "@playwright/test";

/**
 * Authenticate against a live ace-web instance via
 * POST /ace/auth/e2e-login/.
 *
 * Unlike e2e/helpers/auth.ts's `loginAs`, which uses the dev-only
 * /auth/test-login/ endpoint (gated by DEBUG=True), this helper hits
 * the pre-shared-token endpoint that labs has registered for
 * automated tools. Pass the token via the ACE_E2E_AUTH_TOKEN env var;
 * the canonical bot identity is ace@dimagi-ai.com.
 *
 * Returns the authenticated context — caller is responsible for
 * closing it.
 */
export async function newSmokeContext(
  browser: Browser,
  email = "ace@dimagi-ai.com",
  displayName = "ACE Smoke Bot",
): Promise<{
  context: BrowserContext;
  page: Page;
  user: { userId: number; email: string };
}> {
  const token = process.env.ACE_E2E_AUTH_TOKEN;
  if (!token) {
    throw new Error(
      "ACE_E2E_AUTH_TOKEN env var is required for smoke tests. " +
        "Get the value from deploy/aws/task-definition.json (ACE_E2E_AUTH_TOKEN entry).",
    );
  }

  const context = await browser.newContext();
  const page = await context.newPage();

  const response = await page.request.post("/ace/auth/e2e-login/", {
    data: { email, display_name: displayName, token },
  });

  if (!response.ok()) {
    throw new Error(
      `e2e-login failed with status ${response.status()}: ${await response.text()}`,
    );
  }

  const body = await response.json();

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
    user: { userId: body.user_id, email: body.email },
  };
}
