import { useEffect, useState } from "react";
import { ExternalLink } from "lucide-react";

import { artifactBodyUrl } from "@/api/opps";
import { MarkdownRenderer } from "@/components/MarkdownRenderer";
import { parseFrontmatter, type Frontmatter } from "@/lib/frontmatter";

const URL_RE = /^https?:\/\/\S+$/;

const MAX_BYTES = 50 * 1024;

interface Props {
  slug: string;
  runId: string;
  skill: string;
  artifactName: string;
  mimeType: string;
  webViewLink?: string;
}

export function ArtifactBody({ slug, runId, skill, artifactName, mimeType, webViewLink }: Props) {
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

  useEffect(() => {
    setState({ kind: "loading" });
    const url = artifactBodyUrl(slug, runId, skill, artifactName);
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
  }, [slug, runId, skill, artifactName, mimeType]);

  if (state.kind === "loading") {
    return <div className="p-3 text-xs text-muted-foreground">Loading…</div>;
  }
  if (state.kind === "error") {
    return <div className="p-3 text-xs text-destructive">Error: {state.message}</div>;
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
