import type { OppSummaryPayload } from "@/api/oppSummary";

/**
 * The other half of the review surface: what ACE could NOT decide.
 *
 * Each item names an owner and where it gets answered, which is the
 * difference between "an unresolved question" and "an unassigned one".
 * The doc these come from is internal and unshared, so the content is
 * rendered here rather than hidden behind a link a partner can't open.
 */
export function OpenQuestionsList({
  items,
}: {
  items: NonNullable<OppSummaryPayload["open_questions"]>["items"];
}) {
  return (
    <ul className="divide-y divide-border">
      {items.map((q, i) => (
        <li key={`${q.title}-${i}`} className="py-3.5 first:pt-0 last:pb-0">
          {q.title && (
            <p className="text-[0.975rem] leading-[1.5] text-foreground">{q.title}</p>
          )}
          {q.detail && (
            <p className="mt-1 text-sm leading-[1.6] text-muted-foreground">{q.detail}</p>
          )}
          {(q.owner || q.answered_in) && (
            <dl className="mt-2 space-y-1 text-[13px] leading-[1.5]">
              {q.owner && (
                <div className="flex gap-2">
                  <dt className="w-24 shrink-0 text-[11px] uppercase tracking-[0.12em] text-muted-foreground/60">
                    Owner
                  </dt>
                  <dd className="text-muted-foreground">{q.owner}</dd>
                </div>
              )}
              {q.answered_in && (
                <div className="flex gap-2">
                  <dt className="w-24 shrink-0 text-[11px] uppercase tracking-[0.12em] text-muted-foreground/60">
                    Answered in
                  </dt>
                  <dd className="text-muted-foreground">{q.answered_in}</dd>
                </div>
              )}
            </dl>
          )}
        </li>
      ))}
    </ul>
  );
}
