import { useEffect, useState } from "react";

import {
  createShareToken,
  listShareTokens,
  revokeShareToken,
} from "../api/share";
import type { ShareTokenListItem } from "../api/types";

interface Props {
  slug: string;
}

export function SharePopover({ slug }: Props) {
  const [open, setOpen] = useState(false);
  const [tokens, setTokens] = useState<ShareTokenListItem[]>([]);
  const [copyUrl, setCopyUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadTokens = async () => {
    try {
      const result = await listShareTokens(slug);
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
      const result = await createShareToken(slug);
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
      await revokeShareToken(slug, token);
      setCopyUrl(null);
      await loadTokens();
    } catch (e) {
      setError(e instanceof Error ? e.message : "failed to revoke");
    }
  };

  if (!open) {
    return (
      <button
        type="button"
        className="rounded border border-zinc-300 px-2 py-1 text-xs text-zinc-600 hover:bg-zinc-100"
        onClick={() => setOpen(true)}
      >
        share
      </button>
    );
  }

  return (
    <div className="absolute right-0 top-full z-50 mt-1 w-80 rounded-md border border-zinc-200 bg-white p-3 shadow-lg">
      <div className="mb-2 flex items-center justify-between">
        <span className="text-sm font-medium text-zinc-700">Share links</span>
        <button
          type="button"
          className="text-xs text-zinc-400 hover:text-zinc-600"
          onClick={() => {
            setOpen(false);
            setCopyUrl(null);
            setError(null);
          }}
        >
          close
        </button>
      </div>

      {copyUrl && !copyUrl.startsWith("__SHOW__") && (
        <div className="mb-2 rounded bg-emerald-50 px-2 py-1.5 text-xs text-emerald-700">
          Link copied to clipboard
        </div>
      )}

      {copyUrl && copyUrl.startsWith("__SHOW__") && (
        <div className="mb-2 rounded bg-blue-50 px-2 py-1.5 text-xs text-blue-700">
          <div className="mb-1 font-medium">Share link created (copy manually):</div>
          <div className="break-all font-mono text-[10px]">
            {copyUrl.replace("__SHOW__", "")}
          </div>
        </div>
      )}

      {error && (
        <div className="mb-2 rounded bg-rose-50 px-2 py-1.5 text-xs text-rose-700">
          {error}
        </div>
      )}

      <button
        type="button"
        disabled={loading}
        className="mb-3 w-full rounded bg-blue-600 px-3 py-1.5 text-xs text-white hover:bg-blue-700 disabled:opacity-40"
        onClick={handleCreate}
      >
        {loading ? "creating..." : "Create share link"}
      </button>

      {tokens.length > 0 && (
        <div className="space-y-1.5">
          <span className="text-xs font-medium text-zinc-500">
            Active links
          </span>
          {tokens.map((t) => (
            <div
              key={t.token}
              className="flex items-center justify-between rounded border border-zinc-100 px-2 py-1"
            >
              <span className="font-mono text-xs text-zinc-500">
                ...{t.token.slice(-8)}
              </span>
              <button
                type="button"
                className="text-xs text-rose-500 hover:text-rose-700"
                onClick={() => handleRevoke(t.token)}
              >
                revoke
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
