import { Navigate, useLocation, useParams } from "react-router-dom";

import { useWorkspace } from "../hooks/useWorkspace";

/**
 * Redirects a legacy bare path like `/opps`, `/sessions`, or
 * `/chat/<slug>` to `/w/<defaultSlug>/<subPath>` for the user's
 * most-recent (or only) workspace. Sends users with zero memberships
 * to `/welcome`.
 *
 * `subPath` may include a `:slug` placeholder which is filled from
 * the current `useParams` (used by `/opps/:slug` and `/chat/:slug`).
 */
export function NoWorkspaceRedirect({ subPath }: { subPath: string }) {
  const { all, loading } = useWorkspace();
  const params = useParams();
  const location = useLocation();

  if (loading) return null;
  if (all.length === 0) return <Navigate to="/welcome" replace />;

  let resolvedSubPath = subPath;
  if (resolvedSubPath.includes(":slug") && params.slug) {
    resolvedSubPath = resolvedSubPath.replace(":slug", params.slug);
  }
  const target = `/w/${all[0].slug}/${resolvedSubPath}${location.search}`;
  return <Navigate to={target} replace />;
}
