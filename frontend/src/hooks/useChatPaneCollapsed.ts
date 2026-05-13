import { useCallback, useEffect, useState } from "react";

// localStorage key for the per-browser "viewer mode" preference: hide
// the right-hand chat pane on the Opp Workbench so the StepDetailPane
// gets the full remaining width. Read-mostly usage of /opps/<slug>
// rarely needs the chat affordance and the pane is permanent dead
// space when collapsed.
const STORAGE_KEY = "ace.workbench.chatPaneCollapsed";

function readInitial(): boolean {
  if (typeof window === "undefined") return false;
  try {
    return window.localStorage.getItem(STORAGE_KEY) === "1";
  } catch {
    return false;
  }
}

export function useChatPaneCollapsed(): {
  collapsed: boolean;
  toggle: () => void;
  setCollapsed: (v: boolean) => void;
} {
  const [collapsed, setCollapsed] = useState<boolean>(readInitial);

  useEffect(() => {
    try {
      window.localStorage.setItem(STORAGE_KEY, collapsed ? "1" : "0");
    } catch {
      // Private mode / disabled storage — preference becomes per-tab only.
    }
  }, [collapsed]);

  const toggle = useCallback(() => setCollapsed((c) => !c), []);

  return { collapsed, toggle, setCollapsed };
}
