import type { Browser, BrowserContext, Page } from "@playwright/test";

/**
 * Log in a test user via the dev-only POST /ace/auth/test-login/
 * endpoint.
 *
 * The endpoint is ``@csrf_exempt`` so it works without any prior
 * token fetch. The response sets the Django ``sessionid`` cookie on
 * the page's browser context; subsequent authenticated navigation
 * in the same context is then a regular same-origin fetch.
 *
 * Also warms the CSRF cookie by performing a follow-up GET to
 * ``/ace/`` — Django's middleware only emits ``csrftoken`` on
 * authenticated responses (unauthenticated requests redirect to the
 * login page before CSRF can be set), so we have to be logged in
 * first. The cookie is required by :func:`postJson` below for any
 * subsequent API POST.
 *
 * Requires ``ACE_ALLOW_TEST_LOGIN=True`` and ``DEBUG=True`` on the
 * server. The e2e.py settings module enables both.
 */
export async function loginAs(
  page: Page,
  email: string,
  displayName: string,
): Promise<{ userId: number; email: string }> {
  const response = await page.request.post("/ace/auth/test-login/", {
    data: { email, display_name: displayName },
  });

  if (!response.ok()) {
    throw new Error(
      `test-login failed with status ${response.status()}: ${await response.text()}`,
    );
  }

  const body = await response.json();

  // Warm the CSRF cookie for subsequent POSTs. Any authenticated GET
  // works; /ace/ is the lightest option.
  const warm = await page.request.get("/ace/");
  if (!warm.ok()) {
    throw new Error(
      `CSRF cookie warm-up GET /ace/ failed with ${warm.status()}: ${await warm.text()}`,
    );
  }

  return { userId: body.user_id, email: body.email };
}

/**
 * Create a fresh authenticated browser context for a user. Returns
 * the context + a page + the user info. Caller is responsible for
 * closing the context.
 */
export async function newAuthedContext(
  browser: Browser,
  email: string,
  displayName: string,
): Promise<{
  context: BrowserContext;
  page: Page;
  user: { userId: number; email: string };
}> {
  const context = await browser.newContext();
  const page = await context.newPage();
  const user = await loginAs(page, email, displayName);
  return { context, page, user };
}

/**
 * Read the ``csrftoken`` cookie value for the given context.
 *
 * DRF's default ``SessionAuthentication`` enforces CSRF on POSTs
 * from session-authenticated users. The frontend solves this by
 * being same-origin + sending the ``X-CSRFToken`` header on every
 * unsafe method; the Playwright helpers below mirror that by
 * plucking the cookie and re-attaching it on each request.
 */
export async function getCsrfToken(context: BrowserContext): Promise<string> {
  const cookies = await context.cookies();
  const csrf = cookies.find((c) => c.name === "csrftoken");
  if (!csrf) {
    throw new Error(
      "csrftoken cookie not found — did you call loginAs() first?",
    );
  }
  return csrf.value;
}

/**
 * Issue an authenticated JSON POST with the ``X-CSRFToken`` header
 * populated from the browser context's cookies.
 *
 * Prefer this over a raw ``page.request.post()`` for any API call
 * against a session-authenticated endpoint.
 */
export async function postJson<T = unknown>(
  page: Page,
  url: string,
  data: Record<string, unknown>,
): Promise<T> {
  const csrf = await getCsrfToken(page.context());
  const response = await page.request.post(url, {
    data,
    headers: { "X-CSRFToken": csrf },
  });
  if (!response.ok()) {
    throw new Error(
      `POST ${url} failed: ${response.status()} ${await response.text()}`,
    );
  }
  return response.json() as Promise<T>;
}
