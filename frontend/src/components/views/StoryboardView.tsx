import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ChevronLeft, ChevronRight, Play, Pause } from "lucide-react";

import { getOpp } from "@/api/opps";
import type { OppSnapshot, Step } from "@/api/types";

interface Props {
  oppSlug: string;
  workspaceSlug: string;
  runId: string;
}

interface Slide {
  /** Caption shown above the artifact. */
  title: string;
  /** Subtitle / phase label. */
  subtitle: string;
  /** Step skill name (link target). */
  stepSkill: string;
  /** Body of the highlighted artifact, or null when the artifact is binary / missing. */
  body: string | null;
  /** Score/badge to render on the slide. */
  score: number | null;
  passed: boolean | null;
  /** First artifact's filename for the file chip. */
  artifactName: string | null;
}

/**
 * Storyboarded walkthrough of a single run. Auto-curates the highlight
 * reel: PDD → CommCare apps → Connect setup → OCS chatbot → training
 * deck → solicitation. Click ▶ to auto-advance every 6s, or use ‹ ›
 * to drive manually.
 *
 * The view picks one canonical artifact per "story beat" (a narrow
 * subset of the lifecycle skills) and shows its body inline. For
 * skills the run hasn't reached, the slide is skipped.
 *
 * No backend work needed — uses the existing snapshot endpoint and
 * reads bodies via step_detail when the operator advances.
 */

const STORY_BEATS: { skill: string; title: string }[] = [
  { skill: "idea-to-pdd", title: "The brief" },
  { skill: "pdd-to-test-prompts", title: "How we'll evaluate the chatbot" },
  { skill: "pdd-to-learn-app", title: "What FLWs will learn" },
  { skill: "pdd-to-deliver-app", title: "What FLWs will collect" },
  { skill: "app-deploy", title: "App ships to CommCare" },
  { skill: "connect-program-setup", title: "Connect program" },
  { skill: "connect-opp-setup", title: "Connect opportunity" },
  { skill: "ocs-agent-setup", title: "Chatbot persona" },
  { skill: "ocs-chatbot-qa", title: "Chatbot in action" },
  { skill: "ocs-chatbot-eval", title: "Chatbot graded" },
  { skill: "training-deck-outline", title: "Training deck" },
  { skill: "solicitation-create", title: "Solicitation drafted" },
  { skill: "synthetic-summary", title: "Synthetic walk-through" },
  { skill: "opp-eval", title: "Run scorecard" },
];

