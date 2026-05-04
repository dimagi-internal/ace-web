import type { Gate } from "../../api/types";

export function GateHistory({ gates }: { gates: Gate[] }) {
  if (gates.length === 0) return null;
  return (
    <div className="rounded bg-card p-2.5">
      <div className="text-[11px] uppercase tracking-wider text-muted-foreground">Gate history</div>
      <ul className="mt-1 flex flex-col gap-0.5 text-[11px] text-muted-foreground">
        {gates.map((g, i) => (
          <li key={`${g.ts}-${i}`}>
            <span title={g.ts}>{prettyTs(g.ts)}</span>{" "}
            <span className={gateTone(g.decision)}>{g.decision}</span>
            {g.decided_by && <span className="text-muted-foreground"> · {g.decided_by}</span>}
            {g.note && <span className="text-muted-foreground"> — {g.note}</span>}
          </li>
        ))}
      </ul>
    </div>
  );
}

function prettyTs(ts: string): string {
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return ts;
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function gateTone(decision: string): string {
  if (decision === "approved") return "text-green-400";
  if (decision === "rejected") return "text-red-400";
  return "text-amber-400";
}
