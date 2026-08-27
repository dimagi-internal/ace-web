import { useSearchParams } from "react-router-dom";
import type { ViewKind } from "../components/views/ViewSwitcher";

const VALID: readonly ViewKind[] = [
  "hierarchy",
  "timeline",
  "workbench",
  "phase",
  "story",
  "runs",
] as const;

/**
 * URL-state-driven tab selection, generic over the tab key.
 *
 * Replace-history on change so the back button navigates between
 * filters, not between tabs (matches Notion / Linear UX). Selecting the
 * default tab drops the param entirely, which keeps the canonical URL —
 * the one a partner is handed — clean.
 */
export function useUrlTab<K extends string>({
  param,
  valid,
  defaultTab,
}: {
  param: string;
  valid: readonly K[];
  defaultTab: K;
}): { tab: K; setTab: (k: K) => void } {
  const [params, setParams] = useSearchParams();
  const raw = params.get(param);
  const tab = raw && (valid as readonly string[]).includes(raw) ? (raw as K) : defaultTab;
  const setTab = (k: K) => {
    const next = new URLSearchParams(params);
    if (k === defaultTab) {
      next.delete(param);
    } else {
      next.set(param, k);
    }
    setParams(next, { replace: true });
  };
  return { tab, setTab };
}

/**
 * The Workbench's view mode. Lives in `?view=`. Default is whichever
 * the caller declares per surface (Hierarchy on /opps; Flow on
 * /opps/<slug> when the run-graph endpoint ships).
 */
export function useViewMode(defaultView: ViewKind = "hierarchy") {
  const { tab, setTab } = useUrlTab<ViewKind>({
    param: "view",
    valid: VALID,
    defaultTab: defaultView,
  });
  return { view: tab, setView: setTab };
}
