import type { OppSummaryPayload } from "@/api/oppSummary";

type DeepQa = NonNullable<OppSummaryPayload["deep_qa"]>;
type Stage = DeepQa["stages"][number];

/**
 * How each `gate.disposition` reads to someone who has never seen
 * `lib/verdict-schema.ts`. Same rule as `BUILD_STATUS_LABELS` and
 * `DDD_TERMINAL_STATUS_LABELS`: a value we do not recognise is rendered
 * VERBATIM rather than swallowed, because a disposition we have not
 * heard of must not become silence.
 *
 * Deliberately not collapsed to pass/fail. `iterate` and `reject` are
 * both "not cleared", and they are not the same thing to someone
 * deciding whether to wait a week or rethink the design.
 */
const GATE_LABELS: Record<string, string> = {
  approve: "cleared the deep gate",
  iterate: "has not cleared the deep gate — it needs another pass",
  reject: "did not clear the deep gate",
};

function gateSentence(stage: Stage): string {
  if (!stage.gate) return "ran, but recorded no gate decision";
  return GATE_LABELS[stage.gate] ?? `gate: ${stage.gate}`;
}

function formatDate(iso: string | null): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.valueOf())) return iso;
  return d.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

/**
 * The score, and the reason the score is not the answer.
 *
 * A deep pass is "overall >= threshold AND zero failures". Those two
 * conditions come apart, and when they do the page has to say so in the
 * same breath as the number — otherwise the number is the only thing a
 * reader takes away. On `spark-facilitator/20260828-0703` Stage A is
 * 8.03 against a 7.0 bar with two failures, and the gate is `iterate`.
 */
function ScoreLine({ stage }: { stage: Stage }) {
  if (stage.score == null) return null;
  const { total, pass, warn, fail } = stage.counts;
  return (
    <p className="mt-1">
      Scored {stage.score} out of 10
      {stage.threshold != null && ` against a ${stage.threshold} bar`}
      {total > 0 && (
        <>
          {", over "}
          {total} {total === 1 ? "check" : "checks"}
          {": "}
          {pass} passed
          {warn > 0 && `, ${warn} flagged`}
          {fail > 0 && `, ${fail} failed`}
        </>
      )}
      {"."}
      {fail > 0 && stage.threshold != null && stage.score >= stage.threshold && (
        <span className="text-foreground">
          {" "}
          The score clears the bar and the gate still does not: a deep pass
          needs zero failures.
        </span>
      )}
    </p>
  );
}

/**
 * What the verdict was measured against.
 *
 * A verdict produced before the current released build, or the current
 * published chatbot version, is not evidence about what is deployed now
 * — which is why Phase 9 `llo-launch` refuses activation on a stale one.
 *
 * When the payload carries no comparison the page says nothing about
 * freshness and shows the date instead. That is not an oversight: the
 * server emits a comparison only when it has both sides, and a
 * freshness claim that can be wrong is worse than none, because "fresh"
 * is the claim a reader would act on.
 */
function FreshnessLine({ stage }: { stage: Stage }) {
  const ran = formatDate(stage.ran_at);
  if (stage.freshness.length === 0) {
    return ran ? <p className="mt-1">Run on {ran}.</p> : null;
  }
  const stale = stage.freshness.filter((f) => !f.is_current);
  if (stale.length === 0) {
    return (
      <p className="mt-1">
        {ran ? `Run on ${ran}, against ` : "Measured against "}
        {stage.freshness.map((f) => f.basis).join(" and ")}
        {" — still what is deployed."}
      </p>
    );
  }
  return (
    <p className="mt-1 text-foreground">
      {ran ? `Run on ${ran}. ` : ""}
      {stale.map((f) => (
        <span key={f.basis}>
          It was measured against {f.basis} <code>{f.verdict_value}</code>, and{" "}
          <code>{f.current_value}</code> is what is deployed now.{" "}
        </span>
      ))}
      It does not describe what is running today; re-run the deep gate before
      relying on it.
    </p>
  );
}

