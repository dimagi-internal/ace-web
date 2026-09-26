import { useMemo } from "react";
import { ArrowDownToLine, ArrowUpFromLine, Inbox } from "lucide-react";

import type { FlowInput, SkillFlow } from "@/api/replay";
import type { Artifact, PhaseInfo, Step } from "@/api/types.ws";
import { Glossed } from "@/components/glossary/Glossed";
import { useViewer } from "@/components/viewers/ViewerContext";

import type { Replay } from "./useReplay";

interface Props {
  replay: Replay;
  /** REAL steps (not as-of-cursor) — to find the run's actual file for an input. */
  steps: readonly Step[];
  phases: readonly PhaseInfo[];
}

/**
 * How the work flows: what the current step TOOK IN, from which earlier step,
 * and what it HANDED ON, to which later ones.
 *
 * This is the part of ACE that is hardest to see and most worth seeing — the
 * PDD written in Phase 1 is what Nova builds the apps from in Phase 3, which
 * is what the training deck screenshots in Phase 6. It comes from the plugin's
 * artifact manifest (`producedBy` / `consumedBy`), so it is the DECLARED flow,
 * and the panel says so.
 *
 * An input links to the run's real file once the cursor has passed the step
 * that made it.
 */
export function FlowPanel({ replay, steps, phases }: Props) {
  const viewer = useViewer();
  const flow = replay.timeline?.flow;
  const skill = replay.beat.skill;
  const phase = replay.beat.phase;

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

  // A phase-start beat has no skill: show what the phase as a whole takes in
  // from earlier phases.
  const shown: SkillFlow | null = useMemo(() => {
    if (!flow) return null;
    if (skill) return flow[skill] ?? null;
    if (!phase || !replay.timeline) return null;
    const skills = replay.timeline.ladder.find((l) => l.phase === phase)?.steps.map((s) => s.skill) ?? [];
    const seen = new Set<string>();
    const inputs: FlowInput[] = [];
    for (const s of skills) {
      for (const i of flow[s]?.inputs ?? []) {
        if (i.producer_phase === phase || seen.has(i.path)) continue;
        seen.add(i.path);
        inputs.push(i);
      }
    }
    return { inputs, outputs: [] };
  }, [flow, skill, phase, replay.timeline]);

  const label = (s: string | null | undefined) =>
    s === "external" ? "your inputs" : (viewer?.skillLabel(s) ?? s ?? "");
  const phaseTag = (p: string | null | undefined) => {
    const n = p ? phaseOrdinal.get(p) : undefined;
    return n != null ? `Phase ${n}` : null;
  };

  if (!flow) {
    return <Shell>Flow isn't available for this run.</Shell>;
  }
  if (!shown) {
    return <Shell>Step through the run to see what each step takes in and hands on.</Shell>;
  }

  return (
    <div className="flex h-full flex-col gap-4 overflow-y-auto p-4 text-xs">
      <header>
        <div className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
          Flow
        </div>
        <div className="mt-0.5 text-sm font-semibold text-foreground">
          <Glossed
            text={
              skill
                ? label(skill)
                : (replay.timeline?.ladder.find((l) => l.phase === phase)?.phase_display ?? "")
            }
          />
        </div>
      </header>

      <section>
        <h4 className="mb-1.5 flex items-center gap-1.5 font-semibold text-foreground">
          <ArrowDownToLine className="h-3.5 w-3.5 text-sky-500" /> Took in
        </h4>
        {shown.inputs.length === 0 ? (
          <p className="text-muted-foreground">Nothing from earlier steps.</p>
        ) : (
          <ul className="flex flex-col gap-2">
            {shown.inputs.map((i) => {
              const file = filesByBasename.get(basename(i.path));
              const reached =
                !!file &&
                (replay.reveal.done.has(file.skill) || !replay.active);
              return (
                <li key={i.path} className="rounded border border-border/70 bg-card px-2 py-1.5">
                  <div className="flex items-center gap-1.5">
                    {i.producer === "external" && <Inbox className="h-3 w-3 text-muted-foreground" />}
                    {reached && viewer ? (
                      <button
                        type="button"
                        onClick={() =>
                          viewer.open({
                            type: "file",
                            fileId: file!.artifact.drive_file_id,
                            name: file!.artifact.name,
                            driveLink: file!.artifact.drive_web_link,
                            skill: file!.skill,
                          })
                        }
                        className="truncate font-mono text-[11px] text-primary hover:underline"
                        title="Open this file"
                      >
                        {basename(i.path)}
                      </button>
                    ) : (
                      <span className="truncate font-mono text-[11px] text-foreground">
                        {basename(i.path) || i.path}
                      </span>
                    )}
                  </div>
                  <div className="mt-0.5 text-[11px] text-muted-foreground">
                    from <Glossed text={label(i.producer)} />
                    {phaseTag(i.producer_phase) && ` · ${phaseTag(i.producer_phase)}`}
                  </div>
                  {i.description && (
                    <p className="mt-0.5 text-[11px] leading-snug text-muted-foreground/80">
                      <Glossed text={i.description} />
                    </p>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </section>

      {skill && (
        <section>
          <h4 className="mb-1.5 flex items-center gap-1.5 font-semibold text-foreground">
            <ArrowUpFromLine className="h-3.5 w-3.5 text-emerald-500" /> Handed on
          </h4>
          {shown.outputs.length === 0 ? (
            <p className="text-muted-foreground">No declared outputs.</p>
          ) : (
            <ul className="flex flex-col gap-2">
              {shown.outputs.map((o) => (
                <li key={o.path} className="rounded border border-border/70 bg-card px-2 py-1.5">
                  <div className="truncate font-mono text-[11px] text-foreground">
                    {basename(o.path) || o.path}
                  </div>
                  {o.consumers.length === 0 ? (
                    <div className="mt-0.5 text-[11px] text-muted-foreground">
                      Read by no later step — a deliverable in its own right.
                    </div>
                  ) : (
                    <div className="mt-1 flex flex-wrap gap-1">
                      {o.consumers.map((c) => (
                        <span
                          key={c.skill}
                          className="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground"
                        >
                          → <Glossed text={label(c.skill)} />
                          {phaseTag(c.phase) && ` · ${phaseTag(c.phase)}`}
                        </span>
                      ))}
                    </div>
                  )}
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      <p className="mt-auto border-t border-border pt-2 text-[10px] leading-snug text-muted-foreground/70">
        As the ACE plugin declares it — what each step is built to read and write, not a
        trace of this run's reads.
      </p>
    </div>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  return <div className="p-4 text-xs text-muted-foreground">{children}</div>;
}

function basename(path: string): string {
  const trimmed = path.replace(/\/+$/, "");
  return trimmed.slice(trimmed.lastIndexOf("/") + 1);
}
