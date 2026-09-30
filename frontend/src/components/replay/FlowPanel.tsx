import { useEffect, useMemo, useRef, useState } from "react";

import type { ReplayProduct } from "@/api/replay";
import type { PhaseInfo, Step } from "@/api/types.ws";
import { Glossed } from "@/components/glossary/Glossed";
import { ProductCard } from "@/components/viewers/ProductCard";
import { useViewer } from "@/components/viewers/ViewerContext";
import { cn } from "@/lib/utils";

import { basename, filesByBasename, phaseOrdinals, SkillIo, type RunFile } from "./FlowIo";
import type { Replay } from "./useReplay";

interface Props {
  replay: Replay;
  /** REAL steps (not as-of-cursor) — to find the run's actual file for a path. */
  steps: readonly Step[];
  phases: readonly PhaseInfo[];
  /** What the run built, each already cut to the screenshots taken by the
   *  cursor (`productAsOf`). */
  products: readonly ReplayProduct[];
  /** Has the cursor reached the beat that built this? */
  isRevealed: (product: ReplayProduct) => boolean;
  /** Built, or photographed, on the current beat — briefly highlighted. */
  justRevealed: ReadonlySet<string>;
}

type Entry =
  | { readonly type: "phase"; readonly phase: string; readonly label: string }
  | { readonly type: "step"; readonly skill: string; readonly phase: string };

/** How long a card stays highlighted after an ↑ jump lands on it. */
const FLASH_MS = 1400;

/**
 * The run as a chain of steps, growing as the replay plays: each step the
 * cursor reaches adds a card, and the panel scrolls down to follow it.
 *
 * The current step's card is open — what it **built** (with its screenshots,
 * as they are taken), its **Inputs** (and which earlier step made each) and
 * its **Outputs** (and which later phases use each). Earlier cards fold to one
 * line plus what they built, so the chain stays readable and every output the
 * run has made so far stays on screen. An input made by an earlier step carries
 * ↑: click it and the panel scrolls back to the card that made it and flashes
 * it, so "the PDD from Phase 1 is what Phase 3 builds the apps from" is
 * something you can watch, not something the presenter has to assert.
 *
 * A step that photographs something built earlier (Phase 6's walk through the
 * Phase 3 apps) shows it under **Photographed**: the screenshots live with the
 * app, but this is the beat they were taken.
 *
 * Inputs and outputs are the plugin's artifact manifest (`producedBy` /
 * `consumedBy`), so it is the DECLARED flow, and the footer says so. A file
 * opens in the viewer once the cursor has passed the step that wrote it.
 */
