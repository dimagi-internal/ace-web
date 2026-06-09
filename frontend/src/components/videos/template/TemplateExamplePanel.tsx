import { useMemo } from "react";
import { AutoResizeTextarea } from "@/components/ui/AutoResizeTextarea";
import type { TemplateEditorAction } from "./templateEditorReducer";

interface Props {
  exampleYaml: string;
  dispatch: React.Dispatch<TemplateEditorAction>;
}

/**
 * Minimal client-side YAML validity check — same heuristics as
 * TemplateSkeletonPanel. Returns null on pass, a short error string on fail.
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
  const seenKeys = new Map<number, string>();
  let lastIndent = 0;
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (!line.trim() || line.trimStart().startsWith("#")) continue;
    const indentMatch = /^( *)/.exec(line);
    const indent = indentMatch ? indentMatch[1].length : 0;
    if (indent < lastIndent) {
      for (const k of [...seenKeys.keys()]) {
        if (k > indent) seenKeys.delete(k);
      }
    }
    lastIndent = indent;
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

export function TemplateExamplePanel({ exampleYaml, dispatch }: Props) {
  const yamlError = useMemo(() => lintYaml(exampleYaml), [exampleYaml]);

  return (
    <div className="flex flex-col gap-3">
      <div className="text-xs text-muted-foreground">
        A representative example spec used during testing and as a reference for prompt
        authoring. Must be valid YAML. Changes here do not affect generated programs
        but are saved alongside the template.
      </div>

      <section className="flex flex-col gap-1.5">
        <div className="flex items-center justify-between">
          <label htmlFor="template-example" className="text-xs font-medium uppercase tracking-wide">
            Example YAML
          </label>
          <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">
            Demo spec
          </span>
        </div>
        <AutoResizeTextarea
          id="template-example"
          value={exampleYaml}
          onChange={(e) => dispatch({ type: "set-example", value: e.target.value })}
          rows={20}
          spellCheck={false}
          aria-describedby={yamlError ? "example-yaml-error" : undefined}
          className={[
            "w-full rounded border bg-background p-2 font-mono text-sm leading-relaxed",
            yamlError ? "border-amber-500 focus:outline-amber-500" : "",
          ]
            .filter(Boolean)
            .join(" ")}
          placeholder={"beats:\n  - id: hook\n    seconds: 8\n    # …"}
        />
        {yamlError && (
          <p
            id="example-yaml-error"
            role="alert"
            className="text-[11px] font-medium text-amber-700 dark:text-amber-500"
          >
            YAML issue: {yamlError}
          </p>
        )}
      </section>

      <p className="text-[11px] text-muted-foreground">
        Keep indentation consistent (spaces only, no tabs). This example is shown
        to template authors as a reference — it is not used during program generation.
      </p>
    </div>
  );
}
