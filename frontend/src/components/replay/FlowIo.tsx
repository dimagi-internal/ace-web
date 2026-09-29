import { ArrowDownToLine, ArrowUp, ArrowUpFromLine, Eye } from "lucide-react";

import type { FlowInput, FlowOutput, SkillFlow } from "@/api/replay";
import type { Artifact, PhaseInfo, Step } from "@/api/types.ws";
import { Glossed } from "@/components/glossary/Glossed";

/** A run file the viewer can open, and the step that wrote it. */
export interface RunFile {
  readonly artifact: Artifact;
  readonly skill: string;
}

interface Props {
  io: SkillFlow;
  /** This card's skill — an input it made itself gets no ↑. */
  skill: string;
  /** Display name for a skill (`"external"` → "your inputs"). */
  label: (skill: string | null | undefined) => string;
  /** "Phase 3" for a phase, or null. */
  phaseTag: (phase: string | null | undefined) => string | null;
  phaseOrdinal: ReadonlyMap<string, number>;
  /** The run's file for a declared path, when it may be opened. */
  fileFor: (path: string, direction: "input" | "output") => RunFile | null;
  /** Can the card that made this input be jumped to? */
  canJump: (producer: string) => boolean;
  onJump: (producer: string) => void;
  onOpen: (file: RunFile) => void;
}

/**
 * A step's declared **Inputs** (and which earlier step made each — ↑ jumps to
 * it) and **Outputs** (and which later phases use each). Shared by the
 * replay's growing chain and the Phases screen's per-phase rail.
 */
export function SkillIo({ io, skill, label, phaseTag, phaseOrdinal, fileFor, canJump, onJump, onOpen }: Props) {
  return (
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
            canJump={!!i.producer && i.producer !== skill && canJump(i.producer)}
            onJump={() => i.producer && onJump(i.producer)}
            file={fileFor(i.path, "input")}
            onOpen={onOpen}
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
            phases={usedInPhases(o, phaseOrdinal)}
            usedBy={o.consumers.map((c) => label(c.skill)).join(", ")}
            file={fileFor(o.path, "output")}
            onOpen={onOpen}
          />
        ))}
      </IoList>
    </div>
  );
}

/** Basename → the run's file, first writer wins. Declared paths and real
 *  paths differ in their folders across plugin versions; names don't. */
export function filesByBasename(steps: readonly Step[]): Map<string, RunFile> {
  const m = new Map<string, RunFile>();
  for (const s of steps) {
    for (const a of s.artifacts) {
      const base = basename(a.path || a.name);
      if (base && !m.has(base)) m.set(base, { artifact: a, skill: s.skill_name });
    }
  }
  return m;
}

export function phaseOrdinals(phases: readonly PhaseInfo[]): Map<string, number> {
  return new Map(phases.map((p) => [p.name, p.ordinal]));
}

export function basename(path: string): string {
  const trimmed = path.replace(/\/+$/, "");
  return trimmed.slice(trimmed.lastIndexOf("/") + 1);
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
  file: RunFile | null;
  onOpen: (f: RunFile) => void;
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
  file: RunFile | null;
  onOpen: (f: RunFile) => void;
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

/** "Phase 3", "Phase 5"… for the phases that read an output, in order. */
function usedInPhases(output: FlowOutput, ordinal: ReadonlyMap<string, number>): string[] {
  const nums = new Set<number>();
  for (const c of output.consumers) {
    const n = c.phase ? ordinal.get(c.phase) : undefined;
    if (n != null) nums.add(n);
  }
  return [...nums].sort((a, b) => a - b).map((n) => `Phase ${n}`);
}
