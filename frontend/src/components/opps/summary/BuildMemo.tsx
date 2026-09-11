import { AlertTriangle, ArrowUpRight, ChevronRight } from "lucide-react";

import type { OppSummaryPayload } from "@/api/oppSummary";
import { MarkdownRenderer } from "@/components/MarkdownRenderer";
import { AccessUnknownTag, AdminOnlyTag } from "@/components/opps/summary/SummaryRow";

type Memo = NonNullable<OppSummaryPayload["build_memo"]>;

export interface MemoSection {
  /** The `## ` heading line, verbatim (escapes and all). */
  heading: string;
  /** The heading as plain text, for a `<summary>` label. */
  label: string;
  body: string;
}

export interface SplitMemo {
  /** Everything before the first `## ` — the intro and "How to review". */
  lead: string;
  sections: MemoSection[];
}

const H1 = /^ {0,3}#[ \t]+\S/;
const H2 = /^ {0,3}##[ \t]+(.*?)[ \t#]*$/;
const FENCE = /^ {0,3}(`{3,}|~{3,})/;
// CommonMark's escapable punctuation. Drive's markdown export escapes
// liberally (`1\.`, `\[ACE\]`); a heading used as a plain-text label has
// no renderer to resolve them, so they are resolved here.
const ESCAPE = /\\([!-/:-@[-`{-~])/g;

function plainLabel(text: string): string {
  return text.replace(ESCAPE, "$1").replace(/\*\*|__|`/g, "").trim();
}

/**
 * Cut the memo at its `## ` headings.
 *
 * The memo's structure is fixed by ACE's `skills/build-memo` (Process step
 * 2): an H1 title, an intro, "How to review", then `## 1.` — the table a
 * reviewer works through — and `## 2.`–`## 5.`, which the memo itself
 * calls "the producers' own memos, for context". So section 1 stays open
 * and the rest fold, and nothing is dropped: a memo with no `## ` at all
 * renders whole, as `lead`.
 *
 * The leading H1 is removed because the page already names the
 * opportunity and the run directly above it. Headings inside a fenced
 * code block are not headings.
 */
export function splitMemo(body: string): SplitMemo {
  const lines = body.replace(/\r\n?/g, "\n").split("\n");
  let start = 0;
  while (start < lines.length && !lines[start].trim()) start++;
  if (start < lines.length && H1.test(lines[start])) start++;

  const lead: string[] = [];
  const sections: MemoSection[] = [];
  let fence: string | null = null;
  for (const line of lines.slice(start)) {
    const f = FENCE.exec(line);
    if (f) {
      const marker = f[1][0];
      fence = fence === null ? marker : fence === marker ? null : fence;
    }
    const h = fence === null && !f ? H2.exec(line) : null;
    if (h) {
      sections.push({ heading: line, label: plainLabel(h[1]), body: "" });
      continue;
    }
    if (sections.length) {
      const cur = sections[sections.length - 1];
      cur.body += `${line}\n`;
    } else {
      lead.push(line);
    }
  }
  return { lead: lead.join("\n").trim(), sections };
}

/**
 * What the memo itself says it is missing — shown ABOVE the memo, never
 * folded into it, so a memo with gaps can't be read as a complete one.
 * `complete: false` with no gaps recorded still says so; `complete: null`
 * with no gaps says nothing, because the run said nothing.
 */
function MemoGaps({ memo }: { memo: Memo }) {
  if (memo.complete !== false && memo.gaps.length === 0) return null;
  return (
    <div className="mb-6 rounded-lg border border-amber-500/30 bg-amber-500/[0.06] p-4">
      <h3 className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-[0.16em] text-amber-400">
        <AlertTriangle size={13} />
        This memo is incomplete
      </h3>
      {memo.gaps.length > 0 ? (
        <>
          <p className="mt-1.5 text-sm leading-[1.6] text-muted-foreground">
            ACE could not compose every part of it. What is missing:
          </p>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-sm leading-[1.5] text-foreground">
            {memo.gaps.map((g) => (
              <li key={g}>{g}</li>
            ))}
          </ul>
        </>
      ) : (
        <p className="mt-1.5 text-sm leading-[1.6] text-muted-foreground">
          ACE marked it incomplete without recording what is missing.
        </p>
      )}
    </div>
  );
}

export function BuildMemo({
  memo,
  showAccessTags,
}: {
  memo: Memo;
  showAccessTags: boolean;
}) {
  const split = memo.body ? splitMemo(memo.body) : null;
  const [open, ...folded] = split?.sections ?? [];

  return (
    <div>
      <MemoGaps memo={memo} />

      {split ? (
        <>
          {split.lead && <MarkdownRenderer content={split.lead} />}
          {open && <MarkdownRenderer content={`${open.heading}\n${open.body}`} />}
          {folded.map((s) => (
            <details
              key={s.heading}
              className="group/memo border-t border-border [&:last-of-type]:border-b"
            >
              <summary className="flex cursor-pointer list-none items-center gap-2 py-3 text-sm font-medium text-foreground [&::-webkit-details-marker]:hidden">
                <ChevronRight
                  size={14}
                  className="shrink-0 text-muted-foreground transition-transform group-open/memo:rotate-90"
                />
                {s.label}
              </summary>
              <div className="pb-4 pl-6">
                <MarkdownRenderer content={s.body} />
              </div>
            </details>
          ))}
        </>
      ) : (
        <p className="text-[0.975rem] leading-[1.7] text-muted-foreground">
          The memo's text could not be loaded here. It is still in Google Docs.
        </p>
      )}

      {/* The secondary way in. Rendered outside `SummaryRow`, so it carries
          both tag cases itself — an untagged link reads as "anyone can open
          this", which is the ace-web#740 bug. */}
      <p className="mt-4 flex items-center justify-end gap-2 text-sm">
        <a
          href={memo.url}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-1 font-medium text-foreground underline-offset-4 hover:underline"
        >
          Open in Google Docs
          <ArrowUpRight size={14} strokeWidth={2} className="opacity-60" />
        </a>
        {showAccessTags && memo.access === "admin" && <AdminOnlyTag />}
        {showAccessTags && memo.access === "unknown" && <AccessUnknownTag />}
      </p>
    </div>
  );
}
