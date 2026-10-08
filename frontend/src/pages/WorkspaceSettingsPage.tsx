import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";

import {
  changeMemberRole,
  getDriveConfig,
  getWorkspace,
  inviteMember,
  leaveWorkspace,
  listActivity,
  listMembers,
  listPendingInvites,
  removeMember,
  updateWorkspace,
  verifyDriveAccess,
  type ActivityRow,
  type PendingInvite,
  type WorkspaceDetail,
  type WorkspaceMember,
  type WorkspaceRole,
} from "../api/workspaces";
import { Button } from "canopy-ui/ui";
import { useNavigate } from "react-router-dom";
import { DefaultTenancyPanel, type Tenancy } from "@/components/workspaces/DefaultTenancyPanel";
import {
  ROLE_DESCRIPTIONS,
  ROLE_LABELS,
  WORKSPACE_ROLES,
  assignableRoles,
  mayManage,
  roleAllows,
} from "@/lib/workspaceRoles";

/** A role `<select>`: Owner / Admin / Editor / Viewer, limited to `options`. */
export function RolePicker({
  value,
  options,
  onChange,
  label,
  className,
}: {
  value: WorkspaceRole;
  options: readonly WorkspaceRole[];
  onChange: (role: WorkspaceRole) => void;
  label: string;
  className?: string;
}) {
  // The current value is always listed, even when the picker could not grant
  // it, so a row never silently displays the wrong role.
  const shown = WORKSPACE_ROLES.filter((r) => r === value || options.includes(r));
  return (
    <select
      aria-label={label}
      value={value}
      onChange={(e) => onChange(e.target.value as WorkspaceRole)}
      className={className}
    >
      {shown.map((r) => (
        <option key={r} value={r} disabled={!options.includes(r)} title={ROLE_DESCRIPTIONS[r]}>
          {ROLE_LABELS[r]}
        </option>
      ))}
    </select>
  );
}

