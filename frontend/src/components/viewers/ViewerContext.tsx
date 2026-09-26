import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";

import { artifactViewUrl } from "@/api/opps";
import type { PhaseInfo, RunProduct, Step } from "@/api/types.ws";
import { Glossed } from "@/components/glossary/Glossed";
import { OcsWidgetMount } from "@/components/opps/summary/OcsWidgetMount";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "canopy-ui/ui";

import { DriveFileViewer, OpenLink } from "./DriveFileViewer";
import { kindMeta } from "./productKinds";
import { ProductBody, type ViewerRun } from "./ProductViewer";

/** Something the viewer can open. */
export type ViewerTarget =
  | { readonly type: "product"; readonly product: RunProduct }
  | {
      readonly type: "file";
      readonly fileId: string;
      readonly name: string;
      readonly driveLink?: string | null;
      /** The skill that wrote it, for the header. */
      readonly skill?: string | null;
    };

interface ViewerApi {
  readonly run: ViewerRun;
  readonly open: (target: ViewerTarget) => void;
  /** "Phase 3 · CommCare Setup", or null for an unknown phase. */
  readonly phaseLabel: (phase: string | null | undefined) => string | null;
  /** A skill's display name, falling back to its slug. */
  readonly skillLabel: (skill: string | null | undefined) => string | null;
  /** Mount the live OCS widget (corner bubble) for a chatbot. */
  readonly talkTo: (chatbot: NonNullable<RunProduct["chatbot"]>) => void;
}

const ViewerContext = createContext<ViewerApi | null>(null);

interface ProviderProps {
  workspaceSlug: string;
  oppSlug: string;
  runId: string;
  steps: readonly Step[];
  phases: readonly PhaseInfo[];
  children: ReactNode;
}

/**
 * One viewer for everything a run made, openable from anywhere beneath it.
 *
 * The Workbench's right rail was the original viewer and is a poor one for
 * most of what ACE produces now — decks, apps, dashboards. This is a dialog
 * sized for them, and a context so the products strip, a skill's artifact
 * list, the flow panel and the replay spotlight all open the same thing.
 * Nothing in it assumes the Phases screen, so a later page (the canopy chat
 * widget's host, say) can wrap itself in the same provider.
 */
export function ViewerProvider({
  workspaceSlug,
  oppSlug,
  runId,
  steps,
  phases,
  children,
}: ProviderProps) {
  const [target, setTarget] = useState<ViewerTarget | null>(null);
  const [chatbot, setChatbot] = useState<NonNullable<RunProduct["chatbot"]> | null>(null);

  const run = useMemo<ViewerRun>(
    () => ({
      workspaceSlug,
      oppSlug,
      runId,
      steps,
      viewUrl: (fileId: string) => artifactViewUrl(workspaceSlug, oppSlug, runId, fileId),
    }),
    [workspaceSlug, oppSlug, runId, steps],
  );

  const phaseLabel = useCallback(
    (phase: string | null | undefined) => {
      const info = phase ? phases.find((p) => p.name === phase) : undefined;
      return info ? `Phase ${info.ordinal} · ${info.display_name}` : null;
    },
    [phases],
  );
  const skillLabel = useCallback(
    (skill: string | null | undefined) => {
      if (!skill) return null;
      return steps.find((s) => s.skill_name === skill)?.display_name || skill;
    },
    [steps],
  );
  const talkTo = useCallback((bot: NonNullable<RunProduct["chatbot"]>) => {
    setTarget(null);
    setChatbot(bot);
  }, []);

  const api = useMemo<ViewerApi>(
    () => ({ run, open: setTarget, phaseLabel, skillLabel, talkTo }),
    [run, phaseLabel, skillLabel, talkTo],
  );

  return (
    <ViewerContext.Provider value={api}>
      {children}
      <ViewerDialog target={target} onClose={() => setTarget(null)} />
      {chatbot && <OcsWidgetMount chatbotId={chatbot.public_id} embedKey={chatbot.embed_key} />}
    </ViewerContext.Provider>
  );
}

export function useViewer(): ViewerApi | null {
  return useContext(ViewerContext);
}

function ViewerDialog({ target, onClose }: { target: ViewerTarget | null; onClose: () => void }) {
  const api = useViewer();
  if (!api) return null;
  return (
    <Dialog open={target !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="flex max-h-[90vh] max-w-5xl flex-col gap-3">
        {target && (
          <DialogHeader className="pr-8">
            <DialogTitle className="sr-only">{targetTitle(target)}</DialogTitle>
            <DialogDescription className="sr-only">In-page viewer</DialogDescription>
            <ViewerHeading target={target} />
          </DialogHeader>
        )}
        <div className="min-h-0 flex-1 overflow-y-auto pr-1">
          {target?.type === "product" && (
            <ProductBody product={target.product} run={api.run} onTalk={api.talkTo} />
          )}
          {target?.type === "file" && (
            <DriveFileViewer url={api.run.viewUrl(target.fileId)} driveLink={target.driveLink} />
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}

export function targetTitle(target: ViewerTarget): string {
  return target.type === "product" ? target.product.title : target.name;
}

/** Title + provenance line: what it is, which phase, which skill made it.
 *  Plain markup (no dialog primitives) so the replay spotlight can use it. */
export function ViewerHeading({ target, eyebrow }: { target: ViewerTarget; eyebrow?: ReactNode }) {
  const api = useViewer();
  const product = target.type === "product" ? target.product : null;
  const meta = product ? kindMeta(product.kind) : kindMeta("document");
  const skill = product ? product.producer : target.type === "file" ? target.skill : null;
  const provenance = [
    product ? meta.label : null,
    product ? api?.phaseLabel(product.phase) : null,
    skill ? `made by ${api?.skillLabel(skill) ?? skill}` : null,
  ]
    .filter(Boolean)
    .join(" · ");
  const link = product ? product.url : target.type === "file" ? target.driveLink : null;

  return (
    <div className="flex flex-col gap-1.5 text-left">
      {eyebrow}
      <div className="flex items-center gap-2 text-lg font-semibold leading-snug text-foreground">
        <meta.icon className="h-5 w-5 shrink-0 text-primary" aria-hidden />
        <span className="min-w-0">
          <Glossed text={targetTitle(target)} />
        </span>
      </div>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
        {provenance && (
          <span>
            <Glossed text={provenance} />
          </span>
        )}
        {link && <OpenLink href={link} label={product ? meta.openLabel : "Open in Drive"} />}
      </div>
    </div>
  );
}
