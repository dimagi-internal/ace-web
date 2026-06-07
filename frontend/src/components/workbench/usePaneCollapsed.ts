import { useCallback, useEffect, useState } from "react";

/**
 * localStorage-persisted collapse state for a workbench pane, keyed per
 * pane so multiple rails on one page don't collide. Generalized from
 * hooks/useChatPaneCollapsed.ts. Falls back to per-tab state when storage
 * is unavailable (private mode).
 */
export function usePaneCollapsed(
  storageKey: string,
  defaultCollapsed = false,
): { collapsed: boolean; toggle: () => void; setCollapsed: (v: boolean) => void } {
  const [collapsed, setCollapsed] = useState<boolean>(() => {
    if (typeof window === "undefined") return defaultCollapsed;
    try {
      const raw = window.localStorage.getItem(storageKey);
      if (raw === null) return defaultCollapsed;
      return raw === "1";
    } catch {
      return defaultCollapsed;
    }
  });

  useEffect(() => {
    try {
      window.localStorage.setItem(storageKey, collapsed ? "1" : "0");
    } catch {
      // storage disabled — preference is per-tab only
    }
  }, [storageKey, collapsed]);

  const toggle = useCallback(() => setCollapsed((c) => !c), []);

  return { collapsed, toggle, setCollapsed };
}
