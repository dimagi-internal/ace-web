import { useEffect, useState } from "react";

import { artifactBodyUrl } from "@/api/opps";
import { MarkdownRenderer } from "@/components/MarkdownRenderer";

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
    | { kind: "loaded"; content: string; rendered: "markdown" | "code" }
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
          setState({ kind: "loaded", content, rendered: "markdown" });
        } else if (isYaml || isJson) {
          const lang = isYaml ? "yaml" : "json";
          setState({
            kind: "loaded",
            content: `\`\`\`${lang}\n${content}\n\`\`\``,
            rendered: "markdown",
          });
        } else {
          setState({ kind: "loaded", content, rendered: "code" });
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
