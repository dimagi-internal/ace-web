import type { ReactNode } from "react";

export function LoadingSpinner({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex items-center gap-3 p-6 text-zinc-500">
      <div className="h-4 w-4 animate-spin rounded-full border-2 border-zinc-300 border-t-zinc-600" />
      <span>{label}</span>
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
      <h3 className="text-lg font-semibold text-zinc-700">{title}</h3>
      {description && <p className="text-sm text-zinc-500">{description}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function ErrorState({
  title = "Something went wrong",
  message,
  onRetry,
}: {
  title?: string;
  message: string;
  onRetry?: () => void;
}) {
  return (
    <div className="rounded border border-red-200 bg-red-50 p-4 text-sm text-red-800">
      <div className="font-semibold">{title}</div>
      <div className="mt-1">{message}</div>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="mt-3 rounded bg-red-600 px-3 py-1 text-white hover:bg-red-700"
        >
          Retry
        </button>
      )}
    </div>
  );
}
