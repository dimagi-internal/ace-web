import { useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { AlertTriangle, ExternalLink, Library } from "lucide-react";

import { Badge } from "@canopy/workbench/ui";
import { Skeleton } from "@canopy/workbench/ui";
import {
  listMediaLibraryAudio,
  listMediaLibraryVideo,
  type MediaLibraryAudioOut,
  type MediaLibraryVideoOut,
} from "@/api/videos";

type Tab = "video" | "audio";

export default function MediaLibraryPage() {
  const { workspaceSlug } = useParams<{ workspaceSlug: string }>();
  const [params, setParams] = useSearchParams();
  const tab: Tab = params.get("type") === "audio" ? "audio" : "video";

  const [video, setVideo] = useState<MediaLibraryVideoOut | null>(null);
  const [audio, setAudio] = useState<MediaLibraryAudioOut | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!workspaceSlug) return;
    let cancelled = false;
    if (tab === "video" && video === null) {
      listMediaLibraryVideo(workspaceSlug)
        .then((d) => {
          if (!cancelled) setVideo(d);
        })
        .catch((e: unknown) => {
          if (!cancelled) setError(e instanceof Error ? e.message : String(e));
        });
    } else if (tab === "audio" && audio === null) {
      listMediaLibraryAudio(workspaceSlug)
        .then((d) => {
          if (!cancelled) setAudio(d);
        })
        .catch((e: unknown) => {
          if (!cancelled) setError(e instanceof Error ? e.message : String(e));
        });
    }
    return () => {
      cancelled = true;
    };
  }, [workspaceSlug, tab, video, audio]);

  const setTab = (t: Tab) => {
    if (t === "video") params.delete("type");
    else params.set("type", "audio");
    setParams(params, { replace: true });
  };

  return (
    <div className="mx-auto max-w-5xl px-6 py-8">
      <header className="mb-6 flex items-center gap-2">
        <Library className="h-5 w-5 text-muted-foreground" />
        <h1 className="text-2xl font-semibold">Media library</h1>
        <Link
          to={`/w/${workspaceSlug}/videos`}
          className="ml-auto text-sm text-muted-foreground underline"
        >
          ← Back to programs
        </Link>
      </header>

      <div className="mb-6 flex gap-2">
        <button
          type="button"
          onClick={() => setTab("video")}
          className={`rounded px-3 py-1.5 text-sm font-medium ${
            tab === "video" ? "bg-primary text-primary-foreground" : "border"
          }`}
        >
          Video
        </button>
        <button
          type="button"
          onClick={() => setTab("audio")}
          className={`rounded px-3 py-1.5 text-sm font-medium ${
            tab === "audio" ? "bg-primary text-primary-foreground" : "border"
          }`}
        >
          Audio
        </button>
      </div>

      {error && (
        <div className="mb-4 flex items-start gap-2 rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm">
          <AlertTriangle className="mt-0.5 h-4 w-4 text-destructive" />
          <div className="text-muted-foreground">{error}</div>
        </div>
      )}

      {tab === "video"
        ? renderVideo(video)
        : renderAudio(audio, workspaceSlug ?? "")}
    </div>
  );
}

function renderVideo(data: MediaLibraryVideoOut | null) {
  if (data === null) return <Skeleton className="h-40 w-full" />;
  if (data.subfolders.length === 0) {
    return (
      <div className="rounded-md border border-dashed p-6 text-sm text-muted-foreground">
        No video clips in the library yet. Drop files into
        <code className="mx-1 rounded bg-muted px-1 py-0.5 text-xs">
          videos/library/video/&lt;category&gt;/
        </code>
        in Drive with a sibling
        <code className="mx-1 rounded bg-muted px-1 py-0.5 text-xs">&lt;name&gt;.json</code>
        sidecar.
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-8">
      {data.subfolders.map((sub) => (
        <section key={sub.subfolder}>
          <h2 className="mb-3 font-medium">{sub.subfolder}</h2>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            {sub.items.map((item) => (
              <article
                key={item.drive_id}
                className={`rounded border p-3 ${
                  item.status === "ok" ? "" : "border-dashed bg-muted/30"
                }`}
              >
                <header className="mb-1 flex items-center justify-between gap-2">
                  <h3 className="text-sm font-medium">{item.name ?? item.filename}</h3>
                  {item.status !== "ok" && (
                    <Badge variant="outline" className="text-[10px]">
                      {item.status}
                    </Badge>
                  )}
                </header>
                <p className="mb-2 font-mono text-xs text-muted-foreground">{item.filename}</p>
                {item.description && <p className="mb-2 text-sm">{item.description}</p>}
                <div className="mb-2 flex flex-wrap gap-1">
                  {item.tags.map((t) => (
                    <span key={t} className="rounded-full bg-muted px-2 py-0.5 text-xs">
                      {t}
                    </span>
                  ))}
                </div>
                <a
                  href={item.drive_url}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1 text-xs text-muted-foreground underline"
                >
                  Open in Drive <ExternalLink className="h-3 w-3" />
                </a>
              </article>
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}

function renderAudio(data: MediaLibraryAudioOut | null, workspaceSlug: string) {
  if (data === null) return <Skeleton className="h-40 w-full" />;
  if (data.items.length === 0) {
    return (
      <div className="rounded-md border border-dashed p-6 text-sm text-muted-foreground">
        No audio clips yet. They get generated automatically when a render
        synthesizes voiceover; check back after running a render.
      </div>
    );
  }
  // The library streaming endpoint is workspace-scoped. We round-trip
  // through Django so playback is Range-aware + private (Drive's preview
  // URL doesn't stream audio, it serves an HTML viewer that prompts for
  // download).
  const streamBase = `${import.meta.env.BASE_URL.replace(/\/$/, "")}/api/w/${workspaceSlug}/videos/library/audio`;
  return (
    <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
      {data.items.map((item) => (
        <article
          key={item.drive_id}
          className={`rounded border p-3 ${
            item.status === "ok" ? "" : "border-dashed bg-muted/30"
          }`}
        >
          <header className="mb-1 flex items-center gap-2">
            <code className="rounded bg-muted px-1.5 py-0.5 text-xs">{item.hash}</code>
            {item.status !== "ok" && (
              <Badge variant="outline" className="ml-auto text-[10px]">
                {item.status}
              </Badge>
            )}
          </header>
          <p className="mb-2 text-sm" title={item.text ?? ""}>
            {truncate(item.text)}
          </p>
          {item.status !== "missing-media" && (
            <audio
              controls
              preload="none"
              className="mb-2 h-9 w-full"
              src={`${streamBase}/${item.hash}/stream`}
            />
          )}
          <div className="mb-2 flex flex-wrap gap-1 text-xs text-muted-foreground">
            {item.voice_id && (
              <span className="rounded-full bg-muted px-2 py-0.5">
                voice: {item.voice_id.slice(0, 6)}…
              </span>
            )}
            {item.model && (
              <span className="rounded-full bg-muted px-2 py-0.5">{item.model}</span>
            )}
            {item.duration_sec !== null && item.duration_sec !== undefined && (
              <span className="rounded-full bg-muted px-2 py-0.5">
                {item.duration_sec.toFixed(1)}s
              </span>
            )}
          </div>
          <a
            href={item.drive_url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 text-xs text-muted-foreground underline"
          >
            Open in Drive <ExternalLink className="h-3 w-3" />
          </a>
        </article>
      ))}
    </div>
  );
}

function truncate(s: string | null | undefined, max = 140): string {
  if (!s) return "";
  return s.length <= max ? s : s.slice(0, max - 1) + "…";
}
