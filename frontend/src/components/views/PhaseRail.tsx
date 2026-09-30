import { useEffect, useMemo, useState } from "react";

import { fetchRunFlow, type SkillFlow } from "@/api/replay";
import type { PhaseInfo, RunProduct, Step } from "@/api/types.ws";
import { FlowChain, type FlowEntry } from "@/components/replay/FlowPanel";

interface Props {
  workspaceSlug: string;
  oppSlug: string;
  runId: string;
  phases: readonly PhaseInfo[];
  steps: readonly Step[];
  products: readonly RunProduct[];
  selectedPhase: string | null;
  onSelectPhase: (phase: string) => void;
}

type FlowState =
  | { readonly status: "loading" }
  | { readonly status: "error" }
  | { readonly status: "ready"; readonly flow: Readonly<Record<string, SkillFlow>> };

/** Statuses of a step that has not finished — its files aren't opened yet. */
const UNFINISHED = new Set(["pending", "running", "not_started", ""]);

const NO_FLOW: Readonly<Record<string, SkillFlow>> = {};
const ALWAYS = () => true;

/**
 * The Phases screen's right rail outside a replay: the WHOLE run as a flow —
 * every phase, every step with what it built (screenshots included), and
 * opened, what it takes in and hands on. The middle pane is one phase's
 * skills in detail; this is how the whole run hangs together, so it never
 * narrows to the selected phase. Picking a phase on the left brings that
 * phase to the top here; a phase heading here picks it on the left.
 *
 * The same chain the replay grows beat by beat ({@link FlowChain}), just
 * with nothing withheld.
 */
export function PhaseRail({
  workspaceSlug,
  oppSlug,
  runId,
  phases,
  steps,
  products,
  selectedPhase,
  onSelectPhase,
}: Props) {
  const flow = useRunFlow(workspaceSlug, oppSlug, runId);

  const entries = useMemo<FlowEntry[]>(() => {
    const out: FlowEntry[] = [];
    const producedIn = new Set(products.map((p) => p.phase));
    for (const ph of [...phases].sort((a, b) => a.ordinal - b.ordinal)) {
      const phaseSteps = steps
        .filter((s) => s.phase === ph.name)
        .sort((a, b) => a.ordinal - b.ordinal);
      if (phaseSteps.length === 0 && !producedIn.has(ph.name)) continue;
      out.push({ type: "phase", phase: ph.name, label: ph.display_name });
      for (const s of phaseSteps) out.push({ type: "step", skill: s.skill_name, phase: ph.name });
    }
    return out;
  }, [phases, steps, products]);

  const done = useMemo(
    () => new Set(steps.filter((s) => !UNFINISHED.has(s.status ?? "")).map((s) => s.skill_name)),
    [steps],
  );

  return (
    <FlowChain
      entries={entries}
      flow={flow.status === "ready" ? flow.flow : NO_FLOW}
      ioReady={flow.status === "ready"}
      steps={steps}
      phases={phases}
      products={products}
      isShown={ALWAYS}
      done={done}
      focus={selectedPhase ? { phase: selectedPhase } : null}
      selectedPhase={selectedPhase}
      onSelectPhase={onSelectPhase}
      header={
        <>
          <span>Flow</span>
          <span className="tabular-nums normal-case tracking-normal">
            {flow.status === "loading"
              ? "loading inputs & outputs…"
              : flow.status === "error"
                ? "inputs & outputs unavailable"
                : `${products.length} built`}
          </span>
        </>
      }
    />
  );
}

/** The run's declared flow, fetched once per run. */
function useRunFlow(workspaceSlug: string, oppSlug: string, runId: string): FlowState {
  const [state, setState] = useState<FlowState>({ status: "loading" });
  useEffect(() => {
    if (!workspaceSlug || !runId) {
      setState({ status: "error" });
      return;
    }
    let cancelled = false;
    setState({ status: "loading" });
    fetchRunFlow(workspaceSlug, oppSlug, runId)
      .then((flow) => !cancelled && setState({ status: "ready", flow }))
      .catch(() => !cancelled && setState({ status: "error" }));
    return () => {
      cancelled = true;
    };
  }, [workspaceSlug, oppSlug, runId]);
  return state;
}
