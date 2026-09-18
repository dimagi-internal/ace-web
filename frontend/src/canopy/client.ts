import { createRest, type CanopyRest, type TokenStore } from "canopy-client";

import { clearCanopyToken, getCanopyToken, peekCanopyToken } from "./token";

/**
 * Browser → canopy-web transport, from `canopy-client`.
 *
 * `canopy-client` IS ace-web's old `canopy/{token,api,ws}.ts` — canopy-web
 * extracted the package from these files, and its module headers still cite the
 * bugs found here (`SessionOut` has no `updated_at`, it is `last_activity_at`;
 * `Runner.live_status` values are lowercase, where comparing against the Python
 * constant's NAME made every runner look offline and mis-fired the placement
 * banner on every chat). Adopting it back ends a duplication that persisted
 * only because the package could not be published under its original
 * `@canopy/*` name — a scope that turned out to belong to somebody else.
 *
 * **Primitives, not the bundled `createCanopyClient`.** That wrapper exposes
 * only `invalidateToken()` and `sessionSocketUrl()`, and ace-web needs the
 * token store's `get(force)` directly: `CanopyChatPanel` rate-limits FORCED
 * refreshes on the reconnect path, because the kit's reconnect ladder bottoms
 * out at 1s and a flapping socket would otherwise mint a fresh `DelegatedToken`
 * row roughly once a second per open tab. That logic took two review rounds to
 * get right and is not worth rewriting against a narrower API.
 * `createTokenStore` / `createRest` / `buildSessionWsUrl` are all exported for
 * exactly this reason.
 *
 * **What deliberately does NOT come from the package**, and must not:
 *
 *  - `createCanopySession` — it calls ACE-WEB's own workspace-scoped endpoint,
 *    because `origin_key` is stamped server-side from a membership-checked path
 *    parameter. A client that could set its own could claim another tenant's
 *    scope. See `apps/canopy/api.py`.
 *  - The harness reads (runners, live runs, turns, turn events) — canopy's
 *    `/api/harness/*` surface, which the package does not model.
 *  - `declareCanopyPageState` — ace-web shipped page state before the package
 *    grew a call for it.
 *
 * All of those ride on `rest.json` / `rest.raw`, so they still get the shared
 * bearer + retry-once-on-401 machinery without the package needing to know what
 * an opp is.
 */

/**
 * `origin_key` this ace workspace stamps on (and filters by) every canopy
 * session it creates — must match `apps/canopy/api.py`'s server-side derivation
 * (`f"ace-web:{workspace_slug}"`) EXACTLY, since it is how canopy scopes the
 * session LIST to one ace workspace instead of every ace workspace sharing the
 * same canopy tenant. Never sent on a create: the server derives it from a
 * membership-checked path parameter, and a client that could set its own could
 * stamp another workspace's key and read its chats.
 */
export function aceOriginKey(workspaceSlug: string): string {
  return `ace-web:${workspaceSlug}`;
}

/**
 * The package's `TokenStore`, backed by ace-web's own token module rather than
 * by a store built here.
 *
 * Deliberate indirection, for one reason worth stating: `token.ts` is ace-web's
 * single answer to "what bearer are we using", and routing every request's
 * bearer through the same exported functions the rest of the app calls keeps it
 * that way. A second store built inline here would be a second cache, minting
 * its own `DelegatedToken` rows alongside the first.
 */
const tokens: TokenStore = {
  // `force` is forwarded only when the package actually asks for it, rather
  // than passed through as `undefined`. Same behaviour either way — the
  // parameter defaults to `false` — but it keeps the call ARITY identical to
  // what every caller of `getCanopyToken` has always produced, so the existing
  // "first attempt does not force, the 401 retry does" test still reads the
  // thing it was written to read.
  get: (force) => (force ? getCanopyToken(true) : getCanopyToken()),
  peek: () => peekCanopyToken(),
  clear: () => clearCanopyToken(),
};

/**
 * One `rest` per canopy base, all sharing the token store above.
 *
 * `base` comes from `GET /api/canopy/status`, so it is not known at module load
 * and cannot be a constant. It is effectively fixed for a session; the map just
 * avoids rebuilding the closure on every call.
 *
 * `originKey`/`source` are deliberately NOT configured here even though the
 * package supports them: ace-web's session list also filters by
 * `opp_slug`/`opp_run_id`, so `api.ts` builds one query string with every
 * filter together rather than splitting them across two mechanisms.
 */
const rests = new Map<string, CanopyRest>();

export function canopyRest(base: string): CanopyRest {
  let rest = rests.get(base);
  if (!rest) {
    rest = createRest({ baseUrl: base, tokens });
    rests.set(base, rest);
  }
  return rest;
}