/**
 * Everything the grader recorded for one stage — gate, score, freshness
 * against the deployed build, every auto-surfaced finding (severity,
 * `[PLATFORM]` / `[HARNESS]` / `[INSTRUMENT]` tags, issue refs, hashes),
 * the failing items and the dimension scores. Members only, collapsed
 * behind the plain outcome: it is the grader's working, and it is what a
 * Dimagi reviewer needs before trusting the outcome line.
 */
function StageDetail({ stage }: { stage: Stage }) {
  return (
    <div className="mt-1 text-[0.85rem] leading-[1.6] text-muted-foreground">
      <p className="text-foreground">This {gateSentence(stage)}.</p>
      <ScoreLine stage={stage} />
      <FreshnessLine stage={stage} />
      {stage.findings.map((f) => (
        <p key={f.message} className="mt-1">
          {f.severity && <span className="font-mono text-[0.8rem]">{f.severity}</span>}
          {f.severity && " — "}
          {f.message}
        </p>
      ))}
      {stage.items.length > 0 && (
        <ul className="mt-2 space-y-1">
          {stage.items.map((item) => (
            <li key={item.ref}>
              <span className="font-mono text-[0.8rem]">{item.ref}</span>
              {` — ${item.verdict}`}
              {item.score != null && ` (${item.score})`}
              {item.note ? `. ${item.note}` : "."}
            </li>
          ))}
        </ul>
      )}
      {stage.dimensions.length > 0 && (
        <p className="mt-2">
          {stage.dimensions
            .map((d) => `${d.name.replace(/_/g, " ")} ${d.score ?? "—"}`)
            .join(" · ")}
        </p>
      )}
    </div>
  );
}

/**
 * The gate as a partner reads it. Same honesty rule as `GATE_LABELS`:
 * `iterate` and `reject` stay distinct, and an unknown disposition is
 * shown, never dropped.
 */
const PLAIN_GATE: Record<string, string> = {
  approve: "Passed",
  iterate: "Not passed yet — it needs another round of fixes",
  reject: "Did not pass",
};

/**
 * One line: "Passed — 73 of 73 checks, scored 9.4/10, 5 Oct 2026."
 *
 * The score is never shown without the gate in front of it (a score over
 * the bar with failures is still not a pass — see `ScoreLine`).
 */
export function plainOutcome(stage: Stage): string {
  if (!stage.ran) return "Not checked yet.";
  const gate = stage.gate
    ? (PLAIN_GATE[stage.gate] ?? `Result: ${stage.gate}`)
    : "Checked, with no pass or fail recorded";
  const parts: string[] = [];
  const { total, pass } = stage.counts;
  if (total > 0) parts.push(`${pass} of ${total} ${total === 1 ? "check" : "checks"}`);
  if (stage.score != null) parts.push(`scored ${Math.round(stage.score * 10) / 10}/10`);
  const ran = formatDate(stage.ran_at);
  if (ran) parts.push(ran);
  return parts.length > 0 ? `${gate} — ${parts.join(", ")}.` : `${gate}.`;
}

/**
 * A `[PRODUCT]` finding as a sentence about the app, or null when it is
 * not one a partner should read.
 *
 * Only `[PRODUCT]` findings are about the thing the partner will use;
 * `[PLATFORM]` / `[HARNESS]` / `[INSTRUMENT]` and untagged INFO lines are
 * about the grader and stay member-only. From a product finding this
 * strips the tag and the references a partner cannot use — issue / PR
 * numbers, build hashes, app versions, journey ids — and drops one the
 * grader itself calls "not a defect". It does not paraphrase: ACE writes
 * the sentence, and inventing wording here would put words in its mouth.
 */
