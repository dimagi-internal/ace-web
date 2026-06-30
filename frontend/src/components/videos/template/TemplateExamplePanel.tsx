import { useMemo } from "react";
import { AutoResizeTextarea } from "canopy-ui/ui";

interface Props {
  exampleYaml: string;
}

/**
 * Minimal client-side YAML validity check for the read-only example panel.
 * Returns null on pass, a short error string on fail.
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

export function TemplateExamplePanel({ exampleYaml }: Props) {
  const yamlError = useMemo(() => lintYaml(exampleYaml), [exampleYaml]);

  return (
    <div className="flex flex-col gap-3">
      <div className="text-xs text-muted-foreground">
        The serialized example spec, shown read-only as a reference. Edit it through the
        visual editor above (the single source of truth); this view just mirrors what&apos;s
        saved.
      </div>

      <section className="flex flex-col gap-1.5">
        <div className="flex items-center justify-between">
          <label htmlFor="template-example" className="text-xs font-medium uppercase tracking-wide">
            Example YAML
          </label>
          <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">
            Read-only
          </span>
        </div>
        <AutoResizeTextarea
          id="template-example"
          value={exampleYaml}
          readOnly
          rows={20}
          spellCheck={false}
          aria-describedby={yamlError ? "example-yaml-error" : undefined}
          className={[
            "w-full rounded border bg-muted/40 p-2 font-mono text-sm leading-relaxed text-muted-foreground",
            yamlError ? "border-amber-500" : "",
          ]
            .filter(Boolean)
            .join(" ")}
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
        Read-only reference. Edit the example via the <strong>visual editor</strong> above —
        it is the single source of truth, so the raw YAML can&apos;t drift out of sync.
      </p>
    </div>
  );
}
