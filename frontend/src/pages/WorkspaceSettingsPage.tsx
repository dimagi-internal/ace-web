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
  resendInvite,
  revokeInvite,
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
    email: string;
    email_sent: boolean;
  } | null>(null);
  // Per pending invite (by id): a resend in flight, done, or not emailed.
  const [resendState, setResendState] = useState<
    Record<number, { status: "sending" | "sent" | "not_sent"; accept_url?: string }>
  >({});
  const [verifyMsg, setVerifyMsg] = useState<string | null>(null);
  const [driveBroken, setDriveBroken] = useState<string | null>(null);
  const [activity, setActivity] = useState<ActivityRow[]>([]);
  const [pendingInvites, setPendingInvites] = useState<PendingInvite[]>([]);

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
      setInviteResult({ accept_url: r.accept_url, email: r.email, email_sent: r.email_sent });
      setInviteEmail("");
      setReload((n) => n + 1);
    } catch (e) {
      setError(String((e as Error).message));
    }
  }

  async function handleResend(inviteId: number) {
    setError(null);
    setResendState((s) => ({ ...s, [inviteId]: { status: "sending" } }));
    try {
      const r = await resendInvite(workspaceSlug!, inviteId);
      setResendState((s) => ({
        ...s,
        [inviteId]: r.email_sent
          ? { status: "sent" }
          : { status: "not_sent", accept_url: r.accept_url },
      }));
      setReload((n) => n + 1);
    } catch (e) {
      setResendState((s) => {
        const { [inviteId]: _, ...rest } = s;
        return rest;
      });
      setError(String((e as Error).message));
    }
  }

  async function handleRevoke(inviteId: number, email: string) {
    if (!confirm(`Revoke the invite to ${email}? Its link stops working.`)) return;
    setError(null);
    try {
      await revokeInvite(workspaceSlug!, inviteId);
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
              <p className="text-foreground" data-testid="invite-result">
                {inviteResult.email_sent
                  ? `Invite emailed to ${inviteResult.email}. The same link, if you want to send it yourself:`
                  : `Invite created, but no email went out. Copy this link and send it to ${inviteResult.email}:`}
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
            {pendingInvites.map((i) => {
              const rs = resendState[i.id];
              return (
                <li key={i.id} className="py-2">
                  <div className="flex items-center justify-between gap-3">
                    <span className="min-w-0 flex-1 truncate text-foreground">{i.email}</span>
                    <span className="text-muted-foreground">{ROLE_LABELS[i.role]}</span>
                    <span className="hidden text-xs text-muted-foreground sm:inline">
                      expires {new Date(i.expires_at).toLocaleDateString()}
                    </span>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => handleResend(i.id)}
                      disabled={rs?.status === "sending"}
                    >
                      {rs?.status === "sending" ? "Sending…" : rs?.status === "sent" ? "Sent" : "Resend"}
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => handleRevoke(i.id, i.email)}
                    >
                      Revoke
                    </Button>
                  </div>
                  {rs?.status === "not_sent" && rs.accept_url && (
                    <p className="mt-1 text-xs text-muted-foreground">
                      Email is not available — send this link yourself:{" "}
                      <span className="select-all break-all font-mono text-foreground">
                        {window.location.origin}/ace{rs.accept_url}
                      </span>
                    </p>
                  )}
                </li>
              );
            })}
          </ul>
        </section>
      )}


      {canReadLogs && activity.length > 0 && (
        <section className="mt-8">
          <h2 className="text-lg font-medium text-foreground">Recent activity</h2>
          <p className="text-xs text-muted-foreground">
            Drive accesses, tenancy changes and membership changes, newest first.
          </p>
          <ul className="mt-2 divide-y divide-border text-sm">
            {activity.slice(0, 25).map((a, i) => (
              <li key={i} className="flex justify-between py-2">
                <span className="text-foreground">{describeActivity(a)}</span>
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

const MEMBERSHIP_VERBS: Record<string, string> = {
  "invite.sent": "invited",
  "invite.resent": "re-sent the invite to",
  "invite.revoked": "revoked the invite to",
  "member.role_changed": "changed the role of",
  "member.removed": "removed",
};

/** One feed row as a sentence. Membership rows (apps/workspaces/audit.py)
 * name who did it and the roles; anything else keeps its raw action. */
function describeActivity(a: ActivityRow): string {
  const by = (a.context.changed_by as string | null | undefined) ?? "someone";
  const before = a.context.before as string | undefined;
  const after = a.context.after as string | undefined;
  const role = (r?: string) => (r ? ROLE_LABELS[r as keyof typeof ROLE_LABELS] ?? r : "");
  if (a.action === "invite.accepted") {
    return before
      ? `${a.subject} accepted an invite (${role(before)} → ${role(after)})`
      : `${a.subject} joined as ${role(after)}`;
  }
  if (a.action === "member.left") return `${a.subject} left (was ${role(before)})`;
  const verb = MEMBERSHIP_VERBS[a.action];
  if (verb) {
    const roles =
      before && after ? ` (${role(before)} → ${role(after)})` : after || before ? ` (${role(after || before)})` : "";
    return `${by} ${verb} ${a.subject}${roles}`;
  }
  return a.subject ? `${a.action} as ${a.subject}` : a.action;
}
