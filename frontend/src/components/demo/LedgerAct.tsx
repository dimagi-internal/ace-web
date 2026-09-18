import { useMemo } from "react";

import type { DemoLedger } from "@/api/demo";

import { buildPhasePalette, phaseColor } from "./phaseColor";
import { duration } from "./time";

/**
 * Where the time went.
 *
 * Bars are the phase's measured SPAN — first start to last completion —
 * because the gaps between skills are real elapsed time and summing the
 * skills would quietly under-report them. The summed figure sits alongside
 * as "working", so neither number can be mistaken for the other.
 *
 * No tokens, no dollars. See the spec section of that name.
 */
export function LedgerAct({ ledger }: { ledger: DemoLedger }) {
  const palette = useMemo(
    () => buildPhasePalette(ledger.phases.map((p) => p.phase)),
    [ledger.phases],
  );
  const longest = Math.max(1, ...ledger.phases.map((p) => p.seconds ?? 0));

  return (
    <div className="flex h-full flex-col gap-8 overflow-y-auto">
      <div>
        <div className="text-sm text-[var(--demo-dim)]">Start to finish, unattended</div>
        <div className="text-6xl font-light leading-none tracking-tight sm:text-7xl">
          {duration(ledger.wall_seconds)}
        </div>
      </div>

      <ol className="flex w-full max-w-5xl flex-col gap-5">
        {ledger.phases.map((phase) => {
          const color = phaseColor(palette, phase.phase);
          const share = (phase.seconds ?? 0) / longest;
          return (
            <li key={phase.phase}>
              <div className="mb-1.5 flex items-baseline justify-between gap-4">
                <span className="text-base" style={{ color }}>
                  {phase.phase_display}
                </span>
                <span className="flex shrink-0 items-baseline gap-3 text-sm">
                  <span className="text-[var(--demo-ink)]">{duration(phase.seconds)}</span>
                  {phase.active_seconds !== null &&
                    phase.seconds !== null &&
                    phase.active_seconds < phase.seconds - 60 && (
                      <span className="text-[var(--demo-dim)]">
                        {duration(phase.active_seconds)} working
                      </span>
                    )}
                </span>
              </div>
              <div className="h-2.5 w-full overflow-hidden rounded-xs bg-[var(--demo-raised)]">
                <div
                  className="h-full"
                  style={{
                    width: `${Math.max(share * 100, 0.8)}%`,
                    background: color,
                  }}
                />
              </div>
              <div className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 text-xs text-[var(--demo-dim)]">
                {phase.skills.map((skill) => (
                  <span key={skill.skill}>
                    {skill.skill_display}
                    {skill.seconds !== null && ` ${duration(skill.seconds)}`}
                  </span>
                ))}
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
