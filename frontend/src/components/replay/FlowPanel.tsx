import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowDownToLine, ArrowUp, ArrowUpFromLine, Eye } from "lucide-react";

import type { FlowInput, FlowOutput } from "@/api/replay";
import type { Artifact, PhaseInfo, Step } from "@/api/types.ws";
import { Glossed } from "@/components/glossary/Glossed";
import { useViewer } from "@/components/viewers/ViewerContext";
import { cn } from "@/lib/utils";

import type { Replay } from "./useReplay";

interface Props {
  replay: Replay;
  /** REAL steps (not as-of-cursor) — to find the run's actual file for a path. */
  steps: readonly Step[];
  phases: readonly PhaseInfo[];
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
 * The current step's card is open — its **Inputs** (and which earlier step
 * made each) and its **Outputs** (and which later phases use each). Earlier
 * cards fold to one line so the chain stays readable. An input made by an
 * earlier step carries ↑: click it and the panel scrolls back to the card
 * that made it and flashes it, so "the PDD from Phase 1 is what Phase 3
 * builds the apps from" is something you can watch, not something the
 * presenter has to assert.
 *
 * Data is the plugin's artifact manifest (`producedBy` / `consumedBy`), so it
 * is the DECLARED flow, and the footer says so. A file opens in the viewer
 * once the cursor has passed the step that wrote it.
 */
export function FlowPanel({ replay, steps, phases }: Props) {
  const viewer = useViewer();
  const flow = replay.timeline?.flow;
  const current = replay.beat.skill;
  const [opened, setOpened] = useState<ReadonlySet<string>>(new Set());
  const [flash, setFlash] = useState<string | null>(null);
  const cardRefs = useRef(new Map<string, HTMLElement>());
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

  const phaseOrdinal = useMemo(() => new Map(phases.map((p) => [p.name, p.ordinal])), [phases]);
  const filesByBasename = useMemo(() => {
    const m = new Map<string, { artifact: Artifact; skill: string }>();
    for (const s of steps) {
      for (const a of s.artifacts) {
        const base = basename(a.path || a.name);
        if (base && !m.has(base)) m.set(base, { artifact: a, skill: s.skill_name });
      }
    }
    return m;
  }, [steps]);

  // Follow the replay down the chain.
  useEffect(() => {
    const target = current ? cardRefs.current.get(current) : endRef.current;
    target?.scrollIntoView?.({ block: "nearest", behavior: "smooth" });
  }, [current, entries.length]);

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
  const reachedFile = (path: string) => {
    const file = filesByBasename.get(basename(path));
    return file && replay.reveal.done.has(file.skill) ? file : null;
  };
  const openFile = (file: { artifact: Artifact; skill: string }) =>
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
      <div className="mb-2 px-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
        Flow
      </div>
      <ol className="flex flex-col">
        {entries.map((entry) => {
          if (entry.type === "phase") {
            return (
              <li
                key={`phase-${entry.phase}`}
                className="mb-1.5 mt-3 px-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground first:mt-0"
              >
                {phaseTag(entry.phase) && `${phaseTag(entry.phase)} · `}
                <Glossed text={entry.label} />
              </li>
            );
          }
          const { skill } = entry;
          const io = flow[skill] ?? { inputs: [], outputs: [] };
          const isCurrent = skill === current;
          const open = isCurrent || opened.has(skill);
          const done = replay.reveal.done.has(skill);
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
                {open && (
                  <div className="flex flex-col gap-2 border-t border-border/60 px-2 py-2">
                    <IoList
                      title="Inputs"
                      icon={<ArrowDownToLine className="h-3 w-3 text-sky-500" />}
                      empty="Nothing from earlier steps."
                    >
                      {io.inputs.map((i) => (
                        <InputRow
                          key={i.path}
                          input={i}
                          from={label(i.producer)}
                          phase={phaseTag(i.producer_phase)}
                          canJump={!!i.producer && onScreen.has(i.producer) && i.producer !== skill}
                          onJump={() => i.producer && jumpTo(i.producer)}
                          file={reachedFile(i.path)}
                          onOpen={openFile}
                        />
                      ))}
                    </IoList>
                    <IoList
                      title="Outputs"
                      icon={<ArrowUpFromLine className="h-3 w-3 text-emerald-500" />}
                      empty="No declared outputs."
                    >
                      {io.outputs.map((o) => (
                        <OutputRow
                          key={o.path}
                          output={o}
                          phases={[...new Set(o.consumers.map((c) => phaseTag(c.phase)).filter(Boolean))] as string[]}
                          usedBy={o.consumers.map((c) => label(c.skill)).join(", ")}
                          file={done ? reachedFile(o.path) : null}
                          onOpen={openFile}
                        />
                      ))}
                    </IoList>
                  </div>
                )}
              </div>
            </li>
          );
        })}
      </ol>
      <div ref={endRef} />
      <p className="mt-auto border-t border-border px-1 pt-2 text-[10px] leading-snug text-muted-foreground/70">
        As the ACE plugin declares it — what each step is built to read and write, not a trace of
        this run's reads.
      </p>
    </div>
  );
}

