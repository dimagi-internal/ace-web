/**
 * Feature flags + public settings exposed from Django.
 *
 * Source of truth: GET /api/settings (apps/common/api.py::public_settings).
 * The endpoint returns a small allowlisted dict of flags; we fetch it once
 * on first read and cache the promise so multiple consumers share one
 * network round-trip.
 *
 * Usage:
 *   import { useFeatures, featureBeatEditorReact } from "@/lib/features";
 *
 *   // Inside a React component:
 *   const features = useFeatures();
 *   if (features?.ACE_VIDEO_BEAT_EDITOR_REACT) { ... }
 *
 *   // Synchronous read (returns false until features have loaded):
 *   if (featureBeatEditorReact()) { ... }
 */
import { useEffect, useState } from "react";

export interface PublicFeatures {
  ACE_VIDEO_BEAT_EDITOR_REACT: boolean;
}

const DEFAULT_FEATURES: PublicFeatures = {
  ACE_VIDEO_BEAT_EDITOR_REACT: false,
};

let cached: PublicFeatures | null = null;
let inflight: Promise<PublicFeatures> | null = null;

function settingsUrl(): string {
  // BASE_URL is `/ace/` on labs and `/` in local dev; mirrors the prefix that
  // every other client in this codebase uses (see frontend/src/api/videos.ts).
  const base = (import.meta.env.BASE_URL ?? "/").replace(/\/$/, "");
  return `${base}/api/settings`;
}

export function loadFeatures(): Promise<PublicFeatures> {
  if (cached) return Promise.resolve(cached);
  if (inflight) return inflight;
  inflight = fetch(settingsUrl(), {
    credentials: "same-origin",
    headers: { Accept: "application/json" },
  })
    .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`settings ${r.status}`))))
    .then((data: Partial<PublicFeatures>) => {
      cached = { ...DEFAULT_FEATURES, ...data };
      return cached;
    })
    .catch(() => {
      // Network failures should not break the SPA — fall back to defaults
      // (everything off). The user will see the legacy iframe path until
      // settings are reachable again.
      cached = DEFAULT_FEATURES;
      return cached;
    })
    .finally(() => {
      inflight = null;
    });
  return inflight;
}

/**
 * React hook that returns the loaded features, or `null` while loading.
 * Components that need to gate UI on a flag should treat `null` as "not yet
 * known" and render the safe/default branch.
 */
export function useFeatures(): PublicFeatures | null {
  const [features, setFeatures] = useState<PublicFeatures | null>(cached);
  useEffect(() => {
    if (cached) {
      setFeatures(cached);
      return;
    }
    let live = true;
    loadFeatures().then((f) => {
      if (live) setFeatures(f);
    });
    return () => {
      live = false;
    };
  }, []);
  return features;
}

/** Synchronous accessor — returns false until the first fetch resolves. */
export function featureBeatEditorReact(): boolean {
  return Boolean(cached?.ACE_VIDEO_BEAT_EDITOR_REACT);
}

/** Test-only: reset the module-level cache between tests. */
export function _resetFeaturesCacheForTests(): void {
  cached = null;
  inflight = null;
}
