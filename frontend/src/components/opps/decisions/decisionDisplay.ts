import type { Decision } from "@/api/types.ws";

/**
 * What a row SHOWS, from the optional plain-language fields ACE writes
 * (ACE docs/decisions-contract.md), falling back field by field so a row
 * from an older run renders exactly as it always did:
 *
 * - headline: `plain_question` → `plain` → `question`;
 * - value: a human change when one is in force (the plain value describes
 *   the AI default, so it must never mask an override) → `plain_value` →
 *   `ai_default`;
 * - the `plain` summary line only when the headline did not already use it.
 *
 * When the headline IS `plain` and ACE wrote no `plain_value`, the value
 * is left EMPTY: `plain` is a sentence stating what was decided, so the
 * raw option beside it only repeated it in jargon an outside reader
 * cannot parse (`payable_slot in key plus Phase 4 rule`, `max_total 21,
 * max_daily 1`). The raw option then lives behind the row's own
 * disclosure, as "Exact option" in the expanded detail.
 *
 * The raw `question` / `ai_default` stay in the expanded detail.
 */
export function decisionDisplay(decision: Decision, effectiveValue: string) {
  const plainQuestion = decision.plain_question?.trim() || "";
  const plain = decision.plain?.trim() || "";
  const plainValue = decision.plain_value?.trim() || "";
  const headline = plainQuestion || plain || decision.question;
  const overridden = effectiveValue !== decision.ai_default;
  const plainStatesTheAnswer = !plainQuestion && Boolean(plain) && !plainValue;
  const value = overridden
    ? effectiveValue
    : plainValue || (plainStatesTheAnswer ? "" : decision.ai_default);
  return {
    headline,
    value,
    summary: plainQuestion ? plain : "",
    /** The collapsed row draws no value line: the headline already said it. */
    valueInHeadline: !overridden && plainStatesTheAnswer,
    rawQuestionDiffers: headline !== decision.question,
    rawValueDiffers: value !== effectiveValue,
  };
}

export const RECOMMENDED_CONFIRMATION = "recommended-confirmation";

export const REQUIRED_BEFORE = "required-before";

/** Not needed for this pilot — collapsed, never an ask (ACE spec 2026-10-04). */
export function isDeferred(decision: Decision): boolean {
  return decision.status === "deferred";
}

/** ACE asks a person to confirm this row before launch. */
export function asksConfirmation(decision: Decision): boolean {
  return (
    decision.review_ask === RECOMMENDED_CONFIRMATION &&
    !decision.superseded_by &&
    !isDeferred(decision)
  );
}

/**
 * The gated ask: this has no working default and must be answered before
 * `needed_by` (the server folds `required-before: award` into the two fields).
 */
export function asksAnswer(decision: Decision): boolean {
  return (
    (decision.review_ask ?? "").startsWith(REQUIRED_BEFORE) &&
    !decision.superseded_by &&
    !isDeferred(decision)
  );
}

/** Either kind of ask — what the reviewer is asked to DO. */
export function isReviewAsk(decision: Decision): boolean {
  return asksConfirmation(decision) || asksAnswer(decision);
}

/** Lifecycle order of `needed_by`; anything else sorts last. */
export const NEEDED_BY_ORDER = ["award", "go-live", "closeout", "extension"] as const;

const NEEDED_BY_LONG: Record<string, string> = {
  award: "before an implementing organisation is chosen",
  "go-live": "before go-live",
  closeout: "before closeout",
  extension: "before any extension",
};

const NEEDED_BY_SHORT: Record<string, string> = {
  award: "before award",
  "go-live": "before go-live",
  closeout: "before closeout",
  extension: "before an extension",
};

/** "before an implementing organisation is chosen" — for a group heading. */
export function neededByPhrase(neededBy: string | undefined): string {
  const key = (neededBy ?? "").trim().toLowerCase();
  if (!key) return "before launch";
  return NEEDED_BY_LONG[key] ?? `before ${neededBy}`;
}

/** "before award" — for the row's compact marker. */
export function neededByShort(neededBy: string | undefined): string {
  const key = (neededBy ?? "").trim().toLowerCase();
  if (!key) return "before launch";
  return NEEDED_BY_SHORT[key] ?? `before ${neededBy}`;
}

const OWNER_LABEL: Record<string, string> = {
  partner: "The programme partner",
  "implementing-org": "The implementing organisation",
  dimagi: "Dimagi",
};

/** Who must answer, in plain words. Free text passes through. */
export function ownerLabel(owner: string | undefined): string {
  const raw = (owner ?? "").trim();
  return OWNER_LABEL[raw.toLowerCase()] ?? raw;
}

/**
 * Where the answer arrives, in plain words. A solicitation question is
 * answered through the call for implementing organisations; its question id
 * is shown to members only (`showId`), since it means nothing outside ACE.
 */
export function answerChannelLabel(channel: string | undefined, showId = false): string {
  const raw = (channel ?? "").trim();
  if (!raw) return "";
  const lower = raw.toLowerCase();
  if (lower === "review") return "Here, on this page";
  if (lower === "call") return "On a call with Dimagi";
  if (lower.startsWith("solicitation")) {
    const id = raw.slice("solicitation".length).replace(/^\s*:\s*/, "").trim();
    const base = "Through the call for implementing organisations — applicants answer it in their response";
    return showId && id ? `${base} (question ${id})` : base;
  }
  return raw;
}
