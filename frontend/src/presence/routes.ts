import type { RouteRule } from "canopy-ui/presence";

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
      subLocation: decodeURIComponent(m[4]),
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
    pattern: /^\/w\/([^/]+)\/videos\/(library|templates)/,
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
    build: () => ({ workspace: "global", resource: "settings", subLocation: "Settings" }),
  },
  {
    pattern: /^\/system/,
    build: () => ({ workspace: "global", resource: "system", subLocation: "System" }),
  },
];
