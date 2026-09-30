import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import type { SkillFlow } from "@/api/replay";
import type { PhaseInfo, RunProduct, Step } from "@/api/types.ws";
import { Glossed } from "@/components/glossary/Glossed";
import { ProductCard } from "@/components/viewers/ProductCard";
import { useViewer } from "@/components/viewers/ViewerContext";
import { cn } from "@/lib/utils";

import { basename, filesByBasename, phaseOrdinals, SkillIo, type RunFile } from "./FlowIo";
import type { Replay } from "./useReplay";

/** One line of the chain: a phase heading, or a step's card. */
export type FlowEntry =
  | { readonly type: "phase"; readonly phase: string; readonly label: string }
  | { readonly type: "step"; readonly skill: string; readonly phase: string };

/** What the chain brings into view: a phase heading to the top, or a step's
 *  card to the nearest edge. */
export type FlowFocus = { readonly phase: string } | { readonly skill: string } | null;

/** How long a card stays highlighted after an ↑ jump lands on it. */
const FLASH_MS = 1400;

interface ChainProps {
  entries: readonly FlowEntry[];
  flow: Readonly<Record<string, SkillFlow>>;
  /** REAL steps — to find the run's actual file for a declared path. */
  steps: readonly Step[];
  phases: readonly PhaseInfo[];
  /** Everything the run built (in a replay, cut to what the cursor has seen). */
  products: readonly RunProduct[];
  isShown: (product: RunProduct) => boolean;
  /** Steps that have finished — their files open, their dot fills. */
  done: ReadonlySet<string>;
  /** The step being shown now: its card is open and ringed. */
  current?: string | null;
  focus?: FlowFocus;
  /** Built (or photographed) on the current beat — briefly highlighted. */
  fresh?: ReadonlySet<string>;
  /** Replay: a missing screenshot is the timeline, not a gap — say nothing. */
  quiet?: boolean;
  selectedPhase?: string | null;
  onSelectPhase?: (phase: string) => void;
  header: ReactNode;
  /** Replay: blank room below the newest entry, for the run still to come. */
  roomBelow?: boolean;
  /** False while the declared flow is loading or unavailable: show what each
   *  step built, but no in/out counts that would read as "nothing". */
  ioReady?: boolean;
}

/**
 * The run as a chain: phase by phase, a card per step with what it **built**
 * (screenshots included), and — opened — its **Inputs** (which earlier step
 * made each; ↑ jumps back to that card and flashes it) and **Outputs** (which
 * later phases use each). Folded cards keep what they built, so every output
 * stays on screen under the step that made it.
 *
 * One component, two drivers: {@link ReplayFlow} grows it beat by beat;
 * `RunFlow` (the Phases screen outside a replay) shows the whole run and
 * follows the phase picked on the left. It is the screen's second axis — the
 * middle pane is one phase's skills in detail; this is how the whole run
 * hangs together.
 *
 * Inputs and outputs are the plugin's artifact manifest (`producedBy` /
 * `consumedBy`), the DECLARED flow, and the footer says so.
 */
