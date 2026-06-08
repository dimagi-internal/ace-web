// GENERATED from canopy scripts/narrative/schema/json/ReviewRequest.json — do not edit. Run `npm run gen:narrative`.

export type SchemaVersion = number;
export type RunId = string;
export type NarrativeSlug = string;
export type Gate = string;
export type Id = string;
export type Prompt = string;
export type Options = string[];
export type Recommended = string;
export type Class = string;
export type Decisions = Decision[];
export type Scene = number;
export type Id1 = string;
export type Title = string;
export type Persona = string;
export type Provenance = string;
export type Text = string;
export type Id2 = string;
export type Description = string;
export type Verify = string;
export type Features = Feature[];
export type Status = "built" | "new";
export type Narration = (
  | NarrationItem
  | {
      [k: string]: unknown;
    }
)[];
export type Narrative = string;
export type AutonomousAudit = string[];
export type Actionability = {
  [k: string]: unknown;
} | null;
export type BuildOrder = string[];

export interface ReviewRequest {
  schema_version?: SchemaVersion;
  run_id: RunId;
  narrative_slug?: NarrativeSlug;
  gate: Gate;
  video: Video;
  decisions: Decisions;
  narration: Narration;
  narrative?: Narrative;
  personas?: Personas;
  why_brief?: WhyBrief;
  autonomous_audit?: AutonomousAudit;
  actionability?: Actionability;
  build_order?: BuildOrder;
  [k: string]: unknown;
}
export interface Video {
  [k: string]: unknown;
}
export interface Decision {
  id: Id;
  prompt: Prompt;
  options: Options;
  recommended: Recommended;
  class: Class;
  [k: string]: unknown;
}
/**
 * One scene's narration entry in a ReviewRequest (DDD v3).
 *
 * Carries the scene's 1-based number (``scene``), its slug (``id``), the
 * story-beat ``title``, the on-screen ``persona`` key, the editable story
 * beat (``text`` = concept_claim), and the concrete buildable features
 * declared by the spec's ``Scene.features[]``.  ``title``/``persona`` let
 * the review surface render the cohesive multi-persona narrative instead of
 * a generic "Scene N" label.
 */
export interface NarrationItem {
  scene: Scene;
  id: Id1;
  title?: Title;
  persona?: Persona;
  provenance?: Provenance;
  text: Text;
  features?: Features;
  status?: Status;
  [k: string]: unknown;
}
/**
 * A single buildable, verifiable capability within a scene (DDD v3).
 */
export interface Feature {
  id: Id2;
  description: Description;
  verify: Verify;
  [k: string]: unknown;
}
export interface Personas {
  [k: string]: unknown;
}
export interface WhyBrief {
  [k: string]: unknown;
}
