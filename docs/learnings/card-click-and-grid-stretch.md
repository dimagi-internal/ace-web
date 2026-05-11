# Learning: Two layout traps that look like state bugs in card-grid UIs

**Date**: 2026-05-10
**Context**: The opps Hierarchy view (`/w/<workspace>/opps`) had two reports that looked like React state bugs but were both layout-level. Catching either one took a real-browser repro because both render identically to a misbehaving `useState` hook.
**Status**: Active

## Trap 1 — `<button>` inside `<a>` (or `<Link>`) routes the click ambiguously

### Pattern

The whole opp card was wrapped in a single `<Link to={`/opps/${slug}`}>` so any click navigated. Inside the Link, the chevron / trash / compare actions were `<button>` elements with `onClick={(e) => { e.preventDefault(); e.stopPropagation(); /* action */ }}`.

### Symptom

The user reports "I clicked leep's chevron and turmeric expanded." The React state update is correct in isolation — `toggleExpanded(slug)` always receives the right slug — but the wrong card's chevron actually fires.

### Root cause

HTML disallows interactive content nested inside `<a>` ([WHATWG: anchor flow content rules](https://html.spec.whatwg.org/multipage/text-level-semantics.html#the-a-element)). Browsers handle the click target ambiguously: depending on hit-testing order, the click can land on the anchor first (with React Router's intercept handler) or the inner button first. `e.stopPropagation()` in React's synthetic event system stops bubbling **after** the target is chosen — it can't fix a wrong target.

The two cards both have a Link wrapper. Hit-testing a chevron click can resolve to the **other** card's anchor when their layout boxes overlap or the cursor is in the anchor's padding. React Router's onClick on that anchor then fires `navigate("/opps/turmeric")` — and because `setExpandedOpps` happened to also fire on the right card's button, you see "I clicked leep but turmeric opened."

### Fix

Don't nest interactive content. Make the card a `<div>` with an `onClick` that calls `useNavigate`, and bail out when the target is inside any nested button/link:

```tsx
<div
  role="button"
  tabIndex={0}
  onClick={(e) => {
    if ((e.target as HTMLElement).closest("button, a")) return;
    navigate(`/opps/${opp.slug}`);
  }}
  onKeyDown={(e) => {
    if (e.key === "Enter" || e.key === " ") {
      if ((e.target as HTMLElement).closest("button, a")) return;
      e.preventDefault();
      navigate(`/opps/${opp.slug}`);
    }
  }}
>
  <button onClick={(e) => { e.stopPropagation(); /* action */ }} />
  …
</div>
```

Trade-off: `onClick`-on-div loses native middle-click "open in new tab" on the card body. If you need that back, keep a `<Link>` around just the title block (no nested buttons) as a sibling of the action-button row.

This pattern is also what `canopy-web/frontend/src/pages/ProjectsPage.tsx` uses (PR canopy-web#12 "multi-open cards"). When you find the same bug in a sibling repo, copy that shape.

### Where it lives

- `frontend/src/pages/OppListPage.tsx` — `role="button"` + `closest("button, a")` guard
- Each action button (chevron, trash, compare, tag-filter) — `e.stopPropagation()` only; no `e.preventDefault()` since there's no anchor to navigate

## Trap 2 — CSS Grid stretches collapsed cards to match expanded neighbors

### Pattern

```tsx
<div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
  {opps.map((opp) => <OppCard expanded={expanded.has(opp.slug)} … />)}
</div>
```

Click one card's chevron → that card grows tall with expanded content. Cards in the same row visually appear to also expand (empty space below their titles).

### Symptom

The user reports "clicking one card opens all of them." The `expandedOpps` Set has exactly one slug. The chevron icons render correctly (one `ChevronDown`, others `ChevronRight`). But the layout has three tall cards. **The empty space below the collapsed cards' titles is indistinguishable from genuine expanded content.**

### Root cause

CSS Grid's default `align-items` is `stretch`. Every cell in a row stretches to the height of the tallest cell. When one card's content grows (the inline expanded `<OppRunsList />`), its row-mates stretch to match — even though their inner content is unchanged.

### Fix

```tsx
<div className="grid grid-cols-1 items-start gap-3 md:grid-cols-2 xl:grid-cols-3">
```

`items-start` (CSS `align-items: start`) is the right default for any card grid where individual cards can grow. Pin it on the grid container, not per-cell.

### Where it lives

- `frontend/src/pages/OppListPage.tsx` — `items-start` on the visible-opps grid

## Why both took a real-browser repro to catch

Both bugs render perfectly in isolation:

- A unit test of `toggleExpanded` confirms the right slug is added to the Set.
- A unit test of the Card component confirms it renders `ChevronDown` only when `expanded` is true.

You can't see either bug without two cards laid out together in a real grid with a real Link wrapper, real hit-testing, real `align-items: stretch`. The lesson: when a state-shaped bug report ("the wrong card opens", "all cards open") doesn't match a state-shaped repro, suspect the surrounding layout. `gstack browse` against a local Vite + a `?mock=1` route hardcoded into the API client got both repros to ~30 seconds end-to-end.
