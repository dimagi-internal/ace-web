import type { RouteRule } from "canopy-ui/presence";

/**
 * The workspace segment for pages that belong to no workspace.
 *
 * The leading `~` is load-bearing and is a CROSS-APP CONTRACT with the
 * backend (`apps/presence/keys.py::GLOBAL_SENTINEL`) and with canopy-web:
 * `WORKSPACE_RE` cannot match it, so no real workspace slug can collide
 * with the sentinel and thereby skip the membership gate. Changing it here
 * without changing both backends silently kills the badge on `/settings`
 * and `/system`.
 */
const GLOBAL = "~global";

/**
 * Decode a URL path segment without ever throwing.
 *
 * `decodeURIComponent` raises `URIError: URI malformed` on a bare or
 * truncated percent escape (`/steps/100%`). This runs during render, in a
 * component mounted ABOVE the router's `<Outlet/>`, in an SPA with no error
 * boundary — so an unguarded decode turns a mistyped URL into a blank white
 * screen with no navigation to escape it, instead of the page's own "step
 * not found". Presence must never break a page: fall back to the raw
 * segment, which is only ever used as a human-readable sub-location label.
 */
function safeDecode(segment: string): string {
  try {
    return decodeURIComponent(segment);
  } catch {
    return segment;
  }
}

/**
 * ace-web's route table for presence grouping.
 *
 * Order matters — the first match wins, so the most specific patterns come
 * first. Every step of a run deliberately collapses onto the run's key: the
 * whole point is that two people working the same run find each other even
 * when they are on different steps.
 *
 * Routes with no rule (invite acceptance, the public run-summary page, auth
 * callbacks, the legacy `/chat/:slug` redirect) get no badge, which is the
 * correct default for pages where a viewer list would be meaningless or
 * unwelcome.
 *
 * Verified against `frontend/src/router.tsx` — every workspace-scoped path
 * declared there has a matching rule below (or is a redirect/legacy shape
 * deliberately left unmatched).
 */
export const acePresenceRules: RouteRule[] = [
  // Opps ----------------------------------------------------------------
  {
    pattern: /^\/w\/([^/]+)\/opps\/([^/]+)\/runs\/([^/]+)\/steps\/([^/]+)/,
    build: (m) => ({
      workspace: m[1],
      resource: `opp:${m[2]}/${m[3]}`,
      subLocation: safeDecode(m[4]),
    }),
  },
  {
    pattern: /^\/w\/([^/]+)\/opps\/([^/]+)\/runs\/([^/]+)/,
    build: (m) => ({
      workspace: m[1],
      resource: `opp:${m[2]}/${m[3]}`,
      subLocation: "run overview",
    }),
  },
  {
    pattern: /^\/w\/([^/]+)\/opps\/compare\/([^/]+)\/([^/]+)/,
    build: (m) => ({ workspace: m[1], resource: `compare:${m[2]}/${m[3]}`, subLocation: "Compare" }),
  },
  {
    pattern: /^\/w\/([^/]+)\/opps\/([^/]+)/,
    build: (m) => ({ workspace: m[1], resource: `opp:${m[2]}`, subLocation: "Opp" }),
  },
  {
    pattern: /^\/w\/([^/]+)\/opps/,
    build: (m) => ({ workspace: m[1], resource: "opps", subLocation: "Opps" }),
  },

  // Videos ----------------------------------------------------------------
  {
    pattern: /^\/w\/([^/]+)\/videos\/templates\/([^/]+)/,
    build: (m) => ({ workspace: m[1], resource: `template:${m[2]}`, subLocation: "Template" }),
  },
  {
    pattern: /^\/w\/([^/]+)\/videos\/([^/]+)\/runs\/([^/]+)/,
    build: (m) => ({
      workspace: m[1],
      resource: `video:${m[2]}/${m[3]}`,
      subLocation: "Beat editor",
    }),
  },
  {
    // The trailing `(?:\/|$)` anchors the alternation to a whole path
    // segment. Unanchored, a real program slug that merely STARTS with
    // "library"/"templates" (`/w/ws/videos/library-x`) collapses onto the
    // gallery's roster instead of getting its own.
    pattern: /^\/w\/([^/]+)\/videos\/(library|templates)(?:\/|$)/,
    build: (m) => ({ workspace: m[1], resource: `videos-${m[2]}`, subLocation: m[2] }),
  },
  {
    pattern: /^\/w\/([^/]+)\/videos\/([^/]+)/,
    build: (m) => ({ workspace: m[1], resource: `video:${m[2]}`, subLocation: "Program" }),
  },
  {
    pattern: /^\/w\/([^/]+)\/videos/,
    build: (m) => ({ workspace: m[1], resource: "videos", subLocation: "Videos" }),
  },

  // Chat (structure view + canopy-chat redirect page only — the legacy
  // ace-native `/chat/:slug` shape is a redirect with nothing to view, so
  // it's deliberately left unmatched; see module docstring). -------------
  {
    pattern: /^\/w\/([^/]+)\/chat\/([^/]+)\/structure/,
    build: (m) => ({ workspace: m[1], resource: `session:${m[2]}`, subLocation: "Structure" }),
  },
  {
    pattern: /^\/w\/([^/]+)\/chat\/c\/([^/]+)/,
    build: (m) => ({ workspace: m[1], resource: `chat:${m[2]}`, subLocation: "Chat" }),
  },

  // Workspace-scoped list/utility pages ------------------------------------
  {
    pattern: /^\/w\/([^/]+)\/activity/,
    build: (m) => ({ workspace: m[1], resource: "activity", subLocation: "Activity" }),
  },
  {
    pattern: /^\/w\/([^/]+)\/sessions/,
    build: (m) => ({ workspace: m[1], resource: "sessions", subLocation: "Sessions" }),
  },
  {
    pattern: /^\/w\/([^/]+)\/workspace-settings/,
    build: (m) => ({
      workspace: m[1],
      resource: "workspace-settings",
      subLocation: "Workspace settings",
    }),
  },

  // Workspace-agnostic (global) pages --------------------------------------
  {
    pattern: /^\/settings/,
    build: () => ({ workspace: GLOBAL, resource: "settings", subLocation: "Settings" }),
  },
  {
    pattern: /^\/system/,
    build: () => ({ workspace: GLOBAL, resource: "system", subLocation: "System" }),
  },
];