function IoList({
  title,
  icon,
  empty,
  children,
}: {
  title: string;
  icon: React.ReactNode;
  empty: string;
  children: React.ReactNode[];
}) {
  return (
    <section>
      <h4 className="mb-1 flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
        {icon}
        {title}
      </h4>
      {children.length === 0 ? (
        <p className="text-[11px] text-muted-foreground">{empty}</p>
      ) : (
        <ul className="flex flex-col gap-1">{children}</ul>
      )}
    </section>
  );
}

function InputRow({
  input,
  from,
  phase,
  canJump,
  onJump,
  file,
  onOpen,
}: {
  input: FlowInput;
  from: string;
  phase: string | null;
  canJump: boolean;
  onJump: () => void;
  file: { artifact: Artifact; skill: string } | null;
  onOpen: (f: { artifact: Artifact; skill: string }) => void;
}) {
  return (
    <li className="flex items-start gap-1" title={input.description || undefined}>
      <div className="min-w-0 flex-1">
        <div className="truncate font-mono text-[11px] text-foreground">{basename(input.path) || input.path}</div>
        <div className="truncate text-[10px] text-muted-foreground">
          from <Glossed text={from} />
          {phase && ` · ${phase}`}
        </div>
      </div>
      {file && <IconButton label="Open this file" onClick={() => onOpen(file)} icon={<Eye className="h-3 w-3" />} />}
      {canJump && (
        <IconButton
          label={`Show where it was made (${from})`}
          onClick={onJump}
          icon={<ArrowUp className="h-3 w-3" />}
        />
      )}
    </li>
  );
}

function OutputRow({
  output,
  phases,
  usedBy,
  file,
  onOpen,
}: {
  output: FlowOutput;
  phases: string[];
  usedBy: string;
  file: { artifact: Artifact; skill: string } | null;
  onOpen: (f: { artifact: Artifact; skill: string }) => void;
}) {
  return (
    <li className="flex items-start gap-1" title={output.description || undefined}>
      <div className="min-w-0 flex-1">
        <div className="truncate font-mono text-[11px] text-foreground">{basename(output.path) || output.path}</div>
        <div className="truncate text-[10px] text-muted-foreground" title={usedBy ? `Used by ${usedBy}` : undefined}>
          {phases.length > 0 ? `→ used in ${phases.join(", ")}` : "a deliverable in its own right"}
        </div>
      </div>
      {file && <IconButton label="Open this file" onClick={() => onOpen(file)} icon={<Eye className="h-3 w-3" />} />}
    </li>
  );
}

function IconButton({ label, onClick, icon }: { label: string; onClick: () => void; icon: React.ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={label}
      aria-label={label}
      className="mt-0.5 shrink-0 rounded border border-border p-0.5 text-muted-foreground hover:bg-accent hover:text-foreground"
    >
      {icon}
    </button>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  return <div className="p-4 text-xs text-muted-foreground">{children}</div>;
}

function basename(path: string): string {
  const trimmed = path.replace(/\/+$/, "");
  return trimmed.slice(trimmed.lastIndexOf("/") + 1);
}
