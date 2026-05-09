import { useSearchParams } from "react-router-dom";
import type { ViewKind } from "../components/views/ViewSwitcher";

const VALID: readonly ViewKind[] = [
  "hierarchy",
  "timeline",
  "workbench",
  "phase",
  "heatmap",
  "diff",
  "story",
] as const;

function parse(raw: string | null, fallback: ViewKind): ViewKind {
  if (raw && (VALID as readonly string[]).includes(raw)) return raw as ViewKind;
  return fallback;
}

/**
 * URL-state-driven view mode. Lives in `?view=`. Default is whichever
 * the caller declares per surface (Hierarchy on /opps; Flow on
 * /opps/<slug> when the run-graph endpoint ships).
 *
 * Replace-history on change so back-button navigates between filters,
 * not between view tabs (matches Notion / Linear UX).
 */
export function useViewMode(defaultView: ViewKind = "hierarchy") {
  const [params, setParams] = useSearchParams();
  const current = parse(params.get("view"), defaultView);
  const setView = (k: ViewKind) => {
    const next = new URLSearchParams(params);
    if (k === defaultView) {
      next.delete("view");
    } else {
      next.set("view", k);
    }
    setParams(next, { replace: true });
  };
  return { view: current, setView };
}
