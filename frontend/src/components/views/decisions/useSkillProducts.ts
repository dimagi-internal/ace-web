import { useEffect, useState } from "react";

/** Cached, app-lifetime memoized fetch of the skill→products map.
 *
 * Prefix the URL with `import.meta.env.BASE_URL` (= `/ace/` on labs,
 * `/` in local dev). A raw `fetch("/api/...")` works locally but 404s
 * on labs because it lacks the `/ace/` prefix. We deliberately *don't*
 * route through the project's `apiFetch` helper — that one expects the
 * legacy `{data, error}` response envelope, which Ninja endpoints don't
 * use anymore (per the PR #352 cleanup). This endpoint returns a bare
 * `{[skill]: [path, ...]}` object. */
const BASE = (import.meta.env.BASE_URL ?? "/").replace(/\/$/, "");
const ENDPOINT = `${BASE}/api/system/skill-products`;

let cachedPromise: Promise<Record<string, string[]>> | null = null;

function fetchSkillProducts(): Promise<Record<string, string[]>> {
  if (!cachedPromise) {
    cachedPromise = fetch(ENDPOINT, { credentials: "include" }).then(async (r) => {
      if (!r.ok) throw new Error(`skill-products fetch failed: ${r.status}`);
      return (await r.json()) as Record<string, string[]>;
    });
  }
  return cachedPromise;
}

export function useSkillProducts(): Record<string, string[]> | null {
  const [data, setData] = useState<Record<string, string[]> | null>(null);
  useEffect(() => {
    let cancelled = false;
    fetchSkillProducts()
      .then((m) => {
        if (!cancelled) setData(m);
      })
      .catch((e) => {
        console.warn("useSkillProducts: load failed", e);
        if (!cancelled) setData({});
      });
    return () => {
      cancelled = true;
    };
  }, []);
  return data;
}

/** Test seam: reset the module cache between tests. */
export function _resetSkillProductsCache(): void {
  cachedPromise = null;
}
