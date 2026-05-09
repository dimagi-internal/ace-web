import { useEffect, useState, type ReactNode } from "react";

import { cn } from "@/lib/utils";

export function LoadingSpinner({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex items-center gap-3 p-6 text-muted-foreground">
      <div className="h-4 w-4 animate-spin rounded-full border-2 border-muted-foreground/30 border-t-muted-foreground" />
      <span>{label}</span>
    </div>
  );
}

interface PatientLoaderProps {
  label?: string;
  // Shown when the load takes longer than `slowAfterMs` (default 5s) so
  // users on a cold Drive cache know the page isn't frozen.
  slowLabel?: string;
  slowAfterMs?: number;
  className?: string;
}

/**
 * A loader that promotes itself from "Loading…" to "still loading…" after
 * a few seconds. Pairs with the new error fallback in StepDetailPane /
 * ArtifactBody so users hitting a slow Drive read see something other
 * than a frozen spinner.
 */
export function PatientLoader({
  label = "Loading…",
  slowLabel = "Still loading — this can take a moment.",
  slowAfterMs = 5000,
  className,
}: PatientLoaderProps) {
  const [slow, setSlow] = useState(false);
  useEffect(() => {
    const t = setTimeout(() => setSlow(true), slowAfterMs);
    return () => clearTimeout(t);
  }, [slowAfterMs]);
  return (
    <div className={cn("flex flex-col gap-1.5 p-4 text-muted-foreground", className)}>
      <div className="flex items-center gap-3">
        <div className="h-4 w-4 shrink-0 animate-spin rounded-full border-2 border-muted-foreground/30 border-t-muted-foreground" />
        <span>{label}</span>
      </div>
      {slow && (
        <div className="pl-7 text-[11px] text-muted-foreground/80">{slowLabel}</div>
      )}
    </div>
  );
}

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 p-12 text-center">
      <h3 className="text-lg font-semibold text-muted-foreground">{title}</h3>
      {description && <p className="text-sm text-muted-foreground">{description}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

interface ErrorStateProps {
  title?: string;
  message: string;
  /**
   * Structured error code from the backend envelope (e.g. ``drive-not-configured``).
   * When present, takes precedence over the message-prose heuristic for picking
   * a friendly explanation. Plumb this from ``ApiError.code`` in callers'
   * ``.catch`` handlers so the friendly copy reflects the real cause instead
   * of guessing from substrings ("not found" can mean a 404 OR an SA-not-found
   * config error — only the code disambiguates).
   */
  code?: string | null;
  onRetry?: () => void;
}

/**
 * Theme-aware error panel. Maps the structured error code (or, lacking that,
 * the message prose) to a friendly explanation; the raw message hides behind
 * a ``details`` disclosure for power users.
 */
export function ErrorState({
  title = "Something went wrong",
  message,
  code,
  onRetry,
}: ErrorStateProps) {
  const friendly = friendlyExplanation(message, code);
  return (
    <div className="m-4 rounded border border-destructive/30 bg-destructive/10 p-4 text-sm text-destructive">
      <div className="font-semibold">{title}</div>
      <div className="mt-1 text-foreground/80">{friendly}</div>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="mt-3 rounded bg-destructive px-3 py-1 text-xs font-semibold text-white hover:bg-destructive/90"
        >
          Retry
        </button>
      )}
      <details className="mt-3 opacity-70">
        <summary className="cursor-pointer text-xs">details</summary>
        <pre className="mt-1 whitespace-pre-wrap break-all text-xs">
          {code ? `[${code}] ` : ""}{message}
        </pre>
      </details>
    </div>
  );
}

// Known backend error codes → friendly user-facing copy. Add entries here
// when the backend introduces a new ``code`` in error_response(). Codes are
// matched as exact strings; the backend is the source of truth (grep
// ``error_response\(.*code=`` in apps/).
const CODE_EXPLANATIONS: Record<string, string> = {
  "drive-not-configured":
    "Google Drive isn't reachable for this workspace — the ace-drive service account isn't configured in this environment. " +
    "In local dev, run `/ace:setup` to pull the key from 1Password. " +
    "In a deployed environment this means a deploy-config drift; check ACE_DRIVE_SA_KEY_JSON in AWS Secrets Manager.",
};

export function friendlyExplanation(message: string, code?: string | null): string {
  // Code-first: if the backend told us specifically what went wrong, trust
  // that over a regex against the prose. Without this, a message like
  // "Service account 'ace-drive' not found or inactive" matches the generic
  // /not found/ branch and surfaces a misleading "this was deleted" copy.
  if (code && CODE_EXPLANATIONS[code]) {
    return CODE_EXPLANATIONS[code];
  }

  const m = message.trim();
  if (/\b5\d\d\b/.test(m) || /server\s*error/i.test(m)) {
    return "We couldn't load this from Drive — the service may be slow or rate-limited. Wait a moment and try again.";
  }
  if (/\b404\b/.test(m) || /not[\s_-]*found/i.test(m)) {
    return "This doesn't exist (anymore). It may have been deleted, renamed, or moved in Drive.";
  }
  if (/\b40[13]\b/.test(m) || /forbidden|unauthor/i.test(m)) {
    return "You don't have permission to see this. Check your workspace membership.";
  }
  if (/network|fetch|timeout|econnref|enotfound/i.test(m)) {
    return "Network problem reaching the server. Check your connection and try again.";
  }
  return "We couldn't complete that request. The details below may help diagnose it.";
}
