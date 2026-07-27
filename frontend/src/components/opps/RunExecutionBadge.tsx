import { describeRunExecution, type RunExecutionState } from "@/canopy/runState";

const TONE_CLASS: Record<string, string> = {
  muted: "border-border/70 text-muted-foreground",
  foreground: "border-border text-foreground",
  warning: "border-warning/30 bg-warning/10 text-warning",
  destructive: "border-destructive/30 bg-destructive/10 text-destructive",
};

/**
 * Where a run's execution actually stands. Renders nothing for a run that never
 * went to canopy, so it can be dropped in beside legacy/local runs unchanged.
 */
export function RunExecutionBadge({
  state,
  detail,
}: {
  state: RunExecutionState;
  detail: string;
}) {
  const described = describeRunExecution(state, detail);
  if (!described) return null;
  return (
    <span
      title={described.hint}
      className={`shrink-0 rounded border px-1.5 py-0 text-[10px] ${TONE_CLASS[described.tone]}`}
    >
      {described.label}
    </span>
  );
}
