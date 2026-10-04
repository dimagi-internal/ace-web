import type { OppSummaryPayload } from "@/api/oppSummary";

type OpenQuestion = NonNullable<OppSummaryPayload["open_questions"]>["items"][number];

const DT_CLASS =
  "w-24 shrink-0 text-[11px] uppercase tracking-[0.12em] text-muted-foreground/60";

/**
 * The other half of the review surface: what ACE could NOT decide.
 *
 * Each item names an owner and where it gets answered, which is the
 * difference between "an unresolved question" and "an unassigned one".
 * The doc these come from is internal and unshared, so the content is
 * rendered here rather than hidden behind a link a partner can't open.
 *
 * ## Outsiders (`plain`) read the question, not ACE's working notes
 *
 * A row's `detail` is the ledger's `latest:` — ACE's own audit trail
 * (run ids, form ids, XML binds, skill names). For a non-member it moves
 * behind a collapsed "Working notes" disclosure with `raised_by` and the
 * original `blocking` text; "Needed by" reads the plain `needed_by` and
 * says when that stage has already run. Rows are grouped into "Questions
 * for you" and "Questions Dimagi is resolving" (collapsed) by the
 * payload's `for_reviewer` — the rule lives server-side
 * (`summary._owner_is_internal`). Members keep the flat raw view.
 */
export function OpenQuestionsList({
  items,
  plain = false,
}: {
  items: OpenQuestion[];
  /** A non-member reader: group the rows and tuck the working notes away. */
  plain?: boolean;
}) {
  if (!plain) return <QuestionRows items={items} plain={false} />;

  // Absent `for_reviewer` (a payload cached before it shipped) counts as
  // the reviewer's — a question is never hidden on a guess.
  const forYou = items.filter((q) => q.for_reviewer !== false);
  const dimagis = items.filter((q) => q.for_reviewer === false);
  return (
    <div className="space-y-8">
      {forYou.length > 0 && (
        <section>
          <GroupHeading label="Questions for you" count={forYou.length} />
          <QuestionRows items={forYou} plain />
        </section>
      )}
      {dimagis.length > 0 && (
        <details>
          <summary className="cursor-pointer select-none">
            <GroupHeading
              label="Questions Dimagi is resolving"
              count={dimagis.length}
              inline
            />
          </summary>
          <p className="mb-3 mt-2 text-sm leading-[1.6] text-muted-foreground">
            Nothing is needed from you on these — they are listed so you can see what is
            still open.
          </p>
          <QuestionRows items={dimagis} plain />
        </details>
      )}
    </div>
  );
}

function GroupHeading({
  label,
  count,
  inline = false,
}: {
  label: string;
  count: number;
  inline?: boolean;
}) {
  const Tag = inline ? "span" : "h3";
  return (
    <Tag
      className={`${inline ? "inline-flex" : "mb-3 flex"} items-baseline gap-2 text-[11px] font-medium uppercase tracking-[0.16em] text-foreground`}
    >
      {label}
      <span className="tabular-nums text-muted-foreground">({count})</span>
    </Tag>
  );
}

function QuestionRows({ items, plain }: { items: OpenQuestion[]; plain: boolean }) {
  return (
    <ul className="divide-y divide-border">
      {items.map((q, i) => {
        // An unparseable row has no title; its whole text is the detail,
        // and that IS the question — never tuck it away.
        const text = plain ? q.title || q.detail : q.title;
        const notes = plain && q.title ? q.detail : "";
        const neededBy = plain ? q.needed_by || q.blocking : q.blocking;
        const originalDeadline =
          plain && q.blocking && q.blocking !== neededBy ? q.blocking : null;
        const hasNotes = plain && Boolean(notes || q.raised_by || originalDeadline);
        return (
          <li key={`${q.title}-${i}`} className="py-3.5 first:pt-0 last:pb-0">
            {text && (
              <p className="text-[0.975rem] leading-[1.5] text-foreground">{text}</p>
            )}
            {!plain && q.detail && (
              <p className="mt-1 text-sm leading-[1.6] text-muted-foreground">{q.detail}</p>
            )}
            {(q.owner || q.answered_in || neededBy) && (
              <dl className="mt-2 space-y-1 text-[13px] leading-[1.5]">
                {q.owner && (
                  <div className="flex gap-2">
                    <dt className={DT_CLASS}>Owner</dt>
                    <dd className="text-muted-foreground">{q.owner}</dd>
                  </div>
                )}
                {q.answered_in && (
                  <div className="flex gap-2">
                    <dt className={DT_CLASS}>Answered in</dt>
                    <dd className="text-muted-foreground">{q.answered_in}</dd>
                  </div>
                )}
                {/* When it has to be answered by. The ledger has always
                    carried this; the reader never saw it, so a question
                    gating Phase 8 looked the same as a post-pilot one. */}
                {neededBy && (
                  <div className="flex gap-2">
                    <dt className={DT_CLASS}>Needed by</dt>
                    <dd className="text-muted-foreground">
                      {neededBy}
                      {plain && q.overdue && (
                        <span className="text-status-warn">
                          {" "}— that stage has already run, so this is now overdue
                        </span>
                      )}
                    </dd>
                  </div>
                )}
              </dl>
            )}
            {hasNotes && (
              <details className="mt-2 text-[13px] leading-[1.6]">
                <summary className="cursor-pointer select-none text-muted-foreground/80 hover:text-foreground">
                  Working notes
                </summary>
                <div className="mt-1.5 space-y-1 border-l border-border pl-3 text-muted-foreground">
                  <p className="text-[12px] text-muted-foreground/70">
                    ACE's own notes on this question — not needed to answer it.
                  </p>
                  {notes && <p>{notes}</p>}
                  {q.raised_by && <p>Raised by: {q.raised_by}</p>}
                  {originalDeadline && <p>ACE's deadline: {originalDeadline}</p>}
                </div>
              </details>
            )}
          </li>
        );
      })}
    </ul>
  );
}
