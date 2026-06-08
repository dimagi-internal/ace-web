// GENERATED from canopy scripts/narrative/schema/json/Decision.json — do not edit. Run `npm run gen:narrative`.

export type Id = string;
export type Prompt = string;
export type Options = string[];
export type Recommended = string;
export type Class = string;

export interface Decision {
  id: Id;
  prompt: Prompt;
  options: Options;
  recommended: Recommended;
  class: Class;
  [k: string]: unknown;
}
