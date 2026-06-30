import { useCallback, useEffect, useState } from "react";
import { Copy, Key, Plus, Trash2 } from "lucide-react";
import { Link } from "react-router-dom";
import { toast } from "sonner";

import { Badge } from "canopy-ui/ui";
import { Button } from "canopy-ui/ui";
import { Input } from "canopy-ui/ui";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { cliAuthStatus, disconnectNova, novaAuthStatus, promoteCliAuthToGlobal } from "@/api/auth";
import { createToken, listTokens, revokeToken, type PersonalToken } from "@/api/tokens";
import type { CliAuthStatus, NovaAuthStatus } from "@/api/types.ws";

const NOVA_CONNECT_URL = `${(import.meta.env.BASE_URL ?? "/").replace(/\/$/, "")}/auth/nova/initiate/`;

export default function SettingsPage() {
  const [tokens, setTokens] = useState<PersonalToken[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [newLabel, setNewLabel] = useState("");
  const [rawToken, setRawToken] = useState<string | null>(null);
  const [cliStatus, setCliStatus] = useState<CliAuthStatus | null>(null);
  const [novaStatus, setNovaStatus] = useState<NovaAuthStatus | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    listTokens()
      .then(setTokens)
      .catch(() => toast.error("Failed to load tokens"))
      .finally(() => setLoading(false));
  }, []);

  const loadCliStatus = useCallback(() => {
    cliAuthStatus()
      .then(setCliStatus)
      .catch(() => setCliStatus(null));
  }, []);

  const loadNovaStatus = useCallback(() => {
    novaAuthStatus()
      .then(setNovaStatus)
      .catch(() => setNovaStatus(null));
  }, []);

  useEffect(load, [load]);
  useEffect(loadCliStatus, [loadCliStatus]);
  useEffect(loadNovaStatus, [loadNovaStatus]);

  // Surface the redirect from /auth/nova/callback so the user sees
  // a confirmation toast instead of a silent state change.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const novaParam = params.get("nova");
    if (novaParam === "connected") toast.success("Nova connected");
    else if (novaParam === "error") {
      const reason = params.get("reason") ?? "unknown";
      toast.error(`Nova connect failed: ${reason}`);
    }
    if (novaParam) {
      params.delete("nova");
      params.delete("reason");
      const next = params.toString();
      const url = window.location.pathname + (next ? `?${next}` : "");
      window.history.replaceState({}, "", url);
    }
  }, []);

  const handleDisconnectNova = async () => {
    try {
      await disconnectNova();
      toast.success("Nova disconnected");
      loadNovaStatus();
    } catch (e) {
      const message = e instanceof Error ? e.message : "Disconnect failed";
      toast.error(message);
    }
  };

  const handlePromote = async () => {
    try {
      await promoteCliAuthToGlobal();
      toast.success("Promoted to shared fallback");
      loadCliStatus();
    } catch (e) {
      const message = e instanceof Error ? e.message : "Promote failed";
      toast.error(message);
    }
  };

  const handleCreate = async () => {
    if (!newLabel.trim()) return;
    const result = await createToken(newLabel.trim());
    setRawToken(result.raw_token);
    setNewLabel("");
    setShowCreate(false);
    load();
  };

  const handleRevoke = async (id: number) => {
    await revokeToken(id);
    toast.success("Token revoked");
    load();
  };

  const handleCopy = () => {
    if (rawToken) {
      navigator.clipboard.writeText(rawToken);
      toast.success("Copied to clipboard");
    }
  };

  return (
    <div className="flex h-full flex-col bg-background text-foreground">
      <header className="flex items-center gap-4 border-b border-border px-6 py-3">
        <h1 className="text-lg font-semibold">Settings</h1>
      </header>
      <main className="flex-1 overflow-y-auto p-6">
        <section className="max-w-2xl">
          <h2 className="text-base font-semibold">System overview</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            What ACE is — the phases, skills, agents, and MCP tools bundled in
            this deployment. Reads live from the ACE plugin shipped with the
            image.
          </p>
          <Link
            to="/system"
            className="mt-3 inline-block text-sm font-medium text-primary hover:underline"
          >
            Open System Overview →
          </Link>
        </section>

        {cliStatus && (
          <section className="mt-10 max-w-2xl">
            <h2 className="text-base font-semibold">Claude Max subscription</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Powers web chat — the server calls Anthropic with your Claude Max
              subscription (OAuth, not an API key). Upload from your laptop via
              the <code>/ace-web:create-cli-credentials</code> skill.
            </p>

            <div className="mt-4 rounded border border-border p-4">
              <div className="flex items-center justify-between">
                <div className="font-medium">Your subscription</div>
                <Badge variant={cliStatus.user.has_blob ? "default" : "outline"}>
                  {cliStatus.user.has_blob
                    ? cliStatus.authenticated
                      ? "Active"
                      : "Uploaded but failing"
                    : "Not uploaded"}
                </Badge>
              </div>
              {cliStatus.user.token_prefix && (
                <code className="mt-2 block text-xs text-muted-foreground">
                  {cliStatus.user.token_prefix}…
                </code>
              )}
            </div>

            <div className="mt-3 rounded border border-border p-4">
              <div className="flex items-center justify-between">
                <div>
                  <div className="font-medium">Shared fallback</div>
                  <div className="text-xs text-muted-foreground">
                    Used when a user hasn't uploaded their own subscription.
                  </div>
                </div>
                <Badge variant={cliStatus.global.has_blob ? "default" : "outline"}>
                  {cliStatus.global.has_blob ? "Configured" : "Missing"}
                </Badge>
              </div>
              {cliStatus.user.has_blob && (
                <Button
                  size="sm"
                  variant="outline"
                  className="mt-3"
                  onClick={handlePromote}
                >
                  Promote my subscription to shared fallback (admin only)
                </Button>
              )}
            </div>
          </section>
        )}

        {novaStatus && (
          <section className="mt-10 max-w-2xl">
            <h2 className="text-base font-semibold">Nova MCP</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Powers the Nova app-builder tools (<code>mcp__nova__*</code>) inside
              chat. Single shared <code>ace@dimagi-ai.com</code> identity — connect
              once, every workspace uses it.
            </p>

            <div className="mt-4 rounded border border-border p-4">
              <div className="flex items-center justify-between">
                <div className="font-medium">Connection</div>
                <Badge variant={novaStatus.connected ? "default" : "outline"}>
                  {novaStatus.connected
                    ? novaStatus.valid
                      ? "Connected"
                      : "Connected but failing"
                    : "Not connected"}
                </Badge>
              </div>
              {novaStatus.connected && novaStatus.expires_at && (
                <div className="mt-2 text-xs text-muted-foreground">
                  Token expires {new Date(novaStatus.expires_at * 1000).toLocaleString()}
                  {" · "}
                  scopes: <code>{novaStatus.scope}</code>
                </div>
              )}
              {novaStatus.can_manage && (
                <div className="mt-3 flex gap-2">
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => {
                      window.location.href = NOVA_CONNECT_URL;
                    }}
                  >
                    {novaStatus.connected ? "Reconnect" : "Connect Nova"}
                  </Button>
                  {novaStatus.connected && (
                    <Button size="sm" variant="ghost" onClick={handleDisconnectNova}>
                      Disconnect
                    </Button>
                  )}
                </div>
              )}
              {!novaStatus.can_manage && !novaStatus.connected && (
                <p className="mt-2 text-xs text-muted-foreground">
                  Ask an admin to connect Nova on this instance.
                </p>
              )}
            </div>
          </section>
        )}

        <section className="mt-10 max-w-2xl">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-base font-semibold">ACE API tokens</h2>
              <p className="mt-1 text-sm text-muted-foreground">
                Bearer tokens that identify you to ace-web from a script. Used by{" "}
                <code>ace-upload</code>, <code>/ace-web:create-cli-credentials</code>,
                and any custom tooling you point at the ACE API.
              </p>
            </div>
            <Button size="sm" onClick={() => setShowCreate(true)}>
              <Plus className="mr-1.5 h-3.5 w-3.5" />Create token
            </Button>
          </div>
          {loading && <p className="mt-4 text-sm text-muted-foreground">Loading...</p>}
          {!loading && tokens.length === 0 && (
            <p className="mt-4 text-sm text-muted-foreground">No tokens yet.</p>
          )}
          {!loading && tokens.length > 0 && (
            <div className="mt-4 divide-y divide-border rounded border border-border">
              {tokens.map((t) => (
                <div key={t.id} className="flex items-center justify-between px-4 py-3">
                  <div>
                    <div className="flex items-center gap-2">
                      <Key className="h-3.5 w-3.5 text-muted-foreground" />
                      <span className="font-medium">{t.name}</span>
                    </div>
                    <div className="mt-0.5 text-xs text-muted-foreground">
                      Created {new Date(t.created_at).toLocaleDateString()}
                      {t.last_used_at &&
                        ` · Last used ${new Date(t.last_used_at).toLocaleDateString()}`}
                    </div>
                  </div>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-7 w-7 text-destructive"
                    onClick={() => handleRevoke(t.id)}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </Button>
                </div>
              ))}
            </div>
          )}
        </section>
      </main>

      <Dialog open={showCreate} onOpenChange={setShowCreate}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Create ACE API token</DialogTitle>
            <DialogDescription>Give this token a label (e.g., "laptop").</DialogDescription>
          </DialogHeader>
          <Input
            placeholder="Token label"
            value={newLabel}
            onChange={(e) => setNewLabel(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleCreate()}
          />
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowCreate(false)}>
              Cancel
            </Button>
            <Button onClick={handleCreate} disabled={!newLabel.trim()}>
              Create
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={!!rawToken} onOpenChange={() => setRawToken(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Token created</DialogTitle>
            <DialogDescription>
              Copy this token now — it won't be shown again.
            </DialogDescription>
          </DialogHeader>
          <div className="flex items-center gap-2">
            <code className="flex-1 truncate rounded bg-muted px-3 py-2 text-sm">
              {rawToken}
            </code>
            <Button variant="outline" size="icon" onClick={handleCopy}>
              <Copy className="h-4 w-4" />
            </Button>
          </div>
          <DialogFooter>
            <Button onClick={() => setRawToken(null)}>I've saved this</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
