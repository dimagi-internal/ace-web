import { useCallback, useEffect, useState } from "react";
import { Copy, Key, Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { createToken, listTokens, revokeToken } from "@/api/tokens";
import type { PersonalToken } from "@/api/types";

export default function SettingsPage() {
  const [tokens, setTokens] = useState<PersonalToken[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [newLabel, setNewLabel] = useState("");
  const [rawToken, setRawToken] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    listTokens()
      .then(setTokens)
      .catch(() => toast.error("Failed to load tokens"))
      .finally(() => setLoading(false));
  }, []);

  useEffect(load, [load]);

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
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-base font-semibold">Upload tokens</h2>
              <p className="mt-1 text-sm text-muted-foreground">
                Personal tokens for the <code>ace-upload</code> CLI. Paste into{" "}
                <code>~/.ace/config.toml</code>.
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
                      <span className="font-medium">{t.label}</span>
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
            <DialogTitle>Create upload token</DialogTitle>
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
