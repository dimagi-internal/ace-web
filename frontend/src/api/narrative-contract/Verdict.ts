// GENERATED from canopy scripts/narrative/schema/json/Verdict.json — do not edit. Run `npm run gen:narrative`.

export type SchemaVersion = number;
export type Score = number;
export type Weight = number;
export type OverallScore = number;
export type Verdict1 = "pass" | "warn" | "fail" | "blocked";
export type BlockingReason = string | null;
export type FixRecommendation = string | null;

export interface Verdict {
  schema_version?: SchemaVersion;
  dimensions: Dimensions;
  overall_score: OverallScore;
  verdict: Verdict1;
  blocking_reason?: BlockingReason;
  fix_recommendation?: FixRecommendation;
  [k: string]: unknown;
}
export interface Dimensions {
  [k: string]: Dimension;
}
export interface Dimension {
  score: Score;
  weight: Weight;
  [k: string]: unknown;
}
