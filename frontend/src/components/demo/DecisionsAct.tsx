import type { DemoDecisions } from "@/api/demo";

/**
 * What it decided.
 *
 * The overridden rows lead: they are the visible evidence that a person read
 * the agent's default and changed it, which is the thing an audience most
 * wants proof of.
 */
export function DecisionsAct({ decisions }: { decisions: DemoDecisions }) {
  const overridden = decisions.rows.filter((r) => r.status === "overridden");
  const defaults = decisions.rows.filter((r) => r.status !== "overridden");

  return (
    <div className="flex h-full flex-col gap-8 overflow-y-auto">
      <div className="flex flex-wrap gap-x-16 gap-y-6">
        <div>
          <div className="text-sm text-[var(--demo-dim)]">Decisions recorded</div>
          <div className="text-6xl font-light leading-none tracking-tight sm:text-7xl">
            {decisions.total}
          </div>
        </div>
        <div>
          <div className="text-sm text-[var(--demo-dim)]">Changed by a person</div>
          <div className="text-6xl font-light leading-none tracking-tight text-[var(--demo-dim)] sm:text-7xl">
            {decisions.overridden_count}
          </div>
        </div>
      </div>

      {overridden.length > 0 && (
        <ol className="flex w-full max-w-4xl flex-col gap-4">
          {overridden.map((row, index) => (
            <li
              key={row.row_id ?? index}
              className="border-l-2 border-[var(--demo-phase-1)] bg-[var(--demo-raised)] px-5 py-4"
            >
              <p className="max-w-[70ch] text-base">{row.question}</p>
              <div className="mt-2 flex flex-wrap gap-x-8 gap-y-1 text-sm">
                <span className="text-[var(--demo-dim)] line-through">{row.ai_default}</span>
                <span>{row.override}</span>
              </div>
              {row.override_reasoning && (
                <p className="mt-2 max-w-[70ch] text-sm leading-relaxed text-[var(--demo-dim)]">
                  {row.override_reasoning}
                </p>
              )}
            </li>
          ))}
        </ol>
      )}

      {defaults.length > 0 && (
        <ol className="flex w-full max-w-4xl flex-col gap-2">
          {defaults.map((row, index) => (
            <li
              key={row.row_id ?? index}
              className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1 border-b border-[var(--demo-rule)] pb-2 text-sm"
            >
              <span className="max-w-[60ch] text-[var(--demo-ink)]">{row.question}</span>
              <span className="text-[var(--demo-dim)]">{row.ai_default}</span>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
