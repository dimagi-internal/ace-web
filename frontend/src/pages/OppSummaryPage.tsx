import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { ArrowRight, FileText, Scale } from "lucide-react";

import { ApiError } from "@/api/client";
import {
  getPublicOppSummary,
  postDecisionReaction,
  type DecisionReaction,
  type LinkAccess,
  type OppSummaryPayload,
} from "@/api/oppSummary";
import type { ReactionSubmit } from "@/components/opps/summary/DecisionReactions";
import { DecisionsReview } from "@/components/opps/summary/DecisionsReview";
import { OcsWidgetMount } from "@/components/opps/summary/OcsWidgetMount";
import { OpenQuestionsList } from "@/components/opps/summary/OpenQuestionsList";
import { SummaryHero } from "@/components/opps/summary/SummaryHero";
import { AdminOnlyTag, SummaryRow } from "@/components/opps/summary/SummaryRow";
import { SummarySection } from "@/components/opps/summary/SummarySection";
import { ViewSwitcher, type ViewTab } from "@/components/views/ViewSwitcher";
import { useUrlTab } from "@/hooks/useViewMode";

/**
 * Tabs, not a longer page. The decisions log is 42 rows a partner is
 * being asked to REACT to, and burying it two screens under the artifact
 * links makes it the last thing anyone reaches. It is also the same
 * material the Workbench's phase view renders, so it reuses the
 * Workbench's tab strip (`ViewSwitcher`) and URL-state hook rather than
 * a lookalike — the URL stays in the same family (`?tab=decisions`), so
 * a partner still gets ONE link and can be pointed straight at the part
 * that needs them.
 */
type SummaryTab = "overview" | "decisions";

