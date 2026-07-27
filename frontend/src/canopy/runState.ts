/**
 * A run's execution state, as reported by ace-web's `/sessions/{slug}/execution`
 * and embedded on each run dict from `/opps/{slug}/runs`.
 *
 * `no_runner_configured` is the NORMAL day-one state: there is no session-capable
 * canopy cloud runner online, so a dispatched turn sits QUEUED and canopy
 * classifies it after a 150s grace. Rendering it as "queued" would make a run
 * that will never start look like one about to.
 *
 * `no_runner_configured` vs `waiting_for_runner` comes from canopy's advisory
 * `kind`, which it derives from the runners visible in the CALLING user's
 * tenant. ace-web's delegated identity pairs none, so in practice the answer is
 * always "config". Both are rendered honestly as "no runner"; nothing in the UI
 * branches on the distinction beyond its wording.
 */
export type RunExecutionState =
  | "not_dispatched"
  | "queued"
  | "no_runner_configured"
  | "waiting_for_runner"
  | "running"
  | "done"
  | "failed"
  | "cancelled"
  | "lost"
  | "missed"
  | "dispatch_failed"
  | "unknown";

export interface RunExecution {
  state: RunExecutionState;
  detail: string;
  canopy_turn_id: string;
  canopy_session_id: string;
}

export type Tone = "muted" | "warning" | "destructive" | "foreground";

export function describeRunExecution(
  state: RunExecutionState,
  detail: string,
): { label: string; tone: Tone; hint: string } | null {
  switch (state) {
    case "not_dispatched":
      return null;
    case "queued":
      return {
        label: "queued",
        tone: "muted",
        hint: "Enqueued; a runner has not picked it up yet.",
      };
    case "no_runner_configured":
      return {
        label: "no runner available",
        tone: "warning",
        hint:
          detail ||
          "No runner is configured to execute this run. It will not start until one is.",
      };
    case "waiting_for_runner":
      return {
        label: "waiting for a runner",
        tone: "warning",
        hint:
          detail ||
          "A runner can execute this run, but none are reachable right now.",
      };
    case "running":
      return {
        label: "running",
        tone: "foreground",
        hint: "A runner is executing this run.",
      };
    case "done":
      return { label: "complete", tone: "muted", hint: "" };
    case "dispatch_failed":
      return { label: "dispatch failed", tone: "destructive", hint: detail };
    case "unknown":
      return {
        label: "state unknown",
        tone: "muted",
        hint: detail || "canopy could not be reached.",
      };
    default:
      return { label: state, tone: "destructive", hint: detail };
  }
}