export default function WorkspaceSettingsPage() {
  const { workspaceSlug } = useParams<{ workspaceSlug: string }>();
  const navigate = useNavigate();
  const [ws, setWs] = useState<WorkspaceDetail | null>(null);
  const [members, setMembers] = useState<WorkspaceMember[]>([]);
  const [saEmail, setSaEmail] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState<WorkspaceRole>("editor");
  const [inviteResult, setInviteResult] = useState<{
    accept_url: string;
    token: string;
  } | null>(null);
  const [verifyMsg, setVerifyMsg] = useState<string | null>(null);
  const [driveBroken, setDriveBroken] = useState<string | null>(null);
  const [activity, setActivity] = useState<ActivityRow[]>([]);
  const [pendingInvites, setPendingInvites] = useState<PendingInvite[]>([]);
  const [domainsInput, setDomainsInput] = useState("");
  const [domainsMsg, setDomainsMsg] = useState<string | null>(null);
  const [domainsSaving, setDomainsSaving] = useState(false);

  useEffect(() => {
    if (!workspaceSlug) return;
    getWorkspace(workspaceSlug).then(setWs).catch((e) => setError(String((e as Error).message)));
    listMembers(workspaceSlug).then(setMembers).catch(() => {});
    getDriveConfig().then((c) => setSaEmail(c.service_account_email)).catch(() => {});
    // Auto-verify on page load to surface drive-access-broken state.
    verifyDriveAccess(workspaceSlug)
      .then(() => setDriveBroken(null))
      .catch((e) => setDriveBroken(String((e as Error).message)));
  }, [workspaceSlug, reload]);

  useEffect(() => {
    if (!workspaceSlug || !ws) return;
    if (roleAllows(ws.role, "logs.read")) {
      listActivity(workspaceSlug).then(setActivity).catch(() => {});
    }
    if (roleAllows(ws.role, "members.manage")) {
      listPendingInvites(workspaceSlug).then(setPendingInvites).catch(() => {});
    }
  }, [workspaceSlug, ws, reload]);

  useEffect(() => {
    setDomainsInput((ws?.auto_join_domains ?? []).join(", "));
    setDomainsMsg(null);
  }, [ws?.slug, ws?.auto_join_domains?.join(",")]);

  if (!workspaceSlug) return null;
  if (error) return <div className="p-6 text-destructive">{error}</div>;
  if (!ws) return <div className="p-6 text-muted-foreground">Loading…</div>;

  const myRole = ws.role;
  // What the UI OFFERS — the server decides (apps/workspaces/permissions.py).
  const isOwner = roleAllows(myRole, "own");
  const canManageMembers = roleAllows(myRole, "members.manage");
  const canReadLogs = roleAllows(myRole, "logs.read");
  const grantable = assignableRoles(myRole);

  async function handleInvite() {
    setError(null);
    setInviteResult(null);
    try {
      const r = await inviteMember(workspaceSlug!, {
        email: inviteEmail.trim(),
        role: inviteRole,
      });
      setInviteResult({ accept_url: r.accept_url, token: r.token });
      setInviteEmail("");
      setReload((n) => n + 1);
    } catch (e) {
      setError(String((e as Error).message));
    }
  }

  async function handleRemove(userEmail: string, userId: number) {
    if (!confirm(`Remove ${userEmail} from this workspace?`)) return;
    setError(null);
    try {
      await removeMember(workspaceSlug!, userId);
      setReload((n) => n + 1);
    } catch (e) {
      setError(String((e as Error).message));
    }
  }

  async function handleRoleChange(userId: number, role: WorkspaceRole) {
    setError(null);
    try {
      await changeMemberRole(workspaceSlug!, userId, role);
      setReload((n) => n + 1);
    } catch (e) {
      setError(String((e as Error).message));
    }
  }

  async function handleVerify() {
    setVerifyMsg("Verifying…");
    try {
      const r = await verifyDriveAccess(workspaceSlug!);
      setVerifyMsg(`OK — ${r.total_visible} files visible at root.`);
    } catch (e) {
      setVerifyMsg(String((e as Error).message));
    }
  }

  async function handleSaveDomains() {
    setDomainsMsg(null);
    setDomainsSaving(true);
    try {
      const domains = domainsInput
        .split(/[,\s]+/)
        .map((d) => d.trim().toLowerCase().replace(/^@/, ""))
        .filter(Boolean);
      const updated = await updateWorkspace(workspaceSlug!, {
        auto_join_domains: domains,
      });
      setWs(updated);
      setDomainsMsg(
        domains.length
          ? `Saved. ${domains.length} domain${domains.length === 1 ? "" : "s"} auto-join.`
          : "Saved. Auto-join disabled.",
      );
    } catch (e) {
      setDomainsMsg(String((e as Error).message));
    } finally {
      setDomainsSaving(false);
    }
  }

  async function handleLeave() {
    if (!ws) return;
    if (!confirm(`Leave the workspace "${ws.name}"?`)) return;
    setError(null);
    try {
      await leaveWorkspace(workspaceSlug!);
      navigate("/welcome");
    } catch (e) {
      setError(String((e as Error).message));
    }
  }

  return (
    <div className="mx-auto max-w-3xl px-6 py-8">
      <h1 className="text-2xl font-semibold text-foreground">{ws.name}</h1>
      <p className="text-sm text-muted-foreground">/{ws.slug}</p>

      {driveBroken && (
        <div className="mt-4 rounded border border-destructive bg-destructive/10 p-3 text-sm text-destructive">
          <strong>Drive access broken:</strong> {driveBroken}
          <p className="mt-1 text-xs">
            Re-share the folder with{" "}
            <span className="font-mono">{saEmail}</span> as Editor, then click
            "Verify Drive access" below.
          </p>
        </div>
      )}

      <section className="mt-8">
        <h2 className="text-lg font-medium text-foreground">Drive folder</h2>
        <pre className="mt-2 select-all rounded bg-muted px-3 py-2 text-xs font-mono text-foreground">
          {ws.drive_root_folder_id}
        </pre>
        <p className="mt-2 text-xs text-muted-foreground">
          Shared with: <span className="font-mono">{saEmail || "(loading…)"}</span>
        </p>
        <div className="mt-3">
          <Button variant="outline" onClick={handleVerify}>
            Verify Drive access
          </Button>
          {verifyMsg && (
            <span className="ml-3 text-sm text-foreground">{verifyMsg}</span>
          )}
        </div>
      </section>

      <section className="mt-8">
        <h2 className="text-lg font-medium text-foreground">Members</h2>
        <table className="mt-3 w-full text-sm">
          <thead>
            <tr className="border-b border-border text-left text-muted-foreground">
              <th className="py-2">Email</th>
              <th className="py-2">Name</th>
              <th className="py-2">Role</th>
              <th className="py-2">Joined</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {members.map((m) => (
              <tr key={m.user.email} className="border-b border-border">
                <td className="py-2 text-foreground">{m.user.email}</td>
                <td className="py-2 text-muted-foreground">{m.user.display_name ?? m.user.email}</td>
                <td className="py-2">
                  {canManageMembers && mayManage(myRole, m.role) ? (
                    <RolePicker
                      label={`Role for ${m.user.email}`}
                      value={m.role}
                      options={grantable}
                      onChange={(r) => handleRoleChange(m.user.id, r)}
                      className="rounded border border-input bg-background px-2 py-1 text-xs"
                    />
                  ) : (
                    <span className="text-foreground" title={ROLE_DESCRIPTIONS[m.role]}>
                      {ROLE_LABELS[m.role]}
                    </span>
                  )}
                </td>
                <td className="py-2 text-muted-foreground">
                  {new Date(m.joined_at).toLocaleDateString()}
                </td>
                <td className="py-2 text-right">
                  {canManageMembers && mayManage(myRole, m.role) && m.role !== "owner" && (
                    <button
                      type="button"
                      onClick={() => handleRemove(m.user.email, m.user.id)}
                      className="text-xs text-destructive hover:underline"
                    >
                      Remove
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      {isOwner && (
        <section className="mt-8">
          <h2 className="text-lg font-medium text-foreground">Auto-join domains</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Anyone who signs in with an email at these domains is added as
            Editor automatically. Comma- or space-separated. Leave blank to
            disable.
          </p>
          <div className="mt-3 flex gap-2">
            <input
              type="text"
              placeholder="dimagi.com, dimagi-ai.com"
              value={domainsInput}
              onChange={(e) => setDomainsInput(e.target.value)}
              className="flex-1 rounded border border-input bg-background px-3 py-2 text-sm text-foreground"
            />
            <Button onClick={handleSaveDomains} disabled={domainsSaving}>
              {domainsSaving ? "Saving…" : "Save"}
            </Button>
          </div>
          {domainsMsg && (
            <p className="mt-2 text-sm text-muted-foreground">{domainsMsg}</p>
          )}
        </section>
      )}

      <DefaultTenancyPanel
        tenancy={(ws.default_tenancy ?? {}) as Tenancy}
        canEdit={isOwner}
        onSave={async (patch) => {
          setWs(await updateWorkspace(workspaceSlug!, { default_tenancy: patch }));
        }}
      />

      {canManageMembers && (
        <section className="mt-8">
          <h2 className="text-lg font-medium text-foreground">Invite a teammate</h2>
          <div className="mt-3 flex gap-2">
            <input
              type="email"
              placeholder="email@example.com"
              value={inviteEmail}
              onChange={(e) => setInviteEmail(e.target.value)}
              className="flex-1 rounded border border-input bg-background px-3 py-2 text-sm text-foreground"
            />
            <RolePicker
              label="Role for the invite"
              value={inviteRole}
              options={grantable}
              onChange={setInviteRole}
              className="rounded border border-input bg-background px-2 py-2 text-sm"
            />
            <Button onClick={handleInvite} disabled={!inviteEmail.trim()}>
              Send invite
            </Button>
          </div>
          <p className="mt-2 text-xs text-muted-foreground" data-testid="invite-role-description">
            {ROLE_LABELS[inviteRole]}: {ROLE_DESCRIPTIONS[inviteRole]}
          </p>
          {inviteResult && (
            <div className="mt-3 rounded border border-border bg-muted p-3 text-sm">
              <p className="text-foreground">
                Invite created. Copy this link and send it to the recipient:
              </p>
              <pre className="mt-1 select-all break-all text-xs font-mono">
                {window.location.origin}/ace{inviteResult.accept_url}
              </pre>
            </div>
          )}
        </section>
      )}

      {canManageMembers && pendingInvites.length > 0 && (
        <section className="mt-8">
          <h2 className="text-lg font-medium text-foreground">Pending invites</h2>
          <ul className="mt-2 divide-y divide-border text-sm">
            {pendingInvites.map((i) => (
              <li key={`${i.email}-${i.created_at}`} className="flex justify-between py-2">
                <span className="text-foreground">{i.email}</span>
                <span className="text-muted-foreground">{ROLE_LABELS[i.role]}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {canReadLogs && activity.length > 0 && (
        <section className="mt-8">
          <h2 className="text-lg font-medium text-foreground">Recent activity</h2>
          <p className="text-xs text-muted-foreground">
            Last {activity.length} Drive accesses against this workspace.
          </p>
          <ul className="mt-2 divide-y divide-border text-sm">
            {activity.slice(0, 25).map((a, i) => (
              <li key={i} className="flex justify-between py-2">
                <span className="text-foreground">
                  {a.action}
                  {a.subject && (
                    <span className="text-muted-foreground"> as {a.subject}</span>
                  )}
                </span>
                <span className="text-xs text-muted-foreground">
                  {new Date(a.created_at).toLocaleString()}
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="mt-12 border-t border-border pt-6">
        <h2 className="text-sm font-medium text-muted-foreground">Danger zone</h2>
        <Button
          variant="outline"
          className="mt-3 text-destructive"
          onClick={handleLeave}
        >
          Leave workspace
        </Button>
      </section>
    </div>
  );
}
