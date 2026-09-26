import { useEffect, useState } from "react";
import { ExternalLink, RefreshCw } from "lucide-react";

import { MarkdownRenderer } from "@/components/MarkdownRenderer";
import { PatientLoader } from "@/components/opps/LoadingStates";
import { parseFrontmatter } from "@/lib/frontmatter";

import { loadView, type ViewResult } from "./viewCache";

interface Props {
  /** The view endpoint URL (`artifactViewUrl`). */
  url: string;
  /** Fallback link when the file can't be drawn in the page. */
  driveLink?: string | null;
  /** Height for the embedded media (PDF, video). */
  mediaHeight?: string;
}

/**
 * One Drive file, drawn in the page: a Doc as a document, a deck as its PDF,
 * a sheet as a table, screenshots and recordings as themselves.
 *
 * It renders whatever the view endpoint says the file IS (by Content-Type),
 * so it needs no knowledge of which skill made it — the same component opens
 * a PDD, a training deck and a device-walk screenshot.
 */
export function DriveFileViewer({ url, driveLink, mediaHeight = "70vh" }: Props) {
  const [result, setResult] = useState<ViewResult | null>(null);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setResult(null);
    loadView(url).then((r) => {
      if (!cancelled) setResult(r);
    });
    return () => {
      cancelled = true;
    };
  }, [url, nonce]);

  if (!result) {
    return (
      <PatientLoader
        label="Opening…"
        slowLabel="Drive is slow today — still fetching this file."
        className="p-4 text-xs"
      />
    );
  }

  const link = ("driveLink" in result ? result.driveLink : null) ?? driveLink ?? null;

  switch (result.kind) {
    case "error":
      return (
        <div className="flex flex-col items-start gap-2 p-4 text-sm">
          <p className="text-muted-foreground">
            {result.status === 415
              ? "This kind of file can't be shown in the page."
              : result.status === 413
                ? "This file is too large to show in the page."
                : `Couldn't open this file (${result.message}).`}
          </p>
          <div className="flex gap-2">
            {result.status !== 415 && result.status !== 413 && (
              <button
                type="button"
                onClick={() => setNonce((n) => n + 1)}
                className="inline-flex items-center gap-1 rounded border border-border px-2 py-1 text-xs hover:bg-accent"
              >
                <RefreshCw className="h-3 w-3" /> Try again
              </button>
            )}
            {link && <OpenLink href={link} label="Open in Drive" />}
          </div>
        </div>
      );
    case "markdown": {
      const { metadata, body } = parseFrontmatter(result.text);
      return (
        <div className="px-1">
          {metadata && metadata.length > 0 && (
            <dl className="mb-4 grid grid-cols-[max-content_1fr] gap-x-3 gap-y-1 rounded-md border border-border bg-muted/30 px-3 py-2 text-xs">
              {metadata.map(([k, v]) => (
                <div key={k} className="contents">
                  <dt className="font-medium text-muted-foreground">{k}</dt>
                  <dd className="truncate text-foreground" title={v}>
                    {v}
                  </dd>
                </div>
              ))}
            </dl>
          )}
          <MarkdownRenderer content={body} />
        </div>
      );
    }
    case "csv":
      return <CsvTable rows={result.rows} truncated={result.truncated} />;
    case "text":
      return (
        <pre className="overflow-x-auto whitespace-pre-wrap break-words rounded bg-muted/30 p-3 font-mono text-xs text-muted-foreground">
          {result.text}
        </pre>
      );
    case "pdf":
      return (
        <iframe
          src={result.objectUrl}
          title={result.name ?? "Document"}
          className="w-full rounded border border-border bg-white"
          style={{ height: mediaHeight }}
        />
      );
    case "image":
      return (
        <img
          src={result.objectUrl}
          alt={result.name ?? ""}
          className="mx-auto max-w-full rounded border border-border object-contain"
          style={{ maxHeight: mediaHeight }}
        />
      );
    case "video":
      return (
        <video
          src={result.objectUrl}
          controls
          className="mx-auto w-full rounded border border-border bg-black"
          style={{ maxHeight: mediaHeight }}
        />
      );
  }
}

function CsvTable({ rows, truncated }: { rows: string[][]; truncated: boolean }) {
  if (rows.length === 0) {
    return <p className="p-4 text-sm text-muted-foreground">This sheet is empty.</p>;
  }
  const [head, ...body] = rows;
  return (
    <div className="overflow-auto rounded border border-border">
      <table className="w-full border-collapse text-xs">
        <thead className="sticky top-0 bg-muted">
          <tr>
            {head.map((h, i) => (
              <th key={i} className="border-b border-border px-2 py-1.5 text-left font-semibold">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {body.map((r, i) => (
            <tr key={i} className="odd:bg-muted/20">
              {r.map((cell, j) => (
                <td key={j} className="border-b border-border/50 px-2 py-1 align-top text-muted-foreground">
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {truncated && (
        <p className="p-2 text-[11px] text-muted-foreground">Showing the first rows only.</p>
      )}
    </div>
  );
}

export function OpenLink({ href, label }: { href: string; label: string }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="inline-flex items-center gap-1 rounded border border-border bg-card px-2 py-1 text-xs font-medium text-foreground hover:bg-accent"
    >
      <ExternalLink className="h-3 w-3" />
      {label}
    </a>
  );
}
