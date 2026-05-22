import { Check, Trash2, X } from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  createShareToken,
  listShareTokens,
  revokeShareToken,
} from "../api/share";
import type { ShareTokenListItem } from "../api/types.ws";

interface Props {
  slug: string;
  workspaceSlug: string;
}

export function SharePopover({ slug, workspaceSlug }: Props) {
  const [open, setOpen] = useState(false);
  const [tokens, setTokens] = useState<ShareTokenListItem[]>([]);
  const [copyUrl, setCopyUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadTokens = async () => {
    try {
      const result = await listShareTokens(slug, workspaceSlug);
      setTokens(result);
    } catch {
      // Silently fail — the list just stays empty
    }
  };

  useEffect(() => {
    if (open) {
      loadTokens();
    }
  }, [open, slug]);

  const handleCreate = async () => {
    setLoading(true);
    setError(null);
    setCopyUrl(null);
    try {
      const result = await createShareToken(slug, workspaceSlug);
      // Try to copy to clipboard, but don't fail the whole flow if the
      // browser denies clipboard access (headless, restricted contexts).
      let copied = false;
      try {
        await navigator.clipboard.writeText(result.url);
        copied = true;
      } catch {
        // Clipboard write denied — show the URL in the popover instead.
      }
      setCopyUrl(copied ? result.url : `__SHOW__${result.url}`);
      await loadTokens();
    } catch (e) {
      setError(e instanceof Error ? e.message : "failed to create share link");
    } finally {
      setLoading(false);
    }
  };

  const handleRevoke = async (token: string) => {
    try {
      await revokeShareToken(slug, token, workspaceSlug);
      setCopyUrl(null);
      await loadTokens();
    } catch (e) {
      setError(e instanceof Error ? e.message : "failed to revoke");
    }
  };

  if (!open) {
    return (
      <Button
        type="button"
        variant="ghost"
        size="sm"
        className="h-7 px-1.5 text-xs font-normal text-muted-foreground hover:text-foreground"
        onClick={() => setOpen(true)}
      >
        share
      </Button>
    );
  }

  return (
    <div className="absolute right-0 top-full z-50 mt-1 w-80 rounded-md border border-border bg-popover p-3 text-popover-foreground shadow-lg">
      <div className="mb-3 flex items-center justify-between">
        <span className="text-sm font-semibold">Share links</span>
        <button
          type="button"
          className="text-muted-foreground hover:text-foreground"
          onClick={() => {
            setOpen(false);
            setCopyUrl(null);
            setError(null);
          }}
          aria-label="Close"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      {copyUrl && !copyUrl.startsWith("__SHOW__") && (
        <div className="mb-3 flex items-center gap-2 rounded-md border border-border bg-muted px-2 py-1.5 text-xs text-foreground">
          <Check className="h-3.5 w-3.5 text-primary" />
          <span>Link copied to clipboard</span>
        </div>
      )}

      {copyUrl && copyUrl.startsWith("__SHOW__") && (
        <div className="mb-3 rounded-md border border-border bg-muted px-2 py-1.5 text-xs text-foreground">
          <div className="mb-1 font-medium">Share link created (copy manually):</div>
          <div className="break-all rounded bg-background px-2 py-1 font-mono text-[10px]">
            {copyUrl.replace("__SHOW__", "")}
          </div>
        </div>
      )}

      {error && (
        <div className="mb-3 rounded-md border border-destructive/50 bg-destructive/10 px-2 py-1.5 text-xs text-destructive">
          {error}
        </div>
      )}

      <Button
        type="button"
        size="sm"
        disabled={loading}
        onClick={handleCreate}
        className="mb-3 w-full"
      >
        {loading ? "creating..." : "Create share link"}
      </Button>

      {tokens.length > 0 && (
        <div className="space-y-1.5">
          <span className="text-xs font-medium text-muted-foreground">
            Active links
          </span>
          {tokens.map((t) => (
            <div
              key={t.token}
              className="flex items-center justify-between rounded-md border border-border px-2 py-1"
            >
              <span className="font-mono text-xs text-muted-foreground">
                ...{t.token.slice(-8)}
              </span>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="h-6 w-6 text-destructive hover:bg-destructive/10 hover:text-destructive"
                onClick={() => handleRevoke(t.token)}
                aria-label="revoke"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </Button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