const SUMMARY_TABS: readonly SummaryTab[] = ["overview", "decisions"] as const;

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
  const { tab, setTab } = useUrlTab<SummaryTab>({
    param: "tab",
    valid: SUMMARY_TABS,
    defaultTab: "overview",
  });
  // Seeded from the payload, then appended to optimistically on submit —
  // the read path is cached for 60s server-side, and a comment that
  // doesn't appear immediately reads as a comment that was lost.
  const [reactions, setReactions] = useState<Record<string, DecisionReaction[]>>({});

  async function handleReact(decisionId: string, body: ReactionSubmit) {
    const saved = await postDecisionReaction(workspace, slug, runId, decisionId, body);
    setReactions((prev) => ({
      ...prev,
      [decisionId]: [...(prev[decisionId] ?? []), saved],
    }));
  }

  useEffect(() => {
    if (!workspace || !slug || !runId) return;
    let cancelled = false;
    getPublicOppSummary(workspace, slug, runId)
      .then((payload) => {
        if (cancelled) return;
        setState({ kind: "loaded", payload });
        setReactions(payload.reactions?.by_decision ?? {});
      })
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
    opp, design, apps, connect, training, assistant, open_questions, feedback, workbench,
    walkthroughs, dashboards, selected_llo, solicitation, launch, cycle_grade, opp_eval, learnings,
    stage, decisions, viewer,
  } = payload;

  // Every link is served to everyone and carries its own `access`. Whether
  // the page DRAWS the "admin only" tag is decided once, here: a member
  // already knows which links are internal, so the tag would be noise.
  const showAccessTags = !viewer?.is_member;
  const link = (label: string, href: string, access?: LinkAccess) => ({
    label,
    href,
    access: showAccessTags ? access : undefined,
  });

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

  // The tab strip only exists when there is something to review. A run
  // with no decisions log and no open questions renders exactly as it did
  // before: one page, no chrome for a tab that would be empty.
  const openQuestionCount = open_questions?.items.length ?? 0;
  const hasReviewSurface = Boolean(decisions) || openQuestionCount > 0;
  const showOverview = !hasReviewSurface || tab === "overview";
  const needsEye = decisions
    ? decisions.counts.conflicting + decisions.counts.overridden
    : 0;
  const tabs: ViewTab<SummaryTab>[] = [
    { kind: "overview", label: "Overview", icon: FileText },
    {
      kind: "decisions",
      label: "Decisions",
      icon: Scale,
      count: decisions?.total ?? openQuestionCount,
    },
  ];

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

      {hasReviewSurface && (
        <div className="border-b border-border">
          <ViewSwitcher<SummaryTab>
            current={tab}
            tabs={tabs}
            onChange={setTab}
            className="mx-auto max-w-3xl px-6"
          />
        </div>
      )}

      <main className="mx-auto max-w-3xl space-y-14 px-6 py-14">
        {showOverview && (
          <>
          {/* Design — first, because it is what everything below was built
              from and what a reviewer comments on. */}
          <SummarySection title="Design">
            {design && design.docs.length > 0 ? (
              design.docs.map((doc) => (
                <SummaryRow
                  key={doc.url}
                  label="Doc"
                  name={doc.title}
                  links={[link("Open", doc.url, doc.access)]}
                />
              ))
            ) : (
              slot("design", "Doc")
            )}
          </SummarySection>

          {/* The overview's job is the artifact list; the review surface
              lives one tab over. This is the handoff — without it a
              partner can read the whole page and never learn there are 42
              decisions waiting on them. */}
          {hasReviewSurface && (
            <SummarySection title="Review">
              <div className="flex flex-wrap items-baseline justify-between gap-3 py-1">
                <p className="max-w-md text-[0.975rem] leading-[1.7] text-muted-foreground">
                  {decisions
                    ? `${decisions.total} calls ACE made building this run, ${openQuestionCount} it couldn't settle. `
                    : `${openQuestionCount} questions this run couldn't settle. `}
                  <span className="text-foreground">
                    {needsEye > 0
                      ? `${needsEye} need your eye.`
                      : "React to any of them."}
                  </span>
                </p>
                <button
                  type="button"
                  onClick={() => setTab("decisions")}
                  className="group inline-flex items-center gap-1.5 text-sm font-medium text-foreground underline-offset-4 hover:underline"
                >
                  Review the decisions
                  <ArrowRight
                    size={14}
                    className="transition-transform group-hover:translate-x-0.5"
                  />
                </button>
              </div>
            </SummarySection>
          )}

          {/* CommCare apps — always show Learn + Deliver slots */}
          <SummarySection title="CommCare apps">
            {(["Learn", "Deliver"] as const).map((kind) => {
              const app = apps.find((a) => a.kind === kind);
              if (!app) return slot("apps", kind, kind);
              const links: ReturnType<typeof link>[] = [];
              if (app.hq_url) {
                links.push(link("Open in CommCare HQ", app.hq_url, app.access));
              }
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
                    ? [
                        link(
                          "Open on Connect",
                          connect.opportunity.url,
                          connect.opportunity.access,
                        ),
                      ]
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
                    ? [link("View in OCS", assistant.ocs_url, assistant.access)]
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
                    links={[link("Open in Slides", training.deck.url, training.deck.access)]}
                  />
                )}
                {training.docs.map((doc) => (
                  <SummaryRow
                    key={doc.url}
                    label="Doc"
                    name={doc.title}
                    links={[link("Open", doc.url, doc.access)]}
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
                    links={[link("Open deck", w.url, w.access)]}
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
                  links={[link("Open dashboard", d.url, d.access)]}
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
                links={[link("Open solicitation", solicitation.url, solicitation.access)]}
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
                  link("Open in Drive", learnings.summary_url, learnings.access),
                  ...(learnings.new_pdd_url
                    ? [link("Next PDD", learnings.new_pdd_url, learnings.access)]
                    : []),
                ]}
              />
            ) : (
              slot("learnings", "Learnings")
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
                  links={[link("Open", led.url, led.access)]}
                />
              ))
            ) : (
              <Placeholder label="Ledger" text="No review logged yet" />
            )}
          </SummarySection>

          </>
        )}

        {tab === "decisions" && hasReviewSurface && (
          <>
          {/* ── The review surface ──────────────────────────────────────
              "What we decided and why, and what we could not decide."

              Both blocks live on this one tab because they are one
              argument, not two link lists — and 5 open questions do not
              earn a tab of their own. The PDD on the Overview is 24
              pages of prose and people skim prose; these are the
              individual calls, each with its alternatives, its
              reasoning, and a reply box, so disagreeing costs one
              sentence instead of a document review. */}
          {decisions && (
            <SummarySection title="Decisions">
              <DecisionsReview
                decisions={decisions}
                reactions={reactions}
                onReact={handleReact}
              />
            </SummarySection>
          )}

          <SummarySection title="Open questions">
            {open_questions && open_questions.items.length > 0 ? (
              <>
                <p className="mb-4 text-[0.975rem] leading-[1.7] text-muted-foreground">
                  What this run could <span className="text-foreground">not</span> settle —
                  each one already has an owner and a place it gets answered.
                </p>
                <OpenQuestionsList items={open_questions.items} />
                {open_questions.url && (
                  <p className="mt-4 flex items-center justify-end gap-2 text-sm">
                    <a
                      href={open_questions.url}
                      target="_blank"
                      rel="noreferrer"
                      className="font-medium text-foreground underline-offset-4 hover:underline"
                    >
                      Source document
                    </a>
                    {showAccessTags && open_questions.access === "admin" && <AdminOnlyTag />}
                  </p>
                )}
              </>
            ) : open_questions?.url ? (
              <SummaryRow
                label="Doc"
                name="Outstanding design questions for this run"
                links={[link("Open in Drive", open_questions.url, open_questions.access)]}
              />
            ) : (
              <NotCreated label="Doc" />
            )}
          </SummarySection>
          </>
        )}

        <footer className="mt-10 flex flex-wrap items-center justify-between gap-3 border-t border-border pt-8 text-sm text-muted-foreground">
          <span>
            Generated by ACE · run{" "}
            <span className="font-mono">{opp.run_id}</span>
          </span>
          {workbench && (
            <span className="inline-flex items-center gap-2">
              <a
                href={workbench.url}
                className="group inline-flex items-center gap-1 underline-offset-4 transition-all hover:underline"
              >
                See the full build process
                <ArrowRight
                  size={14}
                  className="transition-transform group-hover:translate-x-0.5"
                />
              </a>
              {showAccessTags && workbench.access === "admin" && <AdminOnlyTag />}
            </span>
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
