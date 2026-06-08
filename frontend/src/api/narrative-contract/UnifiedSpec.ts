// GENERATED from canopy scripts/narrative/schema/json/UnifiedSpec.json — do not edit. Run `npm run gen:narrative`.

export type Name = string;
export type Narrative = string;
export type BaseUrl = string;
export type Auth = {
  [k: string]: unknown;
} | null;
export type WhyBrief = string | null;
export type Name1 = string;
export type Role = string;
export type Color = string;
export type Intro = string;
export type Org = string;
export type Persona1 = string;
export type Title = string;
export type Show = string;
export type ConceptClaim = string;
export type Provenance = string;
export type DesignIntent = string | null;
export type ImpressiveBecause = string | null;
export type Id = string;
export type Description = string;
export type Verify = string;
export type Features = Feature[];
export type Note = string | null;
export type MustSucceed = boolean;
export type Kind = "goto";
export type Target = string;
export type Note1 = string | null;
export type MustSucceed1 = boolean;
export type Kind1 = "click";
export type Target1 = string;
export type Note2 = string | null;
export type MustSucceed2 = boolean;
export type Kind2 = "click_menu";
export type Target2 = string;
export type Note3 = string | null;
export type MustSucceed3 = boolean;
export type Kind3 = "fill";
export type Target3 = string;
export type Value = string;
export type Note4 = string | null;
export type MustSucceed4 = boolean;
export type Kind4 = "select";
export type Target4 = string;
export type Value1 = string;
export type Note5 = string | null;
export type MustSucceed5 = boolean;
export type Kind5 = "type";
export type Value2 = string;
export type Note6 = string | null;
export type MustSucceed6 = boolean;
export type Kind6 = "press";
export type Value3 = string;
export type Note7 = string | null;
export type MustSucceed7 = boolean;
export type Kind7 = "hover";
export type Target5 = string;
export type Seconds = number | null;
export type Note8 = string | null;
export type MustSucceed8 = boolean;
export type Kind8 = "scroll_to";
export type Target6 = string;
export type Note9 = string | null;
export type MustSucceed9 = boolean;
export type Kind9 = "scroll";
export type Value4 = string;
export type Note10 = string | null;
export type MustSucceed10 = boolean;
export type Kind10 = "wait_for";
export type Target7 = string;
export type Seconds1 = number | null;
export type Note11 = string | null;
export type MustSucceed11 = boolean;
export type Kind11 = "hold";
export type Seconds2 = number;
export type Note12 = string | null;
export type MustSucceed12 = boolean;
export type Kind12 = "draw";
export type Target8 = string;
export type Points = [unknown, unknown][];
export type Tool = string | null;
export type Actions = (
  | GotoAction
  | ClickAction
  | ClickMenuAction
  | FillAction
  | SelectAction
  | TypeAction
  | PressAction
  | HoverAction
  | ScrollToAction
  | ScrollAction
  | WaitForAction
  | HoldAction
  | DrawAction
)[];
export type Url = string | null;
export type Viewport = {
  [k: string]: number;
} | null;
export type FullPage = boolean | null;
export type Narrative1 = string;
export type Scenes = Scene[];
export type NarrativeLocked = boolean;
export type NarrativeLockedAt = string | null;
export type NarrativeSyncedVersion = number | null;
export type NarrativeSyncedHash = string | null;
export type NarrativeSyncedAt = string | null;
export type Tagline = string;
export type Capabilities = string[];
export type WhySummary = string;
export type GettingStarted = string[];
export type BuildOrder = string[];

export interface UnifiedSpec {
  name: Name;
  narrative: Narrative;
  base_url: BaseUrl;
  auth?: Auth;
  why_brief?: WhyBrief;
  personas: Personas;
  scenes: Scenes;
  narrative_locked?: NarrativeLocked;
  narrative_locked_at?: NarrativeLockedAt;
  narrative_synced_version?: NarrativeSyncedVersion;
  narrative_synced_hash?: NarrativeSyncedHash;
  narrative_synced_at?: NarrativeSyncedAt;
  tagline?: Tagline;
  capabilities?: Capabilities;
  why_summary?: WhySummary;
  getting_started?: GettingStarted;
  build_order?: BuildOrder;
  [k: string]: unknown;
}
export interface Personas {
  [k: string]: Persona;
}
export interface Persona {
  name: Name1;
  role: Role;
  color: Color;
  intro: Intro;
  org?: Org;
  [k: string]: unknown;
}
export interface Scene {
  persona: Persona1;
  title: Title;
  show: Show;
  concept_claim: ConceptClaim;
  provenance: Provenance;
  design_intent?: DesignIntent;
  impressive_because?: ImpressiveBecause;
  features?: Features;
  actions?: Actions;
  url?: Url;
  viewport?: Viewport;
  full_page?: FullPage;
  narrative?: Narrative1;
  [k: string]: unknown;
}
/**
 * A single buildable, verifiable capability within a scene (DDD v3).
 */
export interface Feature {
  id: Id;
  description: Description;
  verify: Verify;
  [k: string]: unknown;
}
/**
 * Navigate to a URL. ``target`` is the URL (absolute or path-relative).
 */
export interface GotoAction {
  note?: Note;
  must_succeed?: MustSucceed;
  kind: Kind;
  target: Target;
}
/**
 * Click a visible text label or CSS selector.
 *
 * ``target`` supports the recorder's prefix syntax: ``css:#sel``,
 * ``testid:foo``, ``aria:Foo``, ``role:button``, ``text:Foo`` (force the
 * visible-text path). Bare strings use a heuristic — CSS-shaped → selector
 * engine; English → visible-text ranking.
 */
