import { useState } from "react";
import { useBeatEditor } from "../../BeatEditorContext";

interface Props {
  /** The beat whose on-screen content this drawer edits. Determines which
      field(s) are shown — the hook / end-card edit the tagline, the cycle
      beat edits the four step labels. */
  beatId: string;
  onCommit: () => void;
  onCancel: () => void;
}

// Defaults from programs/_defaults.yaml > global_template. The
// renderer's resolveGlobalTemplate() in Root.tsx falls back to these
// when spec.global_template doesn't override them. Mirrored here so
// the drawer can show the default value as the placeholder / reset
// target.
const GLOBAL_TAGLINE = "Pay for verified service delivery, not planned activity.";
const GLOBAL_CYCLE_STEPS = ["Learn", "Deliver", "Verify", "Pay"] as const;

/**
 * Per-beat editor for the text rendered ON the video during a beat —
 * the animated tagline on the hook / end card, and the four cycle step
 * labels on the cycle beat. This is the on-screen layer, separate from
 * the voiceover narration (which has its own widget on the same beat).
 *
 * Scoped to the beat: the hook / end-card beats show only the tagline;
 * the cycle beat shows only the step labels. (Previously every beat's
 * drawer showed both, so the opening-tagline beat wrongly surfaced the
 * Learn→Deliver→Verify→Pay editor.) The op omits the field this beat
 * doesn't edit, so editing one never clears the other's customization.
 *
 * Each field starts from the shared brand wording in
 * programs/_defaults.yaml; setting a value writes
 * `global_template.tagline` / `global_template.cycle_steps` onto the
 * spec, and clearing it falls back to the default.
 *
 * Reads either `spec.global_template` (canonical key) or `spec.brand`
 * (legacy, pre-rename) so any spec is handled regardless of which key
 * is present.
 */
export function GlobalTemplatePanel({ beatId, onCommit, onCancel }: Props) {
  const { effectiveSpec, dispatch } = useBeatEditor();

  // The cycle beat (intro_cycle) edits the step labels; every other beat
  // routed here (intro_hook, outro_cta) edits the on-screen tagline.
  const kind = effectiveSpec.beats?.find((b) => b.id === beatId)?.kind ?? "";
  const editsCycle = kind === "intro_cycle";

  const specWithGlobal = effectiveSpec as {
    global_template?: { tagline?: string; cycle_steps?: string[] };
    brand?: { tagline?: string; cycle_steps?: string[] };
  };
  const overrides = specWithGlobal.global_template ?? specWithGlobal.brand;

  const initialTagline = overrides?.tagline ?? "";
  const initialSteps =
    overrides?.cycle_steps && overrides.cycle_steps.length === 4
      ? overrides.cycle_steps
      : ["", "", "", ""];

  const [tagline, setTagline] = useState(initialTagline);
  const [steps, setSteps] = useState<string[]>(initialSteps);

  const dirty = editsCycle
    ? steps.some((s, i) => s !== initialSteps[i])
    : tagline !== initialTagline;

  const commit = () => {
    if (!dirty) {
      onCancel();
      return;
    }

    if (editsCycle) {
      // Empty list → server pops the override → default kicks back in.
      const stepsTrimmed = steps.map((s) => s.trim());
      const allStepsBlank = stepsTrimmed.every((s) => s === "");
      const allStepsFilled = stepsTrimmed.every((s) => s !== "");
      if (!allStepsBlank && !allStepsFilled) {
        // Mixed state — refuse so we don't ship a half-customized cycle
        // (the renderer expects exactly 4 strings if cycle_steps is set).
        alert(
          "Fill in all four cycle step labels, or clear them all to fall back to the default.",
        );
        return;
      }
      // Omit `tagline` so an existing on-screen tagline isn't cleared.
      dispatch({
        type: "APPEND_OP",
        op: {
          op: "set-global-template",
          cycle_steps: allStepsBlank ? [] : stepsTrimmed,
        },
      });
    } else {
      // Omit `cycle_steps` so an existing cycle customization isn't cleared.
      // Empty tagline clears the override → default kicks back in.
      dispatch({
        type: "APPEND_OP",
        op: { op: "set-global-template", tagline: tagline.trim() },
      });
    }
    onCommit();
  };

  return (
    <div className="flex flex-col gap-4">
      <div className="text-xs text-muted-foreground">
        Text rendered <span className="font-medium text-foreground">on the video</span> during this
        beat — separate from the voiceover. It starts from the shared brand wording; edit to
        customize it for this program, or clear it to fall back to the default.
      </div>

      {/* Tagline — hook / end-card beats */}
      {!editsCycle && (
        <section className="flex flex-col gap-1.5">
          <header className="flex items-center gap-2">
            <label className="text-xs font-medium uppercase tracking-wide">On-screen tagline</label>
            {tagline.trim() && tagline.trim() !== GLOBAL_TAGLINE && (
              <span className="rounded-full bg-emerald-500/15 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-emerald-700 dark:text-emerald-400">
                Customized
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
            Default: <span className="italic">{GLOBAL_TAGLINE}</span>. Leave blank to use it.
          </p>
        </section>
      )}

      {/* Cycle step labels — cycle beat only */}
      {editsCycle && (
        <section className="flex flex-col gap-1.5">
          <header className="flex items-center gap-2">
            <label className="text-xs font-medium uppercase tracking-wide">Cycle step labels</label>
            {steps.some((s) => s.trim()) && (
              <span className="rounded-full bg-emerald-500/15 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-emerald-700 dark:text-emerald-400">
                Customized
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
            Default: {GLOBAL_CYCLE_STEPS.join(" → ")}. Fill in all four to customize, or clear them
            all to reset.
          </p>
        </section>
      )}

      <div className="mt-2 flex justify-end gap-2">
        <button type="button" onClick={onCancel} className="rounded border px-3 py-1.5 text-sm">
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