export function StoryboardView({ oppSlug, workspaceSlug, runId }: Props) {
  const [snap, setSnap] = useState<OppSnapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [idx, setIdx] = useState(0);
  const [playing, setPlaying] = useState(false);
  const navigate = useNavigate();

  useEffect(() => {
    getOpp(oppSlug, runId)
      .then(setSnap)
      .catch((e) => setError(String(e?.message ?? e)));
  }, [oppSlug, runId]);

  const slides = useMemo<Slide[]>(() => {
    if (!snap) return [];
    const stepBySkill = new Map<string, Step>();
    for (const s of snap.current_run.steps) stepBySkill.set(s.skill_name, s);
    const out: Slide[] = [];
    for (const beat of STORY_BEATS) {
      const step = stepBySkill.get(beat.skill);
      if (!step) continue;
      if (step.artifacts.length === 0 && !step.judge) continue;
      const primary = step.artifacts[0];
      out.push({
        title: beat.title,
        subtitle: `${step.phase_display ?? step.phase} · ${step.display_name ?? step.skill_name}`,
        stepSkill: step.skill_name,
        body: null, // hydrated lazily
        score: step.judge?.score_pct ?? step.judge?.score ?? null,
        passed: step.judge?.passed ?? null,
        artifactName: primary?.name ?? null,
      });
    }
    return out;
  }, [snap]);

  const slide = slides[idx];

  // Lazy body fetch when the slide changes — avoids paying the full
  // step-detail cost for every slide upfront.
  const [body, setBody] = useState<string | null>(null);
  useEffect(() => {
    if (!slide || !snap) {
      setBody(null);
      return;
    }
    let cancelled = false;
    setBody(null);
    fetch(
      `/ace/api/opps/${encodeURIComponent(oppSlug)}/runs/${encodeURIComponent(runId)}/steps/${encodeURIComponent(slide.stepSkill)}`,
      { credentials: "include" },
    )
      .then((r) => r.json())
      .then((j) => {
        if (cancelled) return;
        const data = j?.data ?? {};
        setBody((data.primary_body as string | null) ?? null);
      })
      .catch(() => !cancelled && setBody(null));
    return () => {
      cancelled = true;
    };
  }, [slide, snap, oppSlug, runId]);

  // Auto-advance.
  useEffect(() => {
    if (!playing || slides.length === 0) return;
    const id = setInterval(() => {
      setIdx((i) => (i + 1 < slides.length ? i + 1 : i));
    }, 6000);
    return () => clearInterval(id);
  }, [playing, slides.length]);

  if (error)
    return (
      <div className="p-6 text-sm text-destructive">
        Couldn't load storyboard: {error}
      </div>
    );
  if (!snap)
    return <div className="p-6 text-sm text-muted-foreground">Loading…</div>;
  if (slides.length === 0) {
    return (
      <div className="p-6 text-sm text-muted-foreground">
        Nothing to show yet — the run hasn't produced any of the canonical
        story beats. Run the lifecycle to see this view light up.
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col bg-background">
      {/* Slide chrome — title, score, controls */}
      <div className="flex items-center gap-3 border-b border-border px-6 py-3">
        <button
          type="button"
          onClick={() => setPlaying((p) => !p)}
          className="flex items-center gap-1 rounded border border-input
            bg-card px-3 py-1 text-xs text-foreground hover:bg-accent"
        >
          {playing ? (
            <>
              <Pause className="h-3 w-3" /> Pause
            </>
          ) : (
            <>
              <Play className="h-3 w-3" /> Play
            </>
          )}
        </button>
        <button
          type="button"
          onClick={() => setIdx((i) => Math.max(0, i - 1))}
          disabled={idx === 0}
          className="rounded border border-input bg-card p-1 text-foreground
            hover:bg-accent disabled:opacity-30"
        >
          <ChevronLeft className="h-4 w-4" />
        </button>
        <button
          type="button"
          onClick={() => setIdx((i) => Math.min(slides.length - 1, i + 1))}
          disabled={idx === slides.length - 1}
          className="rounded border border-input bg-card p-1 text-foreground
            hover:bg-accent disabled:opacity-30"
        >
          <ChevronRight className="h-4 w-4" />
        </button>
        <span className="text-xs text-muted-foreground">
          {idx + 1} / {slides.length}
        </span>
        <div className="ml-auto text-xs text-muted-foreground">
          {snap.opp.display_name || snap.opp.slug} · run {runId}
        </div>
      </div>

      {/* Slide body */}
      <div className="flex-1 overflow-y-auto px-12 py-6">
        <div className="mx-auto max-w-4xl">
          <div className="text-[10px] uppercase tracking-wider text-muted-foreground">
            {slide.subtitle}
          </div>
          <h1 className="mt-1 text-2xl font-semibold text-foreground">
            {slide.title}
          </h1>

          <div className="mt-3 flex flex-wrap items-center gap-3 text-xs">
            {slide.score !== null && (
              <span
                className={
                  "rounded-full px-2 py-0.5 " +
                  (slide.passed === false
                    ? "border border-rose-500/40 bg-rose-500/10 text-rose-500"
                    : slide.passed === true
                      ? "border border-emerald-500/40 bg-emerald-500/10 text-emerald-500"
                      : "border border-border bg-muted text-muted-foreground")
                }
              >
                Judge {Math.round(slide.score)}/100
                {slide.passed === true && " · pass"}
                {slide.passed === false && " · fail"}
              </span>
            )}
            {slide.artifactName && (
              <button
                type="button"
                onClick={() =>
                  navigate(
                    `/w/${workspaceSlug}/opps/${oppSlug}/runs/${runId}/steps/${slide.stepSkill}`,
                  )
                }
                className="flex items-center gap-1 rounded border border-border
                  bg-card px-2 py-0.5 text-foreground hover:bg-accent"
              >
                📄 {slide.artifactName}
              </button>
            )}
          </div>

          <article className="mt-6 rounded-lg border border-border bg-card
            p-6 text-sm leading-relaxed text-foreground">
            {body === null ? (
              <span className="text-muted-foreground">Loading content…</span>
            ) : body === "" ? (
              <span className="text-muted-foreground italic">
                (No primary artifact body to display.)
              </span>
            ) : (
              <pre className="whitespace-pre-wrap font-sans">
                {body.length > 4000 ? body.slice(0, 4000) + "\n\n…" : body}
              </pre>
            )}
          </article>
        </div>
      </div>

      {/* Filmstrip */}
      <div className="border-t border-border px-4 py-2">
        <div className="flex gap-1 overflow-x-auto">
          {slides.map((s, i) => (
            <button
              key={s.stepSkill}
              type="button"
              onClick={() => setIdx(i)}
              className={
                "shrink-0 rounded px-2 py-1 text-[10px] " +
                (i === idx
                  ? "bg-primary text-primary-foreground"
                  : "bg-muted text-muted-foreground hover:bg-accent hover:text-foreground")
              }
              title={s.subtitle}
            >
              {s.title}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
