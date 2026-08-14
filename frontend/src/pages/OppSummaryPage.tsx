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

function Placeholder({ label, text }: { label: string; text: string }) {
  return (
    <div className="flex items-baseline gap-6 -mx-3 px-3 py-3.5 [&+&]:border-t [&+&]:border-border">
      <span className="w-20 shrink-0 text-[11px] uppercase tracking-[0.16em] text-muted-foreground/50">
        {label}
      </span>
      <span className="text-[0.975rem] italic text-muted-foreground/40">{text}</span>
    </div>
  );
}

function NotCreated({ label }: { label: string }) {
  return <Placeholder label={label} text="Not created" />;
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
  const {
    opp, design, apps, connect, training, assistant, open_questions, feedback, workbench_url,
    walkthroughs, dashboards, selected_llo, solicitation, launch, cycle_grade, opp_eval, learnings,
    stage,
  } = payload;

  // Sections whose phase hasn't run yet say so, instead of "Not created".
  // Six of ten sections are legitimately empty on a run paused at the
  // Phase 8→9 boundary; undifferentiated, that reads as an abandoned
  // build rather than a healthy run waiting on a partner.
  const pending = new Set(stage?.pending_sections ?? []);
  const notStartedText = stage?.label
    ? `Not started — this run is at the ${stage.label} stage`
    : "Not started yet";
  const slot = (section: string, label: string, key?: string) =>
    pending.has(section) ? (
      <Placeholder key={key} label={label} text={notStartedText} />
    ) : (
      <NotCreated key={key} label={label} />
    );

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

      <SummaryHero opp={opp} cycleGrade={cycle_grade} />

      <main className="mx-auto max-w-3xl space-y-14 px-6 py-14">
        {/* Design — first, because it is what everything below was built
            from and what a reviewer comments on. */}
        <SummarySection title="Design">
          {design && design.docs.length > 0 ? (
            design.docs.map((doc) => (
              <SummaryRow
                key={doc.url}
                label="Doc"
                name={doc.title}
                links={[{ label: "Open", href: doc.url }]}
              />
            ))
          ) : (
            slot("design", "Doc")
          )}
        </SummarySection>

        {/* CommCare apps — always show Learn + Deliver slots */}
        <SummarySection title="CommCare apps">
          {(["Learn", "Deliver"] as const).map((kind) => {
            const app = apps.find((a) => a.kind === kind);
            if (!app) return slot("apps", kind, kind);
            const links: { label: string; href: string }[] = [];
            if (app.hq_url) links.push({ label: "Open in CommCare HQ", href: app.hq_url });
            return <SummaryRow key={kind} label={kind} name={app.name} links={links} />;
          })}
        </SummarySection>

        {/* Connect opportunity — opp slot only (program URL 404s publicly) */}
        <SummarySection title="Connect opportunity">
          {connect?.opportunity ? (
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
          ) : (
            slot("connect", "Opp")
          )}
        </SummarySection>

        {/* Support assistant */}
        <SummarySection title="Support assistant">
          {assistant ? (
            <SummaryRow
              label="Bot"
              name="Trained on the design doc, training pack, and app guides for this opportunity."
              links={
                assistant.ocs_url
                  ? [{ label: "View in OCS", href: assistant.ocs_url }]
                  : []
              }
            />
          ) : (
            slot("assistant", "Bot")
          )}
        </SummarySection>

        {/* Training pack */}
        <SummarySection title="Training pack">
          {training && (training.deck || training.docs.length > 0) ? (
            <>
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
            </>
          ) : (
            slot("training", "Deck")
          )}
        </SummarySection>

        {/* Persona walkthroughs — absent / withheld / available.
            A withheld walkthrough was produced but failed its concept
            eval, so it is named without a link. Rendering it as "Not
            created" would tell a reviewer something doesn't exist when
            it does and we chose not to show it. */}
        <SummarySection title="Persona walkthroughs">
          {walkthroughs.length > 0 ? (
            walkthroughs.map((w, i) =>
              w.availability === "withheld" || !w.url ? (
                <SummaryRow
                  key={`withheld-${i}`}
                  label="Demo"
                  name={
                    <>
                      {w.persona}
                      <span className="italic text-muted-foreground">
                        {" · "}
                        {w.withheld_reason ?? "Not shown — did not pass quality review"}
                      </span>
                    </>
                  }
                  links={[]}
                />
              ) : (
                <SummaryRow
                  key={w.url}
                  label="Demo"
                  name={
                    <>
                      {w.persona}
                      {w.eval_score != null && (
                        <span className="text-muted-foreground">
                          {" · "}eval {w.eval_score}/10
                        </span>
                      )}
                    </>
                  }
                  links={[{ label: "Open deck", href: w.url }]}
                />
              ),
            )
          ) : (
            slot("walkthroughs", "Demo")
          )}
        </SummarySection>

        {/* Dashboards */}
        <SummarySection title="Dashboards">
          {dashboards.length > 0 ? (
            dashboards.map((d) => (
              <SummaryRow
                key={d.url}
                label="Dashboard"
                name={d.title}
                links={[{ label: "Open dashboard", href: d.url }]}
              />
            ))
          ) : (
            slot("dashboards", "Dashboard")
          )}
        </SummarySection>

        {/* Solicitation */}
        <SummarySection title="Solicitation">
          {solicitation ? (
            <SummaryRow
              label="RFP"
              name={
                <>
                  Published call for LLO responses
                  {solicitation.deadline && (
                    <span className="text-muted-foreground">
                      {" · "}deadline {solicitation.deadline}
                    </span>
                  )}
                  {solicitation.status && (
                    <span className="text-muted-foreground">
                      {" · "}{solicitation.status}
                    </span>
                  )}
                </>
              }
              links={[{ label: "Open solicitation", href: solicitation.url }]}
            />
          ) : (
            slot("solicitation", "RFP")
          )}
        </SummarySection>

        {/* Execution */}
        <SummarySection title="Execution">
          {selected_llo ? (
            <SummaryRow
              label="LLO"
              name={
                <>
                  {selected_llo.org_display_name}
                  {selected_llo.awarded_at && (
                    <span className="text-muted-foreground">
                      {" · "}awarded {_formatShortDate(selected_llo.awarded_at)}
                    </span>
                  )}
                </>
              }
              links={
                selected_llo.contact_email
                  ? [{ label: "Contact", href: `mailto:${selected_llo.contact_email}` }]
                  : []
              }
            />
          ) : (
            slot("selected_llo", "LLO")
          )}
          {launch ? (
            <SummaryRow
              label="Live"
              name={
                <>
                  Went live {_formatShortDate(launch.went_live_at)}
                  {launch.llo_org_display_name && !selected_llo && (
                    <span className="text-muted-foreground">
                      {" · "}{launch.llo_org_display_name}
                    </span>
                  )}
                </>
              }
              links={[]}
            />
          ) : (
            slot("launch", "Live")
          )}
        </SummarySection>

        {/* Outcomes */}
        <SummarySection title="Outcomes">
          {opp_eval ? (
            <SummaryRow
              label="Score"
              name={
                <>
                  {opp_eval.overall_score}
                  {opp_eval.verdict && (
                    <span className="text-muted-foreground">
                      {" · "}{opp_eval.verdict}
                    </span>
                  )}
                  {opp_eval.mode && (
                    <span className="text-muted-foreground">
                      {" · "}{opp_eval.mode} eval
                    </span>
                  )}
                </>
              }
              links={[]}
            />
          ) : (
            slot("opp_eval", "Score")
          )}
          {learnings ? (
            <SummaryRow
              label="Learnings"
              name={
                learnings.iteration_warranted
                  ? "Synthesis with follow-up PDD for the next cycle"
                  : "Synthesis of what this run learned"
              }
              links={[
                { label: "Open in Drive", href: learnings.summary_url },
                ...(learnings.new_pdd_url
                  ? [{ label: "Next PDD", href: learnings.new_pdd_url }]
                  : []),
              ]}
            />
          ) : (
            slot("learnings", "Learnings")
          )}
        </SummarySection>

        {/* Open questions */}
        <SummarySection title="Open questions">
          {open_questions ? (
            <SummaryRow
              label="Doc"
              name="Outstanding design questions for this run"
              links={[{ label: "Open in Drive", href: open_questions.url }]}
            />
          ) : (
            <NotCreated label="Doc" />
          )}
        </SummarySection>

        {/* Reviewer feedback — where a reviewer's own comments landed.
            Rendered per review event so a returning reviewer reads a diff
            instead of re-reviewing from scratch. */}
        <SummarySection title="Reviewer feedback">
          {feedback && feedback.length > 0 ? (
            feedback.map((led) => (
              <SummaryRow
                key={led.url}
                label="Ledger"
                name={led.title}
                links={[{ label: "Open", href: led.url }]}
              />
            ))
          ) : (
            <Placeholder label="Ledger" text="No review logged yet" />
          )}
        </SummarySection>

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
