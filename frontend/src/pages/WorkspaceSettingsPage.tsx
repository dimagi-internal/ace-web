import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";

import {
  changeMemberRole,
  getDriveConfig,
  getWorkspace,
  inviteMember,
  removeMember,
  verifyDriveAccess,
  type WorkspaceDetail,
  type WorkspaceRole,
} from "../api/workspaces";
import { Button } from "@/components/ui/button";

const ROLE_OPTIONS: WorkspaceRole[] = ["owner", "editor", "viewer"];

export default function WorkspaceSettingsPage() {
  const { workspaceSlug } = useParams<{ workspaceSlug: string }>();
  const [ws, setWs] = useState<WorkspaceDetail | null>(null);
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

  useEffect(() => {
    if (!workspaceSlug) return;
    getWorkspace(workspaceSlug).then(setWs).catch((e) => setError(String((e as Error).message)));
    getDriveConfig().then((c) => setSaEmail(c.service_account_email)).catch(() => {});
  }, [workspaceSlug, reload]);

  if (!workspaceSlug) return null;
  if (error) return <div className="p-6 text-destructive">{error}</div>;
  if (!ws) return <div className="p-6 text-muted-foreground">Loading…</div>;

  const myRole = ws.my_role;
  const isOwner = myRole === "owner";

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

  return (
    <div className="mx-auto max-w-3xl px-6 py-8">
      <h1 className="text-2xl font-semibold text-foreground">{ws.display_name}</h1>
      <p className="text-sm text-muted-foreground">/{ws.slug}</p>

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
            {ws.members.map((m) => (
              <tr key={m.user_email} className="border-b border-border">
                <td className="py-2 text-foreground">{m.user_email}</td>
                <td className="py-2 text-muted-foreground">{m.user_display_name}</td>
                <td className="py-2">
                  {isOwner ? (
                    <select
                      value={m.role}
                      onChange={(e) => {
                        const userId = Number(
                          ws.members.indexOf(m) /* placeholder */,
                        );
                        // The API exposes user_email, not user_id.
                        // We can't change roles without user_id; this UI
                        // is a placeholder hook for the API call. Until
                        // the serializer surfaces user_id, role-change
                        // is admin-only via Django admin.
                        void userId;
                        void handleRoleChange;
                        void e;
                      }}
                      className="rounded border border-input bg-background px-2 py-1 text-xs"
                      disabled
                      title="Role changes via Django admin (Phase B v1)"
                    >
                      {ROLE_OPTIONS.map((r) => (
                        <option key={r} value={r}>{r}</option>
                      ))}
                    </select>
                  ) : (
                    <span className="text-foreground">{m.role}</span>
                  )}
                </td>
                <td className="py-2 text-muted-foreground">
                  {new Date(m.joined_at).toLocaleDateString()}
                </td>
                <td className="py-2 text-right">
                  {isOwner && m.user_email !== "" && m.role !== "owner" && (
                    <button
                      type="button"
                      onClick={() =>
                        // Same caveat: needs user_id from the serializer.
                        void handleRemove(m.user_email, 0)
                      }
                      className="text-xs text-destructive opacity-50"
                      title="Removal via Django admin (Phase B v1)"
                      disabled
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
          <h2 className="text-lg font-medium text-foreground">Invite a teammate</h2>
          <div className="mt-3 flex gap-2">
            <input
              type="email"
              placeholder="email@example.com"
              value={inviteEmail}
              onChange={(e) => setInviteEmail(e.target.value)}
              className="flex-1 rounded border border-input bg-background px-3 py-2 text-sm text-foreground"
            />
            <select
              value={inviteRole}
              onChange={(e) => setInviteRole(e.target.value as WorkspaceRole)}
              className="rounded border border-input bg-background px-2 py-2 text-sm"
            >
              {ROLE_OPTIONS.map((r) => (
                <option key={r} value={r}>{r}</option>
              ))}
            </select>
            <Button onClick={handleInvite} disabled={!inviteEmail.trim()}>
              Send invite
            </Button>
          </div>
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
    </div>
  );
}