export function plainProductFinding(message: string): string | null {
  const tag = /^\s*\[([A-Z][A-Z-]*)\]\s*/.exec(message);
  if (!tag || tag[1] !== "PRODUCT") return null;
  let m = message.slice(tag[0].length);
  if (/\bnot a defect\b/i.test(m)) return null;
  m = m
    // A parenthetical that is only a reference: "(ace#2692)", "(v16 and v23)",
    // "(journey-deliver-…)", "(PR #2665)", a build hash.
    .replace(
      /\s*\((?=[^()]*(?:#\d|\bv\d+\b|journey-|\b[0-9a-f]{7,}\b))[^()]*\)/gi,
      "",
    )
    .replace(/\s*\b(?:ace|ace-web|PR)\s?#\d+\b/gi, "")
    .replace(/\s+([.,;:])(?=\s|$)/g, "$1")
    .replace(/\s{2,}/g, " ")
    .trim();
  if (!m) return null;
  m = m.charAt(0).toUpperCase() + m.slice(1);
  return /[.!?]$/.test(m) ? m : `${m}.`;
}

/** One stage — the plain outcome first, for everyone. */
function StageBlock({ stage, isMember }: { stage: Stage; isMember: boolean }) {
  const stale = stage.freshness.some((f) => !f.is_current);
  const product = isMember
    ? []
    : stage.findings
        .map((f) => plainProductFinding(f.message))
        .filter((m): m is string => m != null);
  return (
    <div className="border-t border-border py-3.5 first:border-t-0">
      <p className="text-[11px] uppercase tracking-[0.16em] text-muted-foreground/80">
        {stage.label}
      </p>
      <p className="mt-1 text-[0.85rem] leading-[1.6] text-foreground" data-testid="deep-qa-outcome">
        {plainOutcome(stage)}
      </p>
      {stage.ran && stale && (
        <p className="mt-1 text-[0.85rem] leading-[1.6] text-muted-foreground">
          Checked on an earlier version than the one released now.
        </p>
      )}
      {product.length > 0 && (
        <div className="mt-2 text-[0.85rem] leading-[1.6] text-muted-foreground">
          <p>What the check noticed in the app:</p>
          <ul className="mt-1 list-disc space-y-1 pl-5">
            {product.map((m) => (
              <li key={m}>{m}</li>
            ))}
          </ul>
        </div>
      )}
      {stage.ran && isMember && (
        <details className="mt-2">
          <summary className="cursor-pointer select-none text-[0.85rem] text-muted-foreground hover:text-foreground">
            Full grader detail
          </summary>
          <div className="border-l border-border pl-4">
            <StageDetail stage={stage} />
          </div>
        </details>
      )}
    </div>
  );
}

/**
 * The `/ace:qa-deep` gate, rendered where a partner can find it.
 *
 * Absent entirely when the gate never ran — the caller passes `null` and
 * this returns nothing, rather than an empty shell that a reader would
 * have to interpret. Half a gate IS rendered, with the stage that did
 * not run saying so, because `--ocs-only` / `--apps-only` are real
 * invocations and "we did not test this" is information.
 */
export function DeepQaSection({
  deepQa,
  isMember = false,
}: {
  deepQa: OppSummaryPayload["deep_qa"];
  /**
   * A workspace member also gets the grader's full working, collapsed. An
   * outside reader gets the outcome and the findings about the app only —
   * grader logs, issue numbers and build hashes are noise to a partner.
   */
  isMember?: boolean;
}) {
  if (!deepQa || deepQa.stages.length === 0) return null;
  return (
    <div>
      <p className="mb-3 text-[0.85rem] leading-[1.6] text-muted-foreground">
        A separate, deeper check of the assistant’s answers and the field app,
        run after the build to a higher bar than the checks during it. It must
        pass before anything goes live.
      </p>
      {deepQa.stages.map((stage) => (
        <StageBlock key={stage.stage} stage={stage} isMember={isMember} />
      ))}
    </div>
  );
}
