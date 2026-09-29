import { useEffect, useMemo, useRef, useState } from "react";

import { fetchRunFlow, type SkillFlow } from "@/api/replay";
import type { PhaseInfo, RunProduct, Step } from "@/api/types.ws";
import { Glossed } from "@/components/glossary/Glossed";
import {
  basename,
  filesByBasename,
  phaseOrdinals,
  SkillIo,
  type RunFile,
} from "@/components/replay/FlowIo";
import { ProductCard } from "@/components/viewers/ProductCard";
import { useViewer } from "@/components/viewers/ViewerContext";
import { cn } from "@/lib/utils";

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

/** How long a step card stays highlighted after an ↑ jump lands on it. */
const FLASH_MS = 1400;

/**
 * The Phases screen's right rail, outside a replay: the selected phase's
 * **outputs** — what it handed on, with screenshots where ACE took them — and
 * then each of its steps, with what the step takes in (↑ jumps to the phase
 * that made it) and puts out (→ the phases that use it).
 *
 * An output sits with the phase that BUILT it. The Learn app's screenshots are
 * taken in Phase 6 but shown here under Phase 3, because Phase 3 is where a
 * reader meets the app (docs/specs/2026-09-29-output-previews-design.md).
 *
 * With no phase selected it lists everything the run built, phase by phase —
 * what the strip across the top of the screen used to show.
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
  const viewer = useViewer();
  const flow = useRunFlow(workspaceSlug, oppSlug, runId);
  const [opened, setOpened] = useState<ReadonlySet<string>>(new Set());
  const [flash, setFlash] = useState<string | null>(null);
  const [pendingFocus, setPendingFocus] = useState<string | null>(null);
  const cardRefs = useRef(new Map<string, HTMLElement>());

  const phaseOrdinal = useMemo(() => phaseOrdinals(phases), [phases]);
  const files = useMemo(() => filesByBasename(steps), [steps]);
  const phaseOfSkill = useMemo(() => new Map(steps.map((s) => [s.skill_name, s.phase])), [steps]);
  const productsByPhase = useMemo(() => {
    const m = new Map<string, RunProduct[]>();
    for (const p of products) {
      const arr = m.get(p.phase);
      if (arr) arr.push(p);
      else m.set(p.phase, [p]);
    }
    return m;
  }, [products]);

  // An ↑ jump into another phase switches phase first; the card it asked for
  // only exists after that render, so the scroll waits for it here.
  useEffect(() => {
    if (!pendingFocus) return;
    const el = cardRefs.current.get(pendingFocus);
    if (!el) return;
    el.scrollIntoView?.({ block: "center", behavior: "smooth" });
    setFlash(pendingFocus);
    setPendingFocus(null);
  });

  useEffect(() => {
    if (!flash) return;
    const id = window.setTimeout(() => setFlash(null), FLASH_MS);
    return () => window.clearTimeout(id);
  }, [flash]);

  const label = (s: string | null | undefined) =>
    s === "external" ? "your inputs" : (viewer?.skillLabel(s) ?? s ?? "");
  const phaseTag = (p: string | null | undefined) => {
    const n = p ? phaseOrdinal.get(p) : undefined;
    return n != null ? `Phase ${n}` : null;
  };
  const openFile = (file: RunFile) =>
    viewer?.open({
      type: "file",
      fileId: file.artifact.drive_file_id,
      name: file.artifact.name,
      driveLink: file.artifact.drive_web_link,
      skill: file.skill,
    });
  const jumpTo = (skill: string) => {
    const phase = phaseOfSkill.get(skill);
    if (!phase) return;
    setOpened((o) => new Set(o).add(skill));
    if (phase !== selectedPhase) onSelectPhase(phase);
    setPendingFocus(skill);
  };
  const toggle = (skill: string) =>
    setOpened((o) => {
      const next = new Set(o);
      if (next.has(skill)) next.delete(skill);
      else next.add(skill);
      return next;
    });

  const selected = selectedPhase ? phases.find((p) => p.name === selectedPhase) : undefined;

  if (!selected) {
    return (
      <div className="flex h-full flex-col overflow-y-auto px-3 py-3 text-xs">
        <RailHeading>What this run built</RailHeading>
        {products.length === 0 ? (
          <p className="px-1 text-[11px] text-muted-foreground">
            Nothing recorded yet. Pick a phase to see what its steps take in and put out.
          </p>
        ) : (
          <ol className="flex flex-col gap-3">
            {phases
              .filter((ph) => productsByPhase.has(ph.name))
              .map((ph) => (
                <li key={ph.name}>
                  <button
                    type="button"
                    onClick={() => onSelectPhase(ph.name)}
                    className="mb-1 px-1 text-left text-[10px] font-semibold uppercase tracking-wider text-muted-foreground hover:text-foreground"
                  >
                    Phase {ph.ordinal} · <Glossed text={ph.display_name} />
                  </button>
                  <ProductList products={productsByPhase.get(ph.name) ?? []} />
                </li>
              ))}
          </ol>
        )}
      </div>
    );
  }

  const phaseProducts = productsByPhase.get(selected.name) ?? [];
  const phaseSteps = steps
    .filter((s) => s.phase === selected.name)
    .sort((a, b) => a.ordinal - b.ordinal);

  return (
    <div className="flex h-full flex-col overflow-y-auto px-3 py-3 text-xs">
      <RailHeading>
        Phase {selected.ordinal} · <Glossed text={selected.display_name} />
      </RailHeading>

      <section aria-label="Built in this phase" className="mb-4">
        <SectionTitle>Built in this phase</SectionTitle>
        {phaseProducts.length === 0 ? (
          <p className="px-1 text-[11px] text-muted-foreground">No outputs recorded for this phase.</p>
        ) : (
          <ProductList products={phaseProducts} />
        )}
      </section>

      <section aria-label="Steps" className="flex flex-col">
        <SectionTitle>Steps</SectionTitle>
        {flow.status === "loading" && (
          <p className="px-1 text-[11px] text-muted-foreground">Loading what each step reads and writes…</p>
        )}
        {flow.status === "error" && (
          <p className="px-1 text-[11px] text-muted-foreground">
            What each step reads and writes isn't available for this run.
          </p>
        )}
        {flow.status === "ready" && phaseSteps.length === 0 && (
          <p className="px-1 text-[11px] text-muted-foreground">No steps recorded for this phase yet.</p>
        )}
        {flow.status === "ready" && (
          <ol className="flex flex-col gap-1.5">
            {phaseSteps.map((st) => {
              const skill = st.skill_name;
              const io = flow.flow[skill] ?? { inputs: [], outputs: [] };
              const open = opened.has(skill);
              return (
                <li
                  key={skill}
                  ref={(el) => {
                    if (el) cardRefs.current.set(skill, el);
                    else cardRefs.current.delete(skill);
                  }}
                >
                  <div
                    className={cn(
                      "rounded-md border border-border/70 bg-card transition-all duration-300",
                      flash === skill && "border-amber-400 ring-2 ring-amber-400/50",
                    )}
                  >
                    <button
                      type="button"
                      onClick={() => toggle(skill)}
                      aria-expanded={open}
                      className="flex w-full items-center gap-2 px-2 py-1.5 text-left"
                    >
                      <span className="min-w-0 flex-1 truncate font-semibold text-foreground">
                        <Glossed text={label(skill)} />
                      </span>
                      <span className="shrink-0 text-[10px] tabular-nums text-muted-foreground">
                        {io.inputs.length} in · {io.outputs.length} out
                      </span>
                    </button>
                    {open && (
                      <SkillIo
                        io={io}
                        skill={skill}
                        label={label}
                        phaseTag={phaseTag}
                        phaseOrdinal={phaseOrdinal}
                        fileFor={(path) => files.get(basename(path)) ?? null}
                        canJump={(producer) => phaseOfSkill.has(producer)}
                        onJump={jumpTo}
                        onOpen={openFile}
                      />
                    )}
                  </div>
                </li>
              );
            })}
          </ol>
        )}
      </section>

      <p className="mt-auto border-t border-border px-1 pt-2 text-[10px] leading-snug text-muted-foreground/70">
        Inputs and outputs as the ACE plugin declares them — what each step is built to read and
        write, not a trace of this run's reads.
      </p>
    </div>
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

function ProductList({ products }: { products: readonly RunProduct[] }) {
  return (
    <ul className="flex flex-col gap-1">
      {products.map((p) => (
        <li key={p.id}>
          <ProductCard product={p} />
        </li>
      ))}
    </ul>
  );
}

function RailHeading({ children }: { children: React.ReactNode }) {
  return (
    <div className="mb-3 px-1 text-[11px] font-semibold uppercase tracking-wider text-foreground">
      {children}
    </div>
  );
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <h3 className="mb-1.5 px-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
      {children}
    </h3>
  );
}
