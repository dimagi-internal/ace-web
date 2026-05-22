import { useEffect, useState } from "react";

import { apiFetch } from "@/api/client";

/** Cached, app-lifetime memoized fetch of the skill→products map.
 *
 * Uses `apiFetch` so the request runs through `buildUrl()` which
 * prepends `import.meta.env.BASE_URL` — that's `/ace/` on labs and
 * `/` in local dev. A raw `fetch("/api/...")` works locally but 404s
 * on labs because it lacks the `/ace/` prefix. */
let cachedPromise: Promise<Record<string, string[]>> | null = null;

function fetchSkillProducts(): Promise<Record<string, string[]>> {
  if (!cachedPromise) {
    cachedPromise = apiFetch<Record<string, string[]>>(
      "/api/system/skill-products",
    );
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
