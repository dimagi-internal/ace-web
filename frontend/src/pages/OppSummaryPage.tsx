import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { ArrowRight } from "lucide-react";

import { ApiError } from "@/api/client";
import { getPublicOppSummary, type OppSummaryPayload } from "@/api/oppSummary";
import { OcsWidgetMount } from "@/components/opps/summary/OcsWidgetMount";
import { SummaryHero } from "@/components/opps/summary/SummaryHero";
import { SummaryRow } from "@/components/opps/summary/SummaryRow";
import { SummarySection } from "@/components/opps/summary/SummarySection";

type LoadState =
  | { kind: "loading" }
  | { kind: "loaded"; payload: OppSummaryPayload }
  | { kind: "not_found" }
  | { kind: "error"; message: string };


function _formatShortDate(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const d = new Date(`${iso.slice(0, 10)}T00:00:00`);
  if (Number.isNaN(d.valueOf())) return null;
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}


function formatConnectDateRange(start?: string | null, end?: string | null): string | null {
  const s = _formatShortDate(start);
  const e = _formatShortDate(end);
  if (!s && !e) return null;
  if (s && e) {
    // Append year only on the end side, like "Jun 14 – Aug 9, 2026".
    const year = end ? end.slice(0, 4) : "";
    return year ? `${s} – ${e}, ${year}` : `${s} – ${e}`;
  }
  return s ?? e ?? null;
}

export default function OppSummaryPage() {
  const params = useParams();
  const workspace = params.workspace ?? "";
  const slug = params.slug ?? "";
  const runId = params.runId ?? "";
  const [state, setState] = useState<LoadState>({ kind: "loading" });

  useEffect(() => {
    if (!workspace || !slug || !runId) return;
    let cancelled = false;
    getPublicOppSummary(workspace, slug, runId)
      .then((payload) => { if (!cancelled) setState({ kind: "loaded", payload }); })
      .catch((e) => {
        if (cancelled) return;
        if (e instanceof ApiError && e.code === "not-found") {
          setState({ kind: "not_found" });
        } else if (e instanceof ApiError) {
          setState({ kind: "error", message: e.message });
        } else {
          setState({ kind: "error", message: "Failed to load summary." });
        }
      });
    return () => { cancelled = true; };
  }, [workspace, slug, runId]);

  if (state.kind === "loading") {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <p className="text-sm text-muted-foreground">Loading…</p>
      </div>
    );
  }

  if (state.kind === "not_found") {
    return (
      <div className="flex min-h-screen items-center justify-center px-6">
        <div className="text-center">
          <p className="text-lg font-medium text-foreground">Not found</p>
          <p className="mt-2 text-sm text-muted-foreground">
            We couldn't find this run. The link may be wrong or the run may have
            been removed.
          </p>
        </div>
      </div>
    );
  }

  if (state.kind === "error") {
    return (
      <div className="flex min-h-screen items-center justify-center px-6">
        <div className="text-center">
          <p className="text-lg font-medium text-foreground">
            Something went wrong
          </p>
          <p className="mt-2 text-sm text-muted-foreground">{state.message}</p>
        </div>
      </div>
    );
  }

  const { payload } = state;
  const { opp, apps, connect, training, assistant, open_questions, workbench_url } = payload;

  return (
    <div className="min-h-screen bg-background text-foreground">
      {/* Top utility bar — display name on the left (human-readable),
          run id on the right (technical reference). */}
      <div className="border-b border-border">
        <div className="mx-auto flex max-w-3xl items-center justify-between gap-4 px-6 py-3 text-xs">
          <div className="truncate text-muted-foreground">{opp.display_name}</div>
          <div className="font-mono tracking-tight text-muted-foreground/70">
            run {opp.run_id}
          </div>
        </div>
      </div>

      <SummaryHero opp={opp} />

      <main className="mx-auto max-w-3xl space-y-14 px-6 py-14">
        {apps.length > 0 && (
          <SummarySection title="CommCare apps">
            {apps.map((app) => {
              const links: { label: string; href: string }[] = [];
              if (app.nova_url) links.push({ label: "Open in Nova", href: app.nova_url });
              if (app.hq_url) links.push({ label: "Open in CommCare HQ", href: app.hq_url });
              return (
                <SummaryRow
                  key={app.kind}
                  label={app.kind}
                  name={app.name}
                  links={links}
                />
              );
            })}
          </SummarySection>
        )}

        {connect && (connect.opportunity || connect.program) && (
          <SummarySection title="Connect opportunity">
            {connect.opportunity && (
              <SummaryRow
                label="Opp"
                name={
                  <>
                    {connect.opportunity.name}
                    {(() => {
                      const range = formatConnectDateRange(
                        connect.opportunity.start_date,
                        connect.opportunity.end_date,
                      );
                      return range ? (
                        <span className="text-muted-foreground">{" · "}{range}</span>
                      ) : null;
                    })()}
                  </>
                }
                links={
                  connect.opportunity.url
                    ? [{ label: "Open on Connect", href: connect.opportunity.url }]
                    : []
                }
              />
            )}
            {connect.program && (
              <SummaryRow
                label="Program"
                name={connect.program.name}
                links={
                  connect.program.url
                    ? [{ label: "Open on Connect", href: connect.program.url }]
                    : []
                }
              />
            )}
          </SummarySection>
        )}

        {training && (training.deck || training.docs.length > 0) && (
          <SummarySection title="Training pack">
            {training.deck && (
              <SummaryRow
                label="Deck"
                name={training.deck.title}
                links={[{ label: "Open in Slides", href: training.deck.url }]}
              />
            )}
            {training.docs.map((doc) => (
              <SummaryRow
                key={doc.url}
                label="Doc"
                name={doc.title}
                links={[{ label: "Open", href: doc.url }]}
              />
            ))}
          </SummarySection>
        )}

        {assistant && (
          <SummarySection title="Support assistant">
            <SummaryRow
              label="Bot"
              name="Trained on the design doc, training pack, and app guides for this opportunity. Use the chat in the corner ↘ to ask it a question."
              links={[]}
            />
          </SummarySection>
        )}

        {open_questions && (
          <SummarySection title="Open questions">
            <SummaryRow
              label="Doc"
              name="Outstanding design questions for this run"
              links={[{ label: "Open in Drive", href: open_questions.url }]}
            />
          </SummarySection>
        )}

        <footer className="mt-10 flex flex-wrap items-center justify-between gap-3 border-t border-border pt-8 text-sm text-muted-foreground">
          <span>
            Generated by ACE · run{" "}
            <span className="font-mono">{opp.run_id}</span>
          </span>
          {workbench_url && (
            <a
              href={workbench_url}
              className="group inline-flex items-center gap-1 underline-offset-4 transition-all hover:underline"
            >
              See the full build process
              <ArrowRight
                size={14}
                className="transition-transform group-hover:translate-x-0.5"
              />
            </a>
          )}
        </footer>
      </main>

      {/* Standard OCS widget popup, mounted only when the bot is configured. */}
      {assistant && (
        <OcsWidgetMount
          chatbotId={assistant.public_id}
          embedKey={assistant.embed_key}
        />
      )}
    </div>
  );
}
