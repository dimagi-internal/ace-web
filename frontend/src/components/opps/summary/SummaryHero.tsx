import { Badge } from "@/components/ui/badge";

import type { OppSummaryPayload } from "@/api/oppSummary";

interface Props {
  opp: OppSummaryPayload["opp"];
}

const STATUS_LABEL: Record<OppSummaryPayload["opp"]["status"], string> = {
  active: "Active",
  closed: "Closed",
  in_progress: "In progress",
};

function formatEndDate(iso: string | null): string | null {
  if (!iso) return null;
  // Tolerant of "YYYY-MM-DD" or full ISO.
  const d = new Date(iso.length > 10 ? iso : `${iso}T00:00:00`);
  if (Number.isNaN(d.valueOf())) return null;
  return d.toLocaleDateString(undefined, {
    year: "numeric", month: "long", day: "numeric",
  });
}

export function SummaryHero({ opp }: Props) {
  const formattedEnd = formatEndDate(opp.end_date);
  const subline =
    opp.status === "closed" && formattedEnd
      ? `Closed · ended ${formattedEnd}`
      : opp.status === "active" && formattedEnd
      ? `Active · ends ${formattedEnd}`
      : opp.status === "in_progress" && formattedEnd
      ? `In progress · target end ${formattedEnd}`
      : STATUS_LABEL[opp.status];

  return (
    <header className="border-b border-border">
      <div className="mx-auto max-w-3xl px-6 pt-16 pb-14">
        <div className="mb-6 flex items-center gap-3">
          <Badge variant={opp.status === "closed" ? "secondary" : "outline"}>
            {STATUS_LABEL[opp.status]}
          </Badge>
          {formattedEnd && (
            <span className="text-xs uppercase tracking-[0.18em] text-muted-foreground">
              {subline.replace(`${STATUS_LABEL[opp.status]} · `, "")}
            </span>
          )}
        </div>
        <h1 className="text-5xl font-semibold leading-[1.05] tracking-tight md:text-6xl">
          {opp.display_name}
        </h1>
        {opp.description && (
          <p className="mt-8 max-w-2xl text-lg leading-relaxed text-muted-foreground">
            {opp.description}
          </p>
        )}
      </div>
    </header>
  );
}
