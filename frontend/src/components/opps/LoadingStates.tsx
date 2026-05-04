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
  onRetry?: () => void;
}

/**
 * Theme-aware error panel. Previously hard-coded ``bg-red-50 text-red-800``
 * which lit up bright pink in dark mode. Maps common API status codes to
 * a friendly explanation; the raw message hides behind a ``details``
 * disclosure for power users.
 */
export function ErrorState({
  title = "Something went wrong",
  message,
  onRetry,
}: ErrorStateProps) {
  const friendly = friendlyExplanation(message);
  return (
    <div className="m-4 rounded border border-destructive/30 bg-destructive/10 p-4 text-sm text-destructive">
      <div className="font-semibold">{title}</div>
      <div className="mt-1 text-foreground/80">{friendly}</div>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="mt-3 rounded bg-destructive px-3 py-1 text-xs font-semibold text-destructive-foreground hover:bg-destructive/90"
        >
          Retry
        </button>
      )}
      <details className="mt-3 opacity-70">
        <summary className="cursor-pointer text-xs">details</summary>
        <pre className="mt-1 whitespace-pre-wrap break-all text-xs">{message}</pre>
      </details>
    </div>
  );
}

function friendlyExplanation(message: string): string {
  const m = message.trim();
  if (/^5\d\d/.test(m)) {
    return "We couldn't load this from Drive — the service may be slow or rate-limited. Wait a moment and try again.";
  }
  if (/^404/.test(m) || /not\s*found/i.test(m)) {
    return "This resource doesn't exist (anymore). It may have been deleted, renamed, or moved in Drive.";
  }
  if (/^40[13]/.test(m)) {
    return "You don't have permission to see this. Check your workspace membership.";
  }
  if (/network|fetch|timeout/i.test(m)) {
    return "Network problem reaching the server. Check your connection and try again.";
  }
  return "We couldn't complete that request. The details below may help diagnose it.";
}
