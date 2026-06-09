import { useMemo } from "react";
import type { TemplateEditorAction } from "./templateEditorReducer";

interface Props {
  skeletonYaml: string;
  dispatch: React.Dispatch<TemplateEditorAction>;
}

/**
 * Minimal client-side YAML validity check.
 *
 * The `yaml` package is not a frontend dependency. This heuristic catches the
 * most common mistakes (unclosed brackets, tabs used for indentation, mapping
 * key collisions detectable by a line scan) without a full parser:
 *
 *  1. Tabs in indentation — YAML forbids them.
 *  2. Unmatched `[` / `{` brackets across the whole document.
 *  3. Indentation regression: a line indented less than the current block
 *     without also being a mapping key or list item (very basic; avoids false
 *     positives by only checking leading-space deltas on non-blank, non-comment
 *     lines).
 *
 * Returns null when the content passes all heuristics, or a short error string.
 */
function lintYaml(text: string): string | null {
  if (!text.trim()) return null;

  const lines = text.split("\n");

  // Rule 1: tabs in indentation
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const indentMatch = /^(\s*)/.exec(line);
    if (indentMatch && indentMatch[1].includes("\t")) {
      return `Line ${i + 1}: tabs are not allowed in YAML indentation — use spaces.`;
    }
  }

  // Rule 2: unmatched brackets/braces
  let square = 0;
  let curly = 0;
  for (const ch of text) {
    if (ch === "[") square++;
    else if (ch === "]") square--;
    else if (ch === "{") curly++;
    else if (ch === "}") curly--;
  }
  if (square !== 0) return "Unmatched brackets `[` / `]`.";
  if (curly !== 0) return "Unmatched braces `{` / `}`.";

  // Rule 3: duplicate mapping keys on the same indent level (simple check)
  // Tracks "indent → last key at that indent" and flags repeats.
  const seenKeys = new Map<number, string>();
  let lastIndent = 0;
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (!line.trim() || line.trimStart().startsWith("#")) continue;
    const indentMatch = /^( *)/.exec(line);
    const indent = indentMatch ? indentMatch[1].length : 0;
    // Reset tracked keys for deeper levels when we de-indent
    if (indent < lastIndent) {
      for (const k of [...seenKeys.keys()]) {
        if (k > indent) seenKeys.delete(k);
      }
    }
    lastIndent = indent;
    // A list item ("- ...") starts a NEW mapping element, so its first key is
    // not a duplicate of the previous sibling's first key (e.g. repeated
    // "- asset:" under product.beats is valid). Reset tracking at this indent
    // and deeper, then track the inline key (the part after "- ") at the
    // dash-adjusted column so genuine in-item key duplicates are still caught.
    const listMatch = /^ *-\s+(.*)$/.exec(line);
    if (listMatch) {
      for (const k of [...seenKeys.keys()]) {
        if (k >= indent) seenKeys.delete(k);
      }
      const inlineKey = /^([^#\s][^:]*):/.exec(listMatch[1]);
      if (inlineKey) seenKeys.set(indent + 2, inlineKey[1].trim());
      continue;
    }
    const keyMatch = /^[ ]*([^#\s][^:]*):/.exec(line);
    if (keyMatch) {
      const key = keyMatch[1].trim();
      if (seenKeys.get(indent) === key) {
        return `Line ${i + 1}: duplicate mapping key "${key}" at indent ${indent}.`;
      }
      seenKeys.set(indent, key);
    }
  }

  return null;
}

export function TemplateSkeletonPanel({ skeletonYaml, dispatch }: Props) {
  const yamlError = useMemo(() => lintYaml(skeletonYaml), [skeletonYaml]);

  return (
    <div className="flex flex-col gap-3">
      <div className="text-xs text-muted-foreground">
        The structural skeleton used as a starting point when generating a program from
        this template. Must be valid YAML. This is an advanced field — changes here
        affect every new program created from this template.
      </div>

      <section className="flex flex-col gap-1.5">
        <div className="flex items-center justify-between">
          <label htmlFor="template-skeleton" className="text-xs font-medium uppercase tracking-wide">
            Skeleton YAML
          </label>
          <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">
            Advanced — raw skeleton
          </span>
        </div>
        <textarea
          id="template-skeleton"
          value={skeletonYaml}
          onChange={(e) => dispatch({ type: "set-skeleton", value: e.target.value })}
          rows={20}
          spellCheck={false}
          aria-describedby={yamlError ? "skeleton-yaml-error" : undefined}
          className={[
            "w-full resize-y rounded border bg-background p-2 font-mono text-sm leading-relaxed",
            yamlError ? "border-amber-500 focus:outline-amber-500" : "",
          ]
            .filter(Boolean)
            .join(" ")}
          placeholder={"beats:\n  - id: hook\n    seconds: 8\n    # …"}
        />
        {yamlError && (
          <p
            id="skeleton-yaml-error"
            role="alert"
            className="text-[11px] font-medium text-amber-700 dark:text-amber-500"
          >
            YAML issue: {yamlError}
          </p>
        )}
      </section>

      <p className="text-[11px] text-muted-foreground">
        Each key at the top level becomes a section of the generated program spec.
        Keep indentation consistent (spaces only, no tabs).
      </p>
    </div>
  );
}
