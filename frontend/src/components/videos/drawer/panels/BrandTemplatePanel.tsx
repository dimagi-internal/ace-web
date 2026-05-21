import { useState } from "react";
import { useBeatEditor } from "../../BeatEditorContext";

interface Props {
  onCommit: () => void;
  onCancel: () => void;
}

// Defaults from programs/_defaults.yaml > brand. The renderer's
// resolveBrand() in Root.tsx falls back to these when spec.brand
// doesn't override them. Mirrored here so the drawer can show the
// global value as the placeholder / reset target.
const GLOBAL_TAGLINE = "Pay for verified service delivery, not planned activity.";
const GLOBAL_CYCLE_STEPS = ["Learn", "Deliver", "Verify", "Pay"] as const;

/**
 * Per-program brand override editor.
 *
 * The brand template (tagline + four cycle step labels) lives globally
 * in programs/_defaults.yaml — every program inherits it. A program can
 * override either field by setting `brand.tagline` and/or
 * `brand.cycle_steps` on its spec.yaml. This drawer is the entry
 * point: shows the current value, what it would fall back to, and
 * lets the user edit either or both.
 *
 * Clearing a field (empty tagline / blank step) drops the override and
 * falls back to global.
 */
export function BrandTemplatePanel({ onCommit, onCancel }: Props) {
  const { effectiveSpec, dispatch } = useBeatEditor();

  const specBrand = (effectiveSpec as { brand?: { tagline?: string; cycle_steps?: string[] } }).brand;

  const initialTagline = specBrand?.tagline ?? "";
  const initialSteps = specBrand?.cycle_steps && specBrand.cycle_steps.length === 4
    ? specBrand.cycle_steps
    : ["", "", "", ""];

  const [tagline, setTagline] = useState(initialTagline);
  const [steps, setSteps] = useState<string[]>(initialSteps);

  const dirty =
    tagline !== initialTagline ||
    steps.some((s, i) => s !== initialSteps[i]);

  const commit = () => {
    if (!dirty) {
      onCancel();
      return;
    }
    // Empty tagline → server pops the override → global default kicks
    // back in. Same for cycle_steps: an array of all-empty strings is
    // treated as "no override" by sending an empty list.
    const trimmed = tagline.trim();
    const stepsTrimmed = steps.map((s) => s.trim());
    const allStepsBlank = stepsTrimmed.every((s) => s === "");
    const allStepsFilled = stepsTrimmed.every((s) => s !== "");

    if (!allStepsBlank && !allStepsFilled) {
      // Mixed state — refuse so we don't ship a half-overridden cycle
      // step list (the renderer expects exactly 4 strings if cycle_steps
      // is set).
      alert("Fill in all four cycle step labels, or clear them all to fall back to the global default.");
      return;
    }

    dispatch({
      type: "APPEND_OP",
      op: {
        op: "set-brand",
        tagline: trimmed,                                  // "" clears
        cycle_steps: allStepsBlank ? [] : stepsTrimmed,    // [] clears
      },
    });
    onCommit();
  };

  return (
    <div className="flex flex-col gap-4">
      <div className="text-xs text-muted-foreground">
        These strings ship with the global template (
        <code className="rounded bg-muted px-1">programs/_defaults.yaml</code>
        ). Setting any field here writes a per-program override into this
        spec; clearing it falls back to the global value.
      </div>

      {/* Tagline */}
      <section className="flex flex-col gap-1.5">
        <header className="flex items-center gap-2">
          <label className="text-xs font-medium uppercase tracking-wide">Opening tagline</label>
          {tagline.trim() && tagline.trim() !== GLOBAL_TAGLINE && (
            <span className="rounded-full bg-emerald-500/15 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-emerald-700 dark:text-emerald-400">
              Program override
            </span>
          )}
        </header>
        <textarea
          value={tagline}
          onChange={(e) => setTagline(e.target.value)}
          placeholder={GLOBAL_TAGLINE}
          rows={2}
          className="w-full resize-none rounded border bg-background p-2 font-sans text-sm leading-relaxed"
        />
        <p className="text-[11px] text-muted-foreground">
          Global default: <span className="italic">{GLOBAL_TAGLINE}</span>. Leave blank to use the global value.
        </p>
      </section>

      {/* Cycle step labels */}
      <section className="flex flex-col gap-1.5">
        <header className="flex items-center gap-2">
          <label className="text-xs font-medium uppercase tracking-wide">Cycle step labels</label>
          {steps.some((s) => s.trim()) && (
            <span className="rounded-full bg-emerald-500/15 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-emerald-700 dark:text-emerald-400">
              Program override
            </span>
          )}
        </header>
        <div className="grid grid-cols-2 gap-2">
          {steps.map((s, i) => (
            <input
              key={i}
              type="text"
              value={s}
              onChange={(e) => {
                const next = [...steps];
                next[i] = e.target.value;
                setSteps(next);
              }}
              placeholder={GLOBAL_CYCLE_STEPS[i]}
              className="rounded border bg-background px-2 py-1.5 text-sm"
            />
          ))}
        </div>
        <p className="text-[11px] text-muted-foreground">
          Global defaults: {GLOBAL_CYCLE_STEPS.join(" → ")}. Fill in all four to override, or clear them all to reset.
        </p>
      </section>

      <div className="mt-2 flex justify-end gap-2">
        <button
          type="button"
          onClick={onCancel}
          className="rounded border px-3 py-1.5 text-sm"
        >
          Cancel
        </button>
        <button
          type="button"
          onClick={commit}
          disabled={!dirty}
          className="rounded bg-primary px-3 py-1.5 text-sm font-semibold text-primary-foreground disabled:opacity-50"
        >
          Done
        </button>
      </div>
    </div>
  );
}
