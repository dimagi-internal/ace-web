// GENERATED from canopy scripts/narrative/schema/json/RunState.json — do not edit. Run `npm run gen:narrative`.

export type SchemaVersion = number;
export type RunId = string;
export type NarrativeSlug = string;
export type Phase = "phase0" | "spec" | "render" | "judged" | "converged" | "uploaded" | "promoted";
export type Iteration = number;
export type WhyBrief = string | null;
export type Findings = {
  [k: string]: unknown;
}[];
export type PendingReview = string | null;
export type LastActor = string | null;
export type LastActorAt = string | null;
export type ScenesRun = number[] | null;
export type SceneFilter = string | null;
export type AutoIterateNextAction = string | null;
export type AutoIterateReason = string | null;
export type NarrativeReviewUrl = string | null;
export type NarrativeReviewId = string | null;

export interface RunState {
  schema_version?: SchemaVersion;
  run_id: RunId;
  narrative_slug: NarrativeSlug;
  phase?: Phase;
  iteration?: Iteration;
  why_brief?: WhyBrief;
  verdicts?: Verdicts;
  findings?: Findings;
  pending_review?: PendingReview;
  last_actor?: LastActor;
  last_actor_at?: LastActorAt;
  scenes_run?: ScenesRun;
  scene_filter?: SceneFilter;
  auto_iterate_next_action?: AutoIterateNextAction;
  auto_iterate_reason?: AutoIterateReason;
  iteration_decks?: IterationDecks;
  iteration_clips?: IterationClips;
  narrative_review_url?: NarrativeReviewUrl;
  narrative_review_id?: NarrativeReviewId;
  [k: string]: unknown;
}
export interface Verdicts {
  [k: string]: string;
}
export interface IterationDecks {
  [k: string]: string;
}
export interface IterationClips {
  [k: string]: string;
}
