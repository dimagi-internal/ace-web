import { AutoResizeTextarea } from "@/components/ui/AutoResizeTextarea";
import type { TemplateEditorAction } from "./templateEditorReducer";

interface Props {
  promptMd: string;
  dispatch: React.Dispatch<TemplateEditorAction>;
}

export function TemplatePromptPanel({ promptMd, dispatch }: Props) {
  return (
    <div className="flex flex-col gap-3">
      <div className="text-xs text-muted-foreground">
        The system prompt sent to the AI when generating a program from this template.
        Supports <span className="font-medium">Markdown</span> — headings, lists, and
        emphasis are preserved when the prompt is rendered.
      </div>

      <section className="flex flex-col gap-1.5">
        <div className="flex items-center justify-between">
          <label htmlFor="template-prompt" className="text-xs font-medium uppercase tracking-wide">
            Prompt
          </label>
          <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">
            Markdown
          </span>
        </div>
        <AutoResizeTextarea
          id="template-prompt"
          value={promptMd}
          onChange={(e) => dispatch({ type: "set-prompt", value: e.target.value })}
          rows={18}
          spellCheck={false}
          className="w-full rounded border bg-background p-2 font-mono text-sm leading-relaxed"
          placeholder={"# Template prompt\n\nDescribe what the AI should produce..."}
        />
      </section>

      <p className="text-[11px] text-muted-foreground">
        Use Markdown headings and bullet lists to structure instructions for the
        generation model. This text is not shown to end users.
      </p>
    </div>
  );
}
