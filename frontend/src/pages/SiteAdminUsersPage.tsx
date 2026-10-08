import { useCallback, useEffect, useState } from "react";

import {
  listSiteAdminUsers,
  setUserStaff,
  type SiteAdminUser,
  type SiteAdminUsers,
} from "@/api/siteAdmin";
import { EmptyState, ErrorState, LoadingSpinner } from "@/components/opps/LoadingStates";
import { Badge, Button } from "canopy-ui/ui";

function fmt(iso: string | null | undefined): string {
  return iso ? new Date(iso).toLocaleString() : "—";
}

/**
 * Site admin → Users: who holds site admin (`User.is_staff`). Staff only — the
 * API answers anyone else with 404, which renders as "not found" here rather
 * than as a permissions page that admits the surface exists.
 */
export default function SiteAdminUsersPage() {
  const [query, setQuery] = useState("");
  const [data, setData] = useState<SiteAdminUsers | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState<SiteAdminUser | null>(null);
  const [busy, setBusy] = useState(false);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    let cancelled = false;
    // Debounce the search box; the first load runs immediately.
    const t = setTimeout(
      () => {
        listSiteAdminUsers(query.trim())
          .then((d) => {
            if (cancelled) return;
            setData(d);
            setLoadError(null);
          })
          .catch((e) => !cancelled && setLoadError(String((e as Error).message)));
      },
      data ? 250 : 0,
    );
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
    // `data` only picks the debounce; it must not retrigger the fetch.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query, reload]);

  const apply = useCallback(async () => {
    if (!confirming) return;
    setBusy(true);
    setActionError(null);
    try {
      await setUserStaff(confirming.id, !confirming.is_staff);
      setReload((n) => n + 1);
    } catch (e) {
      setActionError(String((e as Error).message));
    } finally {
      setConfirming(null);
      setBusy(false);
    }
  }, [confirming]);

  if (loadError && !data) {
    // The API 404s a non-staff caller; don't confirm the page exists.
    if (/not found/i.test(loadError)) {
      return <EmptyState title="Page not found" description="There is nothing at this address." />;
    }
    return <ErrorState message={loadError} code={null} onRetry={() => setReload((n) => n + 1)} />;
  }
  if (!data) return <LoadingSpinner label="Loading users…" />;

  return (
    <div className="mx-auto max-w-6xl p-6 text-foreground">
      <h1 className="text-xl font-semibold">Site admin · Users</h1>
      <p className="mt-1 text-sm text-muted-foreground">
        Site admins can use Django admin and other site-wide tools. This is separate from a
        person&apos;s role in a workspace.
      </p>

      <input
        type="search"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="Search by email or name"
        aria-label="Search users"
        className="mt-4 w-full max-w-sm rounded border border-input bg-background px-3 py-1.5 text-sm"
      />

      {actionError && (
        <p role="alert" className="mt-3 text-sm text-destructive">
          {actionError}
        </p>
      )}

      {confirming && (
        <div
          role="alertdialog"
          aria-label="Confirm site admin change"
          className="mt-3 flex flex-wrap items-center gap-3 rounded border border-border bg-card p-3 text-sm"
        >
          <span>
            {confirming.is_staff ? "Remove site admin from" : "Make"}{" "}
            <strong>{confirming.display_name || confirming.email}</strong> ({confirming.email})
            {confirming.is_staff ? "?" : " a site admin?"}
          </span>
          <Button size="sm" disabled={busy} onClick={apply}>
            {confirming.is_staff ? "Remove admin" : "Make admin"}
          </Button>
          <Button size="sm" variant="outline" disabled={busy} onClick={() => setConfirming(null)}>
            Cancel
          </Button>
        </div>
      )}

      <table className="mt-4 w-full text-sm">
        <thead>
          <tr className="border-b border-border text-left text-muted-foreground">
            <th className="py-2">Email</th>
            <th className="py-2">Name</th>
            <th className="py-2">Staff</th>
            <th className="py-2">Active</th>
            <th className="py-2">Created</th>
            <th className="py-2">Last login</th>
            <th className="py-2">Workspaces</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {data.users.map((u) => (
            <tr key={u.id} className="border-b border-border align-top">
              <td className="py-2">{u.email}</td>
              <td className="py-2 text-muted-foreground">{u.display_name}</td>
              <td className="py-2">{u.is_staff ? <Badge>Admin</Badge> : "—"}</td>
              <td className="py-2 text-muted-foreground">{u.is_active ? "Yes" : "No"}</td>
              <td className="py-2 text-muted-foreground">{fmt(u.created_at)}</td>
              <td className="py-2 text-muted-foreground">{fmt(u.last_login)}</td>
              <td className="py-2 text-muted-foreground">
                {u.workspaces.length === 0
                  ? "—"
                  : u.workspaces.map((w) => `${w.workspace_name} (${w.role})`).join(", ")}
              </td>
              <td className="py-2 text-right">
                <Button
                  size="sm"
                  variant="outline"
                  aria-label={`${u.is_staff ? "Remove admin from" : "Make admin"} ${u.email}`}
                  onClick={() => {
                    setActionError(null);
                    setConfirming(u);
                  }}
                >
                  {u.is_staff ? "Remove admin" : "Make admin"}
                </Button>
              </td>
            </tr>
          ))}
          {data.users.length === 0 && (
            <tr>
              <td colSpan={8} className="py-4 text-muted-foreground">
                No users match.
              </td>
            </tr>
          )}
        </tbody>
      </table>

      <h2 className="mt-8 text-lg font-medium">Recent changes</h2>
      {data.recent_changes.length === 0 ? (
        <p className="mt-2 text-sm text-muted-foreground">No site admin changes yet.</p>
      ) : (
        <ul className="mt-2 space-y-1 text-sm">
          {data.recent_changes.map((c) => (
            <li key={c.id}>
              <span className="text-muted-foreground">{fmt(c.created_at)}</span>{" "}
              {c.changed_by_email || "Sign-in bootstrap"}{" "}
              {c.new_is_staff ? "made" : "removed"} <strong>{c.target_email}</strong>{" "}
              {c.new_is_staff ? "a site admin" : "as a site admin"}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
