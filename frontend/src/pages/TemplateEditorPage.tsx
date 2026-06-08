import { useParams } from "react-router-dom";
import { WorkbenchLayout } from "@/components/workbench";

/**
 * Placeholder — full editor implemented in T11.
 */
export default function TemplateEditorPage() {
  const { templateId } = useParams<{ templateId: string }>();

  return (
    <div className="flex h-[calc(100vh-3rem)] flex-col">
      <WorkbenchLayout
        center={
          <div className="flex h-full items-center justify-center p-8 text-sm text-muted-foreground">
            Template editor for <code className="mx-1 rounded bg-muted px-1 py-0.5 font-mono text-xs">{templateId}</code> — coming in T11.
          </div>
        }
      />
    </div>
  );
}
