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
  const d = new Date(iso.length > 10 ? iso : `${iso}T00:00:00`);
  if (Number.isNaN(d.valueOf())) return null;
  return d.toLocaleDateString(undefined, {
    year: "numeric", month: "long", day: "numeric",
  });
}

const STATUS_DOT_COLOR: Record<OppSummaryPayload["opp"]["status"], string> = {
  active: "var(--status-ok)",
  in_progress: "var(--status-warn)",
  closed: "var(--muted-foreground)",
};

const STATUS_DATE_PREFIX: Record<OppSummaryPayload["opp"]["status"], string> = {
  active: "Ends",
  in_progress: "Target end",
  closed: "Ended",
};

/**
 * Hero block — status pill (with a colored status dot prefix), opp
 * display name, and the first prose paragraph from the input PDD.
 *
 * The dot is a static colored circle (not animated) using the project's
 * ``--status-ok`` token; matches the way Connect treats live state in
 * its own headers.
 */
export function SummaryHero({ opp }: Props) {
  const formattedEnd = formatEndDate(opp.end_date);

  return (
    <header className="border-b border-border">
      <div className="mx-auto max-w-3xl px-6 pt-16 pb-14">
        <div className="mb-6 flex items-center gap-4 text-xs">
          <span
            className="inline-flex items-center gap-1.5 rounded-full border border-border bg-card/50 px-2.5 py-1 font-medium text-foreground"
            aria-label={`Status: ${STATUS_LABEL[opp.status]}`}
          >
            <span
              className="size-1.5 rounded-full"
              style={{ backgroundColor: STATUS_DOT_COLOR[opp.status] }}
              aria-hidden
            />
            {STATUS_LABEL[opp.status]}
          </span>
          {formattedEnd && (
            <span className="uppercase tracking-[0.2em] text-muted-foreground">
              {STATUS_DATE_PREFIX[opp.status]} {formattedEnd}
            </span>
          )}
        </div>
        <h1 className="text-balance text-5xl font-semibold leading-[1.05] tracking-tight md:text-6xl">
          {opp.display_name}
        </h1>
        {opp.description && (
          <p className="mt-8 max-w-2xl text-pretty text-lg leading-[1.7] text-muted-foreground">
            {opp.description}
          </p>
        )}
      </div>
    </header>
  );
}
