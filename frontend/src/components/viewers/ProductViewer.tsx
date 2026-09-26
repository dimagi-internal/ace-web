import { MessageCircle } from "lucide-react";

import type { Artifact, RunProduct, Step } from "@/api/types.ws";
import { Glossed } from "@/components/glossary/Glossed";

import { DriveFileViewer } from "./DriveFileViewer";
import { kindMeta } from "./productKinds";

/** What a viewer needs to know about the run it is showing. */
export interface ViewerRun {
  readonly workspaceSlug: string;
  readonly oppSlug: string;
  readonly runId: string;
  readonly steps: readonly Step[];
  /** Builds the view-endpoint URL for a Drive file of this run. */
  readonly viewUrl: (fileId: string) => string;
}

interface Props {
  product: RunProduct;
  run: ViewerRun;
  /** Media height inside the body (PDFs, video). */
  mediaHeight?: string;
  /** Mount the live OCS widget for a chatbot product. */
  onTalk?: (chatbot: NonNullable<RunProduct["chatbot"]>) => void;
}

/**
 * The body of a product's viewer — what it is, drawn the way that makes sense
 * for its kind. A Drive file renders in place; a live thing in another system
 * (an app on HQ, an opportunity on Connect, a dashboard on Labs) renders as a
 * card with its facts, one line on what it is, and the link to the real one.
 */
export function ProductBody({ product, run, mediaHeight, onTalk }: Props) {
  const meta = kindMeta(product.kind);

  if (product.file_id && ["document", "deck", "sheet"].includes(product.kind)) {
    return (
      <div className="flex flex-col gap-3">
        {product.subtitle && (
          <p className="text-sm text-muted-foreground">
            <Glossed text={product.subtitle} />
          </p>
        )}
        <DriveFileViewer
          url={run.viewUrl(product.file_id)}
          driveLink={product.url}
          mediaHeight={mediaHeight}
          pdfUnit={product.kind === "deck" ? "Slide" : "Page"}
        />
      </div>
    );
  }

  const structure = product.kind === "commcare_app" ? appStructureArtifact(product, run.steps) : null;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-start gap-4 rounded-lg border border-border bg-muted/20 p-4">
        <meta.icon className="mt-0.5 h-8 w-8 shrink-0 text-primary" aria-hidden />
        <div className="min-w-0 flex-1">
          <p className="text-sm text-muted-foreground">
            <Glossed text={meta.blurb} />
          </p>
          {product.subtitle && (
            <p className="mt-2 text-sm text-foreground">
              <Glossed text={product.subtitle} />
            </p>
          )}
          {product.facts.length > 0 && (
            <dl className="mt-3 flex flex-wrap gap-x-6 gap-y-1 text-xs">
              {product.facts.map((f) => (
                <div key={f.label} className="flex gap-1.5">
                  <dt className="text-muted-foreground">{f.label}</dt>
                  <dd className="font-medium text-foreground">{f.value}</dd>
                </div>
              ))}
            </dl>
          )}
          {product.chatbot && onTalk && (
            <button
              type="button"
              onClick={() => onTalk(product.chatbot!)}
              className="mt-3 inline-flex items-center gap-1 rounded border border-primary/50 bg-primary/10 px-2 py-1 text-xs font-medium text-primary hover:bg-primary/20"
            >
              <MessageCircle className="h-3 w-3" /> Talk to it
            </button>
          )}
        </div>
      </div>
      {structure && (
        <section>
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            How it's built
          </h3>
          <DriveFileViewer
            url={run.viewUrl(structure.drive_file_id)}
            driveLink={structure.drive_web_link}
            mediaHeight={mediaHeight}
          />
        </section>
      )}
    </div>
  );
}

/**
 * The structure summary the app's build skill wrote — its first prose
 * artifact. Uses the plugin's attribution when there is one; otherwise the
 * two build skills' canonical names, which is the only other honest link
 * between `apps.learn` and the step that built it.
 */
export function appStructureArtifact(product: RunProduct, steps: readonly Step[]): Artifact | null {
  const lowered = product.key.toLowerCase();
  const fallback = lowered.includes("learn")
    ? "pdd-to-learn-app"
    : lowered.includes("deliver")
      ? "pdd-to-deliver-app"
      : null;
  const skill = product.producer ?? fallback;
  const step = skill ? steps.find((s) => s.skill_name === skill) : undefined;
  return step?.artifacts.find((a) => /\.(md|markdown)$/i.test(a.name || a.path)) ?? null;
}