export function FlowPanel({ replay, steps, phases, products, isRevealed, justRevealed }: Props) {
  const viewer = useViewer();
  const flow = replay.timeline?.flow;
  const current = replay.beat.skill;
  const [opened, setOpened] = useState<ReadonlySet<string>>(new Set());
  const [flash, setFlash] = useState<string | null>(null);
  const cardRefs = useRef(new Map<string, HTMLElement>());
  const phaseRefs = useRef(new Map<string, HTMLElement>());
  const endRef = useRef<HTMLDivElement>(null);

  // Everything the cursor has reached, in run order, with phase headers.
  const entries = useMemo<Entry[]>(() => {
    const out: Entry[] = [];
    const events = replay.timeline?.events ?? [];
    for (let i = 0; i <= replay.beat.index && i < events.length; i++) {
      const e = events[i];
      if (e.kind === "phase_start") out.push({ type: "phase", phase: e.phase, label: e.phase_display });
      else if (e.kind === "step_start" && e.skill) out.push({ type: "step", skill: e.skill, phase: e.phase });
    }
    return out;
  }, [replay.timeline, replay.beat.index]);
  const onScreen = useMemo(
    () => new Set(entries.filter((e) => e.type === "step").map((e) => (e as { skill: string }).skill)),
    [entries],
  );

  const phaseOrdinal = useMemo(() => phaseOrdinals(phases), [phases]);
  const files = useMemo(() => filesByBasename(steps), [steps]);
  const runSkills = useMemo(() => new Set(steps.map((s) => s.skill_name)), [steps]);

  // Built products by the skill that made them; those no step of this run
  // made sit under their phase's header.
  const built = useMemo(() => {
    const bySkill = new Map<string, ReplayProduct[]>();
    const byPhase = new Map<string, ReplayProduct[]>();
    const photographedBy = new Map<string, ReplayProduct[]>();
    for (const p of products) {
      if (!isRevealed(p)) continue;
      const own = p.producer && runSkills.has(p.producer) ? p.producer : null;
      push(own ? bySkill : byPhase, own ?? p.phase, p);
      const takers = new Set((p.previews ?? []).map((pv) => pv.captured_by).filter(Boolean) as string[]);
      for (const taker of takers) if (taker !== own) push(photographedBy, taker, p);
    }
    return { bySkill, byPhase, photographedBy };
  }, [products, isRevealed, runSkills]);
  const builtCount = products.filter(isRevealed).length;

  // Follow the replay down the chain. A step keeps its card in view; a new
  // phase goes to the TOP, so the chapter heading is what the audience sees
  // first and its steps fill in below it — "nearest" parked the heading on
  // the rail's bottom edge.
  const beatPhase = replay.beat.event?.kind === "phase_start" ? replay.beat.phase : null;
  useEffect(() => {
    if (beatPhase) {
      phaseRefs.current.get(beatPhase)?.scrollIntoView?.({ block: "start", behavior: "smooth" });
      return;
    }
    const target = current ? cardRefs.current.get(current) : endRef.current;
    target?.scrollIntoView?.({ block: "nearest", behavior: "smooth" });
  }, [current, beatPhase, entries.length]);

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
  const reachedFile = (path: string): RunFile | null => {
    const file = files.get(basename(path));
    return file && replay.reveal.done.has(file.skill) ? file : null;
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

  if (!flow) return <Shell>Flow isn't available for this run.</Shell>;
  if (entries.length === 0) {
    return <Shell>Step through the run to watch what each step takes in and puts out.</Shell>;
  }

  return (
    <div className="flex h-full flex-col overflow-y-auto px-3 py-3 text-xs">
      <div className="mb-2 flex items-baseline justify-between px-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
        <span>Flow</span>
        {products.length > 0 && (
          <span className="tabular-nums">
            Built so far · {builtCount}/{products.length}
          </span>
        )}
      </div>
      <ol className="flex flex-col">
        {entries.map((entry) => {
          if (entry.type === "phase") {
            const phaseBuilt = built.byPhase.get(entry.phase) ?? [];
            return (
              <li
                key={`phase-${entry.phase}`}
                ref={(el) => {
                  if (el) phaseRefs.current.set(entry.phase, el);
                  else phaseRefs.current.delete(entry.phase);
                }}
                className="mb-1.5 mt-3 scroll-mt-2 px-1 first:mt-0"
              >
                <div className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                  {phaseTag(entry.phase) && `${phaseTag(entry.phase)} · `}
                  <Glossed text={entry.label} />
                </div>
                {phaseBuilt.length > 0 && (
                  <BuiltList title="Built in this phase" products={phaseBuilt} fresh={justRevealed} />
                )}
              </li>
            );
          }
          const { skill } = entry;
          const io = flow[skill] ?? { inputs: [], outputs: [] };
          const isCurrent = skill === current;
          const open = isCurrent || opened.has(skill);
          const done = replay.reveal.done.has(skill);
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
                  done ? "border-primary bg-primary" : "border-primary bg-background",
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
                  {!open && (
                    <span className="shrink-0 text-[10px] tabular-nums text-muted-foreground">
                      {io.inputs.length} in · {io.outputs.length} out
                    </span>
                  )}
                </button>
                {/* What a step built stays on its card when the card folds —
                    it is what the rail is for; only the inputs/outputs fold. */}
                {(made.length > 0 || photographed.length > 0) && (
                  <div className="flex flex-col gap-2 border-t border-border/60 px-2 py-2">
                    {made.length > 0 && <BuiltList title="Built" products={made} fresh={justRevealed} />}
                    {photographed.length > 0 && (
                      <BuiltList title="Photographed" products={photographed} fresh={justRevealed} />
                    )}
                  </div>
                )}
                {open && (
                  <SkillIo
                    io={io}
                    skill={skill}
                    label={label}
                    phaseTag={phaseTag}
                    phaseOrdinal={phaseOrdinal}
                    fileFor={(path, direction) =>
                      direction === "output" && !done ? null : reachedFile(path)
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
      <div ref={endRef} />
      {/* Room for the run still to come. Without it the newest entry is the
          last thing in the rail, and a new phase heading can never scroll
          above the rail's bottom edge. */}
      <div aria-hidden className="h-[60vh] shrink-0" />
      <p className="mt-auto border-t border-border px-1 pt-2 text-[10px] leading-snug text-muted-foreground/70">
        As the ACE plugin declares it — what each step is built to read and write, not a trace of
        this run's reads.
      </p>
    </div>
  );
}

function BuiltList({
  title,
  products,
  fresh,
}: {
  title: string;
  products: readonly ReplayProduct[];
  fresh: ReadonlySet<string>;
}) {
  return (
    <section className="mt-1">
      <h4 className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
        {title}
      </h4>
      <ul className="flex flex-col gap-1">
        {products.map((p) => (
          <li key={p.id}>
            <ProductCard product={p} fresh={fresh.has(p.id)} quiet />
          </li>
        ))}
      </ul>
    </section>
  );
}

function push<K, V>(m: Map<K, V[]>, key: K, value: V) {
  const arr = m.get(key);
  if (arr) arr.push(value);
  else m.set(key, [value]);
}

function Shell({ children }: { children: React.ReactNode }) {
  return <div className="p-4 text-xs text-muted-foreground">{children}</div>;
}
