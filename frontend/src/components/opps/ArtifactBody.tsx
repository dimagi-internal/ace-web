import { useEffect, useState } from "react";
import { ExternalLink, RefreshCw } from "lucide-react";

import { artifactBodyUrl } from "@/api/opps";
import { MarkdownRenderer } from "@/components/MarkdownRenderer";
import { PatientLoader } from "@/components/opps/LoadingStates";
import { parseFrontmatter, type Frontmatter } from "@/lib/frontmatter";

const URL_RE = /^https?:\/\/\S+$/;

const MAX_BYTES = 50 * 1024;

interface Props {
  workspaceSlug: string;
  slug: string;
  runId: string;
  skill: string;
  artifactName: string;
  mimeType: string;
  webViewLink?: string;
  driveFileId?: string;
}

export function ArtifactBody({ workspaceSlug, slug, runId, artifactName, mimeType, webViewLink, driveFileId }: Props) {
  const [state, setState] = useState<
    | { kind: "loading" }
    | { kind: "error"; message: string }
    | { kind: "too-large"; size: number }
    | {
        kind: "loaded";
        content: string;
        rendered: "markdown" | "code";
        metadata: Frontmatter | null;
      }
  >({ kind: "loading" });
  // Bumped by the Retry button to force the loader effect to re-run on
  // the same URL (the dependency array intentionally does not include
  // mutable state).
  const [retryNonce, setRetryNonce] = useState(0);

  useEffect(() => {
    setState({ kind: "loading" });
    if (!driveFileId) {
      // The download endpoint is keyed by the artifact's Drive file id;
      // without it there is nothing to fetch. Fall through to the error
      // state, which offers the Drive web link as a fallback.
      setState({ kind: "error", message: "No Drive file id for this artifact" });
      return;
    }
    const url = artifactBodyUrl(workspaceSlug, slug, runId, driveFileId);
    let cancelled = false;
    fetch(url, { credentials: "include" })
      .then(async (r) => {
        if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
        return r.text();
      })
      .then((content) => {
        if (cancelled) return;
        if (content.length > MAX_BYTES) {
          setState({ kind: "too-large", size: content.length });
          return;
        }
        const isMd = artifactName.endsWith(".md") || mimeType.startsWith("text/markdown");
        const isYaml = artifactName.endsWith(".yaml") || artifactName.endsWith(".yml");
        const isJson = artifactName.endsWith(".json");
        if (isMd) {
          const { metadata, body } = parseFrontmatter(content);
          setState({ kind: "loaded", content: body, rendered: "markdown", metadata });
        } else if (isYaml || isJson) {
          const lang = isYaml ? "yaml" : "json";
          setState({
            kind: "loaded",
            content: `\`\`\`${lang}\n${content}\n\`\`\``,
            rendered: "markdown",
            metadata: null,
          });
        } else {
          setState({ kind: "loaded", content, rendered: "code", metadata: null });
        }
      })
      .catch((err) => {
        if (cancelled) return;
        setState({ kind: "error", message: String(err.message ?? err) });
      });
    return () => {
      cancelled = true;
    };
  }, [workspaceSlug, slug, runId, driveFileId, artifactName, mimeType, retryNonce]);

  if (state.kind === "loading") {
    return (
      <PatientLoader
        label="Loading…"
        slowLabel="Drive is slow today — still fetching this artifact."
        className="p-3 text-xs"
      />
    );
  }
  if (state.kind === "error") {
    // Prefer the Drive web link the API gave us; fall back to the
    // canonical /file/d/<id>/view URL if we only have the file_id.
    const driveHref =
      webViewLink ||
      (driveFileId ? `https://drive.google.com/file/d/${driveFileId}/view` : null);
    return (
      <div className="p-3 text-xs text-destructive">
        <div>Couldn't load this artifact.</div>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => setRetryNonce((n) => n + 1)}
            className="inline-flex items-center gap-1 rounded border border-destructive/40 bg-destructive/10 px-2 py-1 text-[11px] font-medium text-destructive hover:bg-destructive/20"
            aria-label="Retry loading this artifact"
          >
            <RefreshCw className="h-3 w-3" />
            Retry load
          </button>
          {driveHref && (
            <a
              href={driveHref}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 rounded border border-border bg-card px-2 py-1 text-[11px] font-medium text-foreground hover:bg-accent"
            >
              <ExternalLink className="h-3 w-3" />
              Open in Drive
            </a>
          )}
        </div>
        <details className="mt-2 opacity-70">
          <summary className="cursor-pointer">details</summary>
          <pre className="mt-1 whitespace-pre-wrap break-all">{state.message}</pre>
        </details>
      </div>
    );
  }
  if (state.kind === "too-large") {
    return (
      <div className="p-3 text-xs text-muted-foreground">
        File is {(state.size / 1024).toFixed(1)} KB — too large to render inline.{" "}
        {webViewLink && (
          <a href={webViewLink} target="_blank" rel="noopener noreferrer" className="text-primary underline">
            Open in Drive
          </a>
        )}
      </div>
    );
  }
  if (state.rendered === "markdown") {
    return (
      <div className="p-3">
        {state.metadata && state.metadata.length > 0 && (
          <dl className="mb-4 grid grid-cols-[max-content_1fr] gap-x-3 gap-y-1 rounded-md border border-border bg-muted/30 px-3 py-2 text-xs">
            {state.metadata.map(([key, value]) => (
              <div key={key} className="contents">
                <dt className="font-medium text-muted-foreground">{key}</dt>
                <dd className="truncate text-foreground" title={value}>
                  {URL_RE.test(value) ? (
                    <a
                      href={value}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex items-center gap-1 text-primary hover:underline"
                    >
                      <span className="truncate">{value}</span>
                      <ExternalLink className="h-3 w-3 shrink-0" />
                    </a>
                  ) : (
                    value
                  )}
                </dd>
              </div>
            ))}
          </dl>
        )}
        <MarkdownRenderer content={state.content} />
      </div>
    );
  }
  return (
    <pre className="overflow-x-auto p-3 font-mono text-xs text-muted-foreground">
      {state.content}
    </pre>
  );
}