export interface ClickAction {
  note?: Note1;
  must_succeed?: MustSucceed1;
  kind: Kind1;
  target: Target1;
}
/**
 * Click an item inside the currently-open dropdown / popover.
 *
 * Same target syntax as :class:`ClickAction`. Distinct verb because menus
 * usually have shorter post-click settle than a top-level button.
 */
export interface ClickMenuAction {
  note?: Note2;
  must_succeed?: MustSucceed2;
  kind: Kind2;
  target: Target2;
}
/**
 * Focus a field (``target``) and type ``value`` character-by-character.
 *
 * Typing fires real ``input`` events — reactive form widgets that gate
 * buttons on debounced input (e.g. the bulk-create line counter) WILL
 * react to ``fill`` but won't react to a raw ``.value = ...`` setter.
 */
export interface FillAction {
  note?: Note3;
  must_succeed?: MustSucceed3;
  kind: Kind3;
  target: Target3;
  value: Value;
}
/**
 * Pick an option from a native ``<select>``.
 *
 * ``value`` is interpreted as the option's ``value`` attribute first, then
 * a digit-only string as the 0-based ``index``, then the visible text
 * label. The recorder glides the cursor onto the select so the viewer
 * sees which control is being driven (the dropdown won't visually open —
 * native-control limitation).
 */
export interface SelectAction {
  note?: Note4;
  must_succeed?: MustSucceed4;
  kind: Kind4;
  target: Target4;
  value: Value1;
}
/**
 * Type ``value`` into whatever element currently has focus.
 *
 * No ``target`` — that's what :class:`FillAction` is for. Use ``type``
 * only after an explicit focus (or right after ``fill`` to extend the
 * text).
 */
export interface TypeAction {
  note?: Note5;
  must_succeed?: MustSucceed5;
  kind: Kind5;
  value: Value2;
}
/**
 * Press a keyboard key. Defaults to Enter — the most common case.
 */
export interface PressAction {
  note?: Note6;
  must_succeed?: MustSucceed6;
  kind: Kind6;
  value?: Value3;
}
/**
 * Glide the cursor onto ``target`` and rest. No click.
 *
 * ``seconds`` overrides the default dwell — useful when the demo is
 * showing a tooltip or hover-revealed control that needs time to appear.
 */
export interface HoverAction {
  note?: Note7;
  must_succeed?: MustSucceed7;
  kind: Kind7;
  target: Target5;
  seconds?: Seconds;
}
/**
 * Smooth-scroll the element matching ``target`` into view.
 */
export interface ScrollToAction {
  note?: Note8;
  must_succeed?: MustSucceed8;
  kind: Kind8;
  target: Target6;
}
/**
 * Scroll the page. ``value`` is ``"top"``, ``"bottom"``, or a pixel offset.
 */
export interface ScrollAction {
  note?: Note9;
  must_succeed?: MustSucceed9;
  kind: Kind9;
  value?: Value4;
}
/**
 * Wait for ``target`` (text or selector) to appear.
 *
 * All-digits target is treated as a millisecond pause. Plain-text targets
 * skip the selector engine (which would otherwise sit through its full
 * timeout before falling back) — see the recorder's
 * ``_lib/targets.wait_for_target``.
 *
 * ``seconds`` is a per-action timeout override. The recorder's default
 * ``wait_for`` timeout is ``RecorderConfig.wait_for_timeout_ms`` (12s);
 * when an author knows a particular condition might take longer (an SSE
 * bulk-create stream that runs 30-90s) the spec can say
 * ``seconds: 120`` to wait up to two minutes — and the recorder exits
 * the moment the target appears, instead of holding blindly. The
 * alternative — padding with a fixed ``hold`` after a normal-timeout
 * ``wait_for`` — guarantees 100+ seconds of dead-air on a clip if the
 * condition resolves early. ``None`` preserves the default.
 */
export interface WaitForAction {
  note?: Note10;
  must_succeed?: MustSucceed10;
  kind: Kind10;
  target: Target7;
  seconds?: Seconds1;
}
/**
 * Dwell in place for ``seconds``.
 *
 * The single-purpose pause: framing time after a layout, reading time
 * after a render, slack so the SSE stream finishes flushing.
 */
export interface HoldAction {
  note?: Note11;
  must_succeed?: MustSucceed11;
  kind: Kind11;
  seconds: Seconds2;
}
/**
 * Draw a polygon on a map or canvas by clicking a sequence of points.
 *
 * The recorder has no way to express map drawing through the other verbs —
 * ``click`` resolves a DOM element's centre, but a Mapbox-GL-Draw polygon (or any
 * canvas drawing tool) needs clicks at *coordinates on the canvas*, not on a
 * labelled element. ``draw`` fills that gap.
 *
 * ``target`` is the map/canvas element (e.g. ``css:#review-map``). ``points`` is a
 * list of ``[fx, fy]`` fractional positions (0-1) within that element's bounding
 * box — fractions, not pixels, so the polygon is independent of viewport size. The
 * synthetic cursor glides to each vertex and clicks (real Playwright pointer events
 * the drawing tool receives), then double-clicks the last vertex to close the
 * polygon (Mapbox finishes a polygon on double-click).
 *
 * Set ``tool`` to the draw-tool button (e.g. ``css:.mapbox-gl-draw_polygon``) and
 * ``draw`` activates it first with a coordinate mouse-click — which works on the
 * small map-control buttons that a normal ``click`` can't (Playwright's
 * actionability checks time out on them). Omit ``tool`` if the tool is already
 * active.
 */
export interface DrawAction {
  note?: Note12;
  must_succeed?: MustSucceed12;
  kind: Kind12;
  target: Target8;
  points: Points;
  tool?: Tool;
}
