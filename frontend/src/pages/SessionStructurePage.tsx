import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft } from "lucide-react";

import { getSession } from "../api/sessions";
import type { Session } from "../api/types";
import { OppHeaderBreadcrumb } from "../components/OppHeaderBreadcrumb";
import { RecentSessionsSidebar } from "../components/RecentSessionsSidebar";
import { StructureTab } from "../components/structure/StructureTab";

export function SessionStructurePage() {
  const { slug = "", workspaceSlug = "" } = useParams<{
    slug: string;
    workspaceSlug: string;
  }>();
  const [meta, setMeta] = useState<Session | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setMeta(null);
    setLoadError(null);
    getSession(slug)
      .then((s) => {
        if (!cancelled) setMeta(s);
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setLoadError(err instanceof Error ? err.message : String(err));
        }
      });
    return () => {
      cancelled = true;
    };
  }, [slug]);

  return (
    <div className="flex h-full">
      <RecentSessionsSidebar currentSlug={slug} />
      <div className="flex flex-1 flex-col overflow-hidden">
        <header className="flex items-center justify-between border-b border-border px-4 py-3">
          <div className="flex items-center gap-3">
            <Link
              to={`/w/${workspaceSlug}/chat/${slug}`}
              className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
              title="Back to chat"
            >
              <ArrowLeft className="h-4 w-4" />
              Chat
            </Link>
            <OppHeaderBreadcrumb
              oppSlug={meta?.opp_slug ?? ""}
              oppDisplayName={meta?.opp_display_name ?? ""}
              oppRunId={meta?.opp_run_id ?? ""}
              oppStepSkill={meta?.opp_step_skill ?? ""}
              oppStepSkillDisplay={meta?.opp_step_skill_display ?? ""}
            />
            <div className="text-sm font-medium">
              {meta?.title ?? (loadError ? "Session not found" : "Loading…")}
            </div>
          </div>
        </header>
        <div className="flex-1 overflow-auto">
          {loadError ? (
            <div className="p-4 text-sm text-destructive">{loadError}</div>
          ) : (
            <StructureTab slug={slug} />
          )}
        </div>
      </div>
    </div>
  );
}
