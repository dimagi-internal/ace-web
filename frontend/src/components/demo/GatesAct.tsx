import type { DemoGate } from "@/api/demo";

/**
 * What it caught.
 *
 * A demo that only shows success gets discounted by exactly the audiences
 * worth convincing, so the failures are the act rather than a footnote.
 * Every row here is a step whose own QA or judge refused to pass it.
 */
export function GatesAct({ gates }: { gates: readonly DemoGate[] }) {
  return (
    <div className="flex h-full flex-col gap-8 overflow-y-auto">
      <div>
        <div className="text-sm text-[var(--demo-dim)]">
          {gates.length === 1 ? "Step stopped by its own review" : "Steps stopped by their own review"}
        </div>
        <div className="text-6xl font-light leading-none tracking-tight sm:text-7xl">
          {gates.length}
        </div>
      </div>

      <ol className="flex w-full max-w-4xl flex-col gap-4">
        {gates.map((gate) => (
          <li
            key={`${gate.phase}-${gate.skill}`}
            className="border-l-2 border-[var(--demo-alert)] bg-[var(--demo-raised)] px-5 py-4"
          >
            <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1">
              <span className="text-lg">{gate.skill_display ?? gate.skill}</span>
              <span className="text-sm text-[var(--demo-dim)]">{gate.phase_display}</span>
            </div>

            {gate.judge?.score !== null && gate.judge?.score !== undefined && (
              <div className="mt-2 text-sm text-[var(--demo-alert)]">
                Scored {gate.judge.score}
              </div>
            )}
            {gate.judge?.rationale && (
              <p className="mt-2 max-w-[70ch] text-sm leading-relaxed text-[var(--demo-dim)]">
                {gate.judge.rationale}
              </p>
            )}
            {gate.qa_result?.failures && gate.qa_result.failures.length > 0 && (
              <ul className="mt-2 flex flex-col gap-1">
                {gate.qa_result.failures.slice(0, 6).map((failure, index) => (
                  <li key={index} className="max-w-[70ch] text-sm text-[var(--demo-dim)]">
                    {typeof failure === "string" ? failure : JSON.stringify(failure)}
                  </li>
                ))}
              </ul>
            )}
            {gate.error && (
              <p className="mt-2 max-w-[70ch] text-sm text-[var(--demo-dim)]">{gate.error}</p>
            )}
          </li>
        ))}
      </ol>
    </div>
  );
}
