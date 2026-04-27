import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";

import { listWorkspaces, type WorkspaceSummary } from "../api/workspaces";

export interface WorkspaceContext {
  current: WorkspaceSummary | null;
  all: WorkspaceSummary[];
  loading: boolean;
  error: string | null;
  reload: () => void;
}

/**
 * Resolves the active workspace from the URL kwarg `:workspaceSlug`
 * (set by the router for any path under `/w/:workspaceSlug/...`) and
 * fetches the user's full membership list once.
 *
 * Returns `current=null` when the URL has no workspace context — e.g.
 * /welcome, /settings, /share/<token>. Pages that require a workspace
 * should redirect to /welcome when `current` is null AND `all` is empty.
 */
export function useWorkspace(): WorkspaceContext {
  const { workspaceSlug } = useParams<{ workspaceSlug?: string }>();
  const [all, setAll] = useState<WorkspaceSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadCounter, setReloadCounter] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    listWorkspaces()
      .then((ws) => {
        if (!cancelled) {
          setAll(ws);
          setError(null);
        }
      })
      .catch((e) => {
        if (!cancelled) setError(String(e?.message ?? e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [reloadCounter]);

  const current = workspaceSlug
    ? all.find((w) => w.slug === workspaceSlug) ?? null
    : null;

  return {
    current,
    all,
    loading,
    error,
    reload: () => setReloadCounter((n) => n + 1),
  };
}