export function FlowChain({
  entries,
  flow,
  steps,
  phases,
  products,
  isShown,
  done,
  current = null,
  focus = null,
  fresh = EMPTY,
  quiet = false,
  selectedPhase = null,
  onSelectPhase,
  header,
  roomBelow = false,
  ioReady = true,
}: ChainProps) {
  const viewer = useViewer();
  const [opened, setOpened] = useState<ReadonlySet<string>>(new Set());
  const [flash, setFlash] = useState<string | null>(null);
  const cardRefs = useRef(new Map<string, HTMLElement>());
  const phaseRefs = useRef(new Map<string, HTMLElement>());

  const onScreen = useMemo(
    () => new Set(entries.flatMap((e) => (e.type === "step" ? [e.skill] : []))),
    [entries],
  );
  const phaseOrdinal = useMemo(() => phaseOrdinals(phases), [phases]);
  const files = useMemo(() => filesByBasename(steps), [steps]);
  const runSkills = useMemo(() => new Set(steps.map((s) => s.skill_name)), [steps]);

  // Built products by the skill that made them; those no step of this run
  // made sit under their phase's heading. A step that photographed something
  // built earlier (Phase 6's walk through the Phase 3 apps) lists it too.
  const built = useMemo(() => {
    const bySkill = new Map<string, RunProduct[]>();
    const byPhase = new Map<string, RunProduct[]>();
    const photographedBy = new Map<string, RunProduct[]>();
    for (const p of products) {
      if (!isShown(p)) continue;
      const own = p.producer && runSkills.has(p.producer) ? p.producer : null;
      push(own ? bySkill : byPhase, own ?? p.phase, p);
      const takers = new Set(
        (p.previews ?? [])
          .map((pv) => pv.captured_by)
          .filter((t): t is string => !!t && runSkills.has(t)),
      );
      for (const taker of takers) if (taker !== own) push(photographedBy, taker, p);
    }
    return { bySkill, byPhase, photographedBy };
  }, [products, isShown, runSkills]);

  const focusKey = focus ? ("phase" in focus ? `p:${focus.phase}` : `s:${focus.skill}`) : "";
  useEffect(() => {
    if (!focus) return;
    if ("phase" in focus) {
      phaseRefs.current.get(focus.phase)?.scrollIntoView?.({ block: "start", behavior: "smooth" });
    } else {
      cardRefs.current.get(focus.skill)?.scrollIntoView?.({ block: "nearest", behavior: "smooth" });
    }
    // Re-run when the target changes, or a new entry mounts it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusKey, entries.length]);

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
  const fileFor = (path: string): RunFile | null => {
    const file = files.get(basename(path));
    return file && done.has(file.skill) ? file : null;
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
    setOpened((o) => new Set(o).add(skill));
    setFlash(skill);
    cardRefs.current.get(skill)?.scrollIntoView?.({ block: "center", behavior: "smooth" });
  };
  const toggle = (skill: string) =>
    setOpened((o) => {
      const next = new Set(o);
      if (next.has(skill)) next.delete(skill);
      else next.add(skill);
      return next;
    });

  return (
    <div className="flex h-full flex-col overflow-y-auto px-3 py-3 text-xs">
      <div className="mb-2 flex items-baseline justify-between px-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
        {header}
      </div>
      <ol className="flex flex-col">
        {entries.map((entry) => {
          if (entry.type === "phase") {
            const phaseBuilt = built.byPhase.get(entry.phase) ?? [];
            const selected = entry.phase === selectedPhase;
            const heading = (
              <>
                {phaseTag(entry.phase) && `${phaseTag(entry.phase)} · `}
                <Glossed text={entry.label} />
              </>
            );
            return (
              <li
                key={`phase-${entry.phase}`}
                ref={(el) => {
                  if (el) phaseRefs.current.set(entry.phase, el);
                  else phaseRefs.current.delete(entry.phase);
                }}
                className="mb-1.5 mt-3 scroll-mt-2 px-1 first:mt-0"
              >
                {onSelectPhase ? (
                  <button
                    type="button"
                    onClick={() => onSelectPhase(entry.phase)}
                    aria-current={selected ? "true" : undefined}
                    className={cn(
                      "text-left text-[10px] font-semibold uppercase tracking-wider hover:text-foreground",
                      selected ? "text-primary" : "text-muted-foreground",
                    )}
                  >
                    {heading}
                  </button>
                ) : (
                  <div className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                    {heading}
                  </div>
                )}
                {phaseBuilt.length > 0 && (
                  <BuiltList title="Built in this phase" products={phaseBuilt} fresh={fresh} quiet={quiet} />
                )}
              </li>
            );
          }
          const { skill } = entry;
          const io = flow[skill] ?? { inputs: [], outputs: [] };
          const isCurrent = skill === current;
          const open = isCurrent || opened.has(skill);
          const finished = done.has(skill);
          const made = built.bySkill.get(skill) ?? [];
          const photographed = built.photographedBy.get(skill) ?? [];
          return (
            <li
              key={skill}
              ref={(el) => {
                if (el) cardRefs.current.set(skill, el);
                else cardRefs.current.delete(skill);
              }}
              className="relative border-l border-border pb-2 pl-3"
            >
              <span
                className={cn(
                  "absolute -left-[4.5px] top-2.5 h-2 w-2 rounded-full border",
                  finished ? "border-primary bg-primary" : "border-primary bg-background",
                )}
                aria-hidden
              />
              <div
                className={cn(
                  "rounded-md border bg-card transition-all duration-300",
                  isCurrent ? "border-primary ring-2 ring-primary/30" : "border-border/70",
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
                  {!open && ioReady && (
                    <span className="shrink-0 text-[10px] tabular-nums text-muted-foreground">
                      {io.inputs.length} in · {io.outputs.length} out
                    </span>
                  )}
                </button>
                {/* What a step built stays on its card when the card folds —
                    it is what the rail is for; only the inputs/outputs fold. */}
                {(made.length > 0 || photographed.length > 0) && (
                  <div className="flex flex-col gap-2 border-t border-border/60 px-2 py-2">
                    {made.length > 0 && (
                      <BuiltList title="Built" products={made} fresh={fresh} quiet={quiet} />
                    )}
                    {photographed.length > 0 && (
                      <BuiltList title="Photographed" products={photographed} fresh={fresh} quiet={quiet} />
                    )}
                  </div>
                )}
                {open && ioReady && (
                  <SkillIo
                    io={io}
                    skill={skill}
                    label={label}
                    phaseTag={phaseTag}
                    phaseOrdinal={phaseOrdinal}
                    fileFor={(path, direction) =>
                      direction === "output" && !finished ? null : fileFor(path)
                    }
                    canJump={(producer) => onScreen.has(producer)}
                    onJump={jumpTo}
                    onOpen={openFile}
                  />
                )}
              </div>
            </li>
          );
        })}
      </ol>
      {/* Room below the newest entry, so a new phase heading can scroll to
          the top — without it the heading sits on the rail's bottom edge. */}
      {roomBelow && <div aria-hidden className="h-[60vh] shrink-0" />}
      <p className="mt-auto border-t border-border px-1 pt-2 text-[10px] leading-snug text-muted-foreground/70">
        Inputs and outputs as the ACE plugin declares them — what each step is built to read and
        write, not a trace of this run's reads.
      </p>
    </div>
  );
}

// ─── Replay driver ───────────────────────────────────────────────────

interface ReplayFlowProps {
  replay: Replay;
  steps: readonly Step[];
  phases: readonly PhaseInfo[];
  /** Each already cut to the screenshots taken by the cursor (`productAsOf`). */
  products: readonly RunProduct[];
  /** Has the cursor reached the beat that built this? */
  isRevealed: (product: RunProduct) => boolean;
  /** Built, or photographed, on the current beat. */
  justRevealed: ReadonlySet<string>;
}

/**
 * The chain growing as the replay plays: each step the cursor reaches adds a
 * card, the current one open; a new phase scrolls its heading to the top.
 * A file opens once the cursor has passed the step that wrote it.
 */
export function ReplayFlow({
  replay,
  steps,
  phases,
  products,
  isRevealed,
  justRevealed,
}: ReplayFlowProps) {
  const flow = replay.timeline?.flow;
  const entries = useMemo<FlowEntry[]>(() => {
    const out: FlowEntry[] = [];
    const events = replay.timeline?.events ?? [];
    for (let i = 0; i <= replay.beat.index && i < events.length; i++) {
      const e = events[i];
      if (e.kind === "phase_start") out.push({ type: "phase", phase: e.phase, label: e.phase_display });
      else if (e.kind === "step_start" && e.skill) out.push({ type: "step", skill: e.skill, phase: e.phase });
    }
    return out;
  }, [replay.timeline, replay.beat.index]);

  const current = replay.beat.skill;
  const focus: FlowFocus =
    replay.beat.event?.kind === "phase_start" && replay.beat.phase
      ? { phase: replay.beat.phase }
      : current
        ? { skill: current }
        : null;
  const builtCount = products.filter(isRevealed).length;

  if (!flow) return <Shell>Flow isn't available for this run.</Shell>;
  if (entries.length === 0) {
    return <Shell>Step through the run to watch what each step takes in and puts out.</Shell>;
  }
  return (
    <FlowChain
      entries={entries}
      flow={flow}
      steps={steps}
      phases={phases}
      products={products}
      isShown={isRevealed}
      done={replay.reveal.done}
      current={current}
      focus={focus}
      fresh={justRevealed}
      quiet
      roomBelow
      header={
        <>
          <span>Flow</span>
          {products.length > 0 && (
            <span className="tabular-nums">
              Built so far · {builtCount}/{products.length}
            </span>
          )}
        </>
      }
    />
  );
}

function BuiltList({
  title,
  products,
  fresh,
  quiet,
}: {
  title: string;
  products: readonly RunProduct[];
  fresh: ReadonlySet<string>;
  quiet: boolean;
}) {
  return (
    <section className="mt-1">
      <h4 className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
        {title}
      </h4>
      <ul className="flex flex-col gap-1">
        {products.map((p) => (
          <li key={p.id}>
            <ProductCard product={p} fresh={fresh.has(p.id)} quiet={quiet} />
          </li>
        ))}
      </ul>
    </section>
  );
}

const EMPTY: ReadonlySet<string> = new Set();

function push<K, V>(m: Map<K, V[]>, key: K, value: V) {
  const arr = m.get(key);
  if (arr) arr.push(value);
  else m.set(key, [value]);
}

function Shell({ children }: { children: ReactNode }) {
  return <div className="p-4 text-xs text-muted-foreground">{children}</div>;
}
