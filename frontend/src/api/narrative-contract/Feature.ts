// GENERATED from canopy scripts/narrative/schema/json/Feature.json — do not edit. Run `npm run gen:narrative`.

export type Id = string;
export type Description = string;
export type Verify = string;

/**
 * A single buildable, verifiable capability within a scene (DDD v3).
 */
export interface Feature {
  id: Id;
  description: Description;
  verify: Verify;
  [k: string]: unknown;
}
