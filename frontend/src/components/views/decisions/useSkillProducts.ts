import { useEffect, useState } from "react";

const ENDPOINT = "/api/system/skill-products";

/** Cached, app-lifetime memoized fetch of the skill→products map. */
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
