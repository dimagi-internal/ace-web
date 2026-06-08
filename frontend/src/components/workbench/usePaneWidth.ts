import { useCallback, useEffect, useState } from "react";

/**
 * localStorage-persisted width (px) for a resizable workbench rail, keyed
 * per pane. Pair with WorkbenchRail's `resizable` + `onResize` to make a
 * rail drag-to-resize. Falls back to per-tab state when storage is
 * unavailable (private mode).
 */
export function usePaneWidth(
  storageKey: string,
  defaultWidth: number,
): { width: number; setWidth: (w: number) => void } {
  const [width, setWidthState] = useState<number>(() => {
    if (typeof window === "undefined") return defaultWidth;
    try {
      const raw = window.localStorage.getItem(storageKey);
      const n = raw == null ? NaN : Number(raw);
      return Number.isFinite(n) && n > 0 ? n : defaultWidth;
    } catch {
      return defaultWidth;
    }
  });

  useEffect(() => {
    try {
      window.localStorage.setItem(storageKey, String(Math.round(width)));
    } catch {
      // storage disabled — width is per-tab only
    }
  }, [storageKey, width]);

  const setWidth = useCallback((w: number) => setWidthState(w), []);

  return { width, setWidth };
}
