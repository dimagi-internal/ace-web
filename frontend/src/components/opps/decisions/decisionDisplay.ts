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

/** ACE asks a person to confirm this row before launch. */
export function asksConfirmation(decision: Decision): boolean {
  return decision.review_ask === RECOMMENDED_CONFIRMATION && !decision.superseded_by;
}
