import { createTokenStore } from "canopy-client";

import { apiClient } from "../api/apiClient";

/**
 * The browser's cached delegated canopy token.
 *
 * The cache itself is `canopy-client`'s `createTokenStore` — the package
 * canopy-web extracted FROM this file, so the logic here was the original and
 * is now the shared one. What stays is the part that cannot be shared: HOW
 * ace-web mints. That needs ace-web's `AppCredential`, which is a secret and
 * can only live on ace-web's server, so the package takes a `fetchToken`
 * callback and knows nothing about the exchange. That single inversion is what
 * lets one package serve this SPA, a Django page and an iframe widget.
 *
 * ONE store for the app. The package de-globalised its own because a WIDGET can
 * be mounted twice and the two would leak state into each other; ace-web is a
 * single-user SPA minting one token for one signed-in human, and a single store
 * is what keeps the in-flight dedup meaningful — several components mounting in
 * the same tick (sidebar + chat panel + placement poll) would otherwise fire N
 * concurrent mints and create N `DelegatedToken` rows server-side.
 */

async function requestToken() {
  // openapi-fetch CONSUMES the body to build `data` and never clones, so
  // calling `response.json()` here throws "body stream already read" on every
  // call — the defect fixed in #749. Use the parsed `data`.
  const { data, error, response } = await apiClient.POST("/api/canopy/token", {});
  if (!response.ok || error || !data) {
    throw new Error(`Failed to fetch canopy token: ${response.status}`);
  }
  const body = data as unknown as { token: string; expires_at: string; kind?: string };
  // The package's contract is `expiresAt`; ace's endpoint says `expires_at`.
  // A non-parseable value is treated as already-expired by the store rather
  // than cached as NaN.
  // `kind` says WHICH principal canopy resolved this person to — their own
  // canopy account, or a contact. ace-web does not decide it and must not
  // guess: the same signed assertion yields a user at a domain the site may
  // resolve and a contact everywhere else, and the two reach different
  // surfaces. Anything unrecognised is treated as a user by the package,
  // which is the narrower read (a contact's routes would 403 loudly).
  return {
    token: body.token,
    expiresAt: body.expires_at,
    kind: body.kind === "contact" ? ("contact" as const) : ("user" as const),
  };
}

const store = createTokenStore(requestToken);

/**
 * Cached delegated token, refetching shortly before expiry.
 *
 * `force` bypasses the cache outright: the retry-once-on-401 path uses it when
 * canopy has already rejected a token, regardless of what our own TTL
 * bookkeeping thinks (it may have been revoked early, or the clocks may
 * disagree); `CanopyChatPanel` uses it — rate-limited — after a reconnect, so a
 * revoked-but-unexpired token cannot wedge the socket in a permanent loop.
 */
export function getCanopyToken(force = false): Promise<string> {
  return store.get(force);
}

/** Sync read for callers that cannot await — the WS URL builder, which has to
 *  put the token in a query string. `null` before the first mint. */
export function peekCanopyToken(): string | null {
  return store.peek();
}

/** Who the cached token is for. `user` until a mint says otherwise — so a
 *  caller that asks before the first mint gets the same answer the package's
 *  own store gives, rather than a third state nothing handles. */
export function canopyPrincipal(): "user" | "contact" {
  return store.principal();
}

/** Drop the cached token. For a sign-out or an account switch. */
export function clearCanopyToken(): void {
  store.clear();
}
