// GENERATED from canopy scripts/narrative/schema/json/WhyBrief.json — do not edit. Run `npm run gen:narrative`.

export type SchemaVersion = number;
export type NarrativeSlug = string;
export type Problem = string;
export type Id = string;
export type Claim = string;
export type Rationale = string;
export type Kind = "documented" | "implemented" | "assumed";
export type Ref = string;
export type Evidence = Evidence1[];
export type Status = "grounded" | "gap";
export type Spine = SpineItem[];
export type Id1 = string;
export type Type = "RESEARCH" | "CAPABILITY" | "DECISION";
export type ClaimRef = string;
export type Detail = string;
export type ProposedAction = string;
export type Gaps = Gap[];

export interface WhyBrief {
  schema_version?: SchemaVersion;
  narrative_slug: NarrativeSlug;
  problem: Problem;
  spine: Spine;
  gaps: Gaps;
  [k: string]: unknown;
}
export interface SpineItem {
  id: Id;
  claim: Claim;
  rationale: Rationale;
  evidence?: Evidence;
  status?: Status;
  [k: string]: unknown;
}
export interface Evidence1 {
  kind: Kind;
  ref: Ref;
  [k: string]: unknown;
}
export interface Gap {
  id: Id1;
  type: Type;
  claim_ref: ClaimRef;
  detail: Detail;
  proposed_action: ProposedAction;
  [k: string]: unknown;
}
