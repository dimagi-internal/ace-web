import type { TemplateMeta } from "@/api/videos";
import { AutoResizeTextarea } from "@/components/ui/AutoResizeTextarea";
import type { TemplateEditorAction } from "./templateEditorReducer";

interface Props {
  meta: TemplateMeta;
  dispatch: React.Dispatch<TemplateEditorAction>;
}

export function TemplateMetaPanel({ meta, dispatch }: Props) {
  const setField = (field: keyof Omit<TemplateMeta, "id">, value: string | number) =>
    dispatch({ type: "set-meta-field", field, value });

  return (
    <div className="flex flex-col gap-4">
      <div className="text-xs text-muted-foreground">
        Metadata visible to users when browsing available templates.
      </div>

      <section className="flex flex-col gap-1.5">
        <label htmlFor="template-name" className="text-xs font-medium uppercase tracking-wide">
          Name
        </label>
        <input
          id="template-name"
          type="text"
          value={meta.name}
          onChange={(e) => setField("name", e.target.value)}
          className="w-full rounded border bg-background p-2 text-sm"
          placeholder="e.g. CHW Training — Bednet Distribution"
        />
      </section>

      <section className="flex flex-col gap-1.5">
        <label htmlFor="template-intent" className="text-xs font-medium uppercase tracking-wide">
          Intent
        </label>
        <AutoResizeTextarea
          id="template-intent"
          value={meta.intent}
          onChange={(e) => setField("intent", e.target.value)}
          rows={3}
          className="w-full rounded border bg-background p-2 text-sm leading-relaxed"
          placeholder="What this video must accomplish + its narrative thesis. 1–3 sentences."
        />
        <p className="text-[11px] text-muted-foreground">
          What this video must accomplish + its narrative thesis. Drives AI generation.
        </p>
      </section>

      <section className="flex flex-col gap-1.5">
        <label htmlFor="template-description" className="text-xs font-medium uppercase tracking-wide">
          Description
        </label>
        <AutoResizeTextarea
          id="template-description"
          value={meta.description}
          onChange={(e) => setField("description", e.target.value)}
          rows={3}
          className="w-full rounded border bg-background p-2 text-sm leading-relaxed"
          placeholder="Brief summary of what this template produces."
        />
      </section>

      <section className="flex flex-col gap-1.5">
        <label htmlFor="template-audience" className="text-xs font-medium uppercase tracking-wide">
          Intended audience
        </label>
        <AutoResizeTextarea
          id="template-audience"
          value={meta.intended_audience}
          onChange={(e) => setField("intended_audience", e.target.value)}
          rows={2}
          className="w-full rounded border bg-background p-2 text-sm leading-relaxed"
          placeholder="e.g. CHW supervisors in community health programs"
        />
      </section>

      <section className="flex flex-col gap-1.5">
        <label htmlFor="template-when-to-use" className="text-xs font-medium uppercase tracking-wide">
          When to use
        </label>
        <AutoResizeTextarea
          id="template-when-to-use"
          value={meta.when_to_use}
          onChange={(e) => setField("when_to_use", e.target.value)}
          rows={3}
          className="w-full rounded border bg-background p-2 text-sm leading-relaxed"
          placeholder="e.g. Onboarding new CHWs before their first field visit."
        />
      </section>
    </div>
  );
}
