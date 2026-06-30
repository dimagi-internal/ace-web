import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { ChevronDown, ChevronRight, FileVideo } from "lucide-react";
import { Skeleton } from "@marshellis/canopy-ui/ui";
import { sectionLabel } from "../sectionLabels";

// ──────────────────────────────────────────────────────────────────────────────
// Types
// ──────────────────────────────────────────────────────────────────────────────

interface Props {
  workspaceSlug: string;
  /** Full template list (null = still loading). */
  templates: { id: string; name: string }[] | null;
  currentTemplateId: string;
  /** Whether the current template has a parsed example spec (BeatEditor). */
  hasExample: boolean;
  /** Beats of the current template's example spec. */
  beats: { id: string; kind: string; seconds: number }[];
}

// ──────────────────────────────────────────────────────────────────────────────
// Section definitions
// ──────────────────────────────────────────────────────────────────────────────

const SECTIONS = [
  { label: "Metadata",        id: "tpl-section-metadata"  },
  { label: "Demo / example",  id: "tpl-section-demo"      },
] as const;

// ──────────────────────────────────────────────────────────────────────────────
// Scroll helpers
// ──────────────────────────────────────────────────────────────────────────────

function scrollToSection(sectionId: string) {
  document.getElementById(sectionId)?.scrollIntoView({ behavior: "smooth", block: "start" });
}

function scrollToBeat(id: string) {
  document.getElementById(`beat-${id}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
}

// ──────────────────────────────────────────────────────────────────────────────
// Component
// ──────────────────────────────────────────────────────────────────────────────

/**
 * Left-rail navigator for the template editor.
 *
 * Top level: the full template list (same as the old flat nav).
 * Expanded level (current template only): the 4 editor sections.
 * Under Demo / example: individual beat items, identical to VideoNavRail.
 */
export function TemplateNavRail({
  workspaceSlug,
  templates,
  currentTemplateId,
  hasExample,
  beats,
}: Props) {
  const navigate = useNavigate();

  // Whether the current template's section group is expanded (default: yes).
  const [sectionsOpen, setSectionsOpen] = useState(true);
  // Whether the Demo sub-group is expanded (default: yes).
  const [demoOpen, setDemoOpen] = useState(true);

  // Loading state
  if (templates === null) {
    return (
      <div className="space-y-1 p-2">
        <Skeleton className="h-8 w-full" />
        <Skeleton className="h-8 w-full" />
        <Skeleton className="h-8 w-full" />
      </div>
    );
  }

  if (templates.length === 0) {
    return (
      <p className="p-3 text-xs text-muted-foreground">No templates found.</p>
    );
  }

  return (
    <div className="flex flex-col text-sm">
      <div className="flex flex-col py-1">
        {templates.map((t) => {
          const isCurrent = t.id === currentTemplateId;

          return (
            <div key={t.id}>
              {/* ── Template row ─────────────────────────────────────────── */}
              <div
                className={`group flex items-center gap-1 px-2 py-1.5 ${
                  isCurrent ? "bg-muted" : "hover:bg-muted/60"
                }`}
              >
                {/* Chevron for expand/collapse — only on the current template */}
                {isCurrent ? (
                  <button
                    type="button"
                    onClick={() => setSectionsOpen((v) => !v)}
                    className="flex h-5 w-5 shrink-0 items-center justify-center rounded text-muted-foreground hover:text-foreground"
                    aria-label={sectionsOpen ? `Collapse ${t.name}` : `Expand ${t.name}`}
                    aria-expanded={sectionsOpen}
                  >
                    {sectionsOpen ? (
                      <ChevronDown className="h-3.5 w-3.5" />
                    ) : (
                      <ChevronRight className="h-3.5 w-3.5" />
                    )}
                  </button>
                ) : (
                  <span className="flex h-5 w-5 shrink-0 items-center justify-center text-muted-foreground/40">
                    <FileVideo className="h-3.5 w-3.5" />
                  </span>
                )}

                {/* Template name button */}
                <button
                  type="button"
                  onClick={() =>
                    navigate(`/w/${workspaceSlug}/videos/templates/${t.id}`)
                  }
                  className={`flex flex-1 items-center truncate text-left ${
                    isCurrent
                      ? "font-medium text-foreground"
                      : "text-muted-foreground hover:text-foreground"
                  }`}
                  title={t.name}
                >
                  <span className="truncate">{t.name}</span>
                </button>
              </div>

              {/* ── Sections (only for the current template when expanded) ── */}
              {isCurrent && sectionsOpen ? (
                <div className="flex flex-col">
                  {SECTIONS.map((sec) => {
                    const isDemo = sec.id === "tpl-section-demo";
                    return (
                      <div key={sec.id}>
                        {/* Section row */}
                        <div className="flex items-center gap-1 pl-6">
                          {isDemo ? (
                            <button
                              type="button"
                              onClick={() => setDemoOpen((v) => !v)}
                              className="flex h-5 w-5 shrink-0 items-center justify-center rounded text-muted-foreground hover:text-foreground"
                              aria-label={demoOpen ? "Collapse demo beats" : "Expand demo beats"}
                              aria-expanded={demoOpen}
                            >
                              {demoOpen ? (
                                <ChevronDown className="h-3.5 w-3.5" />
                              ) : (
                                <ChevronRight className="h-3.5 w-3.5" />
                              )}
                            </button>
                          ) : (
                            <span className="h-5 w-5 shrink-0" />
                          )}
                          <button
                            type="button"
                            onClick={() => scrollToSection(sec.id)}
                            className="flex-1 truncate py-1.5 text-left text-xs text-muted-foreground hover:bg-muted/60 hover:text-foreground"
                          >
                            {sec.label}
                          </button>
                        </div>

                        {/* Beat sub-items under Demo / example */}
                        {isDemo && demoOpen ? (
                          hasExample && beats.length > 0 ? (
                            <div className="flex flex-col">
                              {beats.map((b) => (
                                <button
                                  key={b.id}
                                  type="button"
                                  onClick={() => scrollToBeat(b.id)}
                                  className="truncate py-1 pl-14 pr-3 text-left text-xs text-muted-foreground hover:bg-muted/60 hover:text-foreground"
                                  title={sectionLabel(b.id).name}
                                >
                                  {sectionLabel(b.id).name}
                                </button>
                              ))}
                            </div>
                          ) : (
                            <p className="py-1 pl-14 text-xs text-muted-foreground/60">
                              No demo
                            </p>
                          )
                        ) : null}
                      </div>
                    );
                  })}
                </div>
              ) : null}
            </div>
          );
        })}
      </div>
    </div>
  );
}
