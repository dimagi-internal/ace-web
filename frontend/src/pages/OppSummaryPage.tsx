import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { ArrowRight, FileText, Scale } from "lucide-react";

import { ApiError } from "@/api/client";
import {
  getPublicOppSummary,
  isPlainViewer,
  postDecisionEdit,
  postDecisionReaction,
  type DecisionReaction,
  type LinkAccess,
  type OppSummaryPayload,
  type PublicDecisionEdit,
} from "@/api/oppSummary";
import type { ReactionSubmit } from "@/components/opps/summary/DecisionReactions";
import {
  DecisionsReview,
  askCounts,
  decisionsTabBadge,
  type DecisionEditSubmit,
} from "@/components/opps/summary/DecisionsReview";
import { ClaimsSection } from "@/components/opps/summary/ClaimsSection";
import { DeepQaSection } from "@/components/opps/summary/DeepQaSection";
import { OcsWidgetMount } from "@/components/opps/summary/OcsWidgetMount";
import { cn } from "@/lib/utils";
import { SummaryHero } from "@/components/opps/summary/SummaryHero";
import { SummaryOrientation } from "@/components/opps/summary/SummaryOrientation";
import { useDecisionLineage } from "@/components/opps/decisions/lineage/Lineage";
import {
  AdminOnlyTag,
  SummaryRow,
} from "@/components/opps/summary/SummaryRow";
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

/**
 * One plain line qualifying a section whose phase finished without a
 * clean verdict — `stage.caveats[]`, worded server-side. On
 * spark-facilitator/20261001-2208 the training pack came from a
 * `proceed-with-warn` phase and the dashboards from
 * `passed-with-deferred-evals`, and both rendered exactly like a clean
 * run's. Same visual move as `BuildCaveats` and `SyntheticNotice`.
 */
function SectionCaveat({ text }: { text: string | undefined }) {
  if (!text) return null;
  return (
    <p className="mb-3 border-l-2 border-border pl-3 text-[0.85rem] leading-[1.6] text-muted-foreground">
      {text}
    </p>
  );
}

/**
 * The canopy DDD concept rubric is anchored **1–5**, not 1–10 —
 * `skills/ddd-concept-eval/rubric.yaml` in the canopy plugin, whose
 * per-dimension `anchors` run "5" down to "1" with 3 as the documented
 * default.
 *
 * The page rendered `{score}/10` (ace-web#740). On
 * spark-facilitator/20260820-0817 the loop recorded concept 2.0, user
 * 2.0 and arc 2.0 — 2 out of 5, a failing-but-not-catastrophic score —
 * and the page showed "eval 2/10", which reads as roughly half as good
 * as it actually is. A wrong denominator is not a rounding error; it
 * changes what the number says.
 */
const DDD_EVAL_SCORE_MAX = 5;

function formatEvalScore(score: number): string {
  return `${score}/${DDD_EVAL_SCORE_MAX}`;
}

/** `["a", "b", "c"]` → `"a, b and c"`. */
function joinList(items: string[]): string {
  if (items.length <= 1) return items[0] ?? "";
  return `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}`;
}

/**
 * How each DDD terminal status reads to someone who has never heard of
 * the loop. Four values, four different sentences — never collapsed to
 * pass/fail, because "converged, good" and "converged, still failing"
 * are the two the collapse would fuse, and they are the two a reader
 * most needs to tell apart.
 */
const DDD_TERMINAL_STATUS_LABELS: Record<string, string> = {
  converged_clean: "the review loop finished clean",
  converged_with_open_questions:
    "the review loop finished, with open questions",
  stopped_not_converged: "the review loop stopped before it converged",
  diverging: "the review loop was getting worse, not better",
};

/**
 * The qualifiers that make a walkthrough's score readable — surfaced
 * beside it, never dropped (ace-web#740).
 *
 * On spark-facilitator/20260820-0817 the run state carried
 * `stopped_not_converged`, zero end-to-end iterations, and
 * `ddd_render_measures_pre_fix_artifact: true`; the page carried a score
 * and a video link and none of the three. The pre-fix flag is the one
 * that makes the LINK misleading rather than just the number: four
 * accuracy fixes landed during that iteration and appear in no captured
 * frame, so the published video films a product that no longer exists.
 * A published video presented bare against a pre-fix artifact is the
 * specific thing this component exists to prevent.
 *
 * An unrecognised status is rendered verbatim rather than swallowed —
 * same rule as the walkthrough URL keys (ace#1432): a value we don't
 * know must not become silence.
 */
function WalkthroughCaveats({
  ddd,
  isMember,
}: {
  ddd: OppSummaryPayload["walkthroughs"][number]["ddd"];
  /**
   * The review-loop status is ACE's internal process, and a partner has
   * no use for "the review loop stopped before it converged" — members
   * only. The pre-fix caveat is about the RECORDING, so everyone gets it;
   * an outside reader just gets it without the score it qualifies.
   */
  isMember: boolean;
}) {
  if (!ddd) return null;
  const status = isMember ? ddd.terminal_status : null;
  const statusText = status
    ? (DDD_TERMINAL_STATUS_LABELS[status] ?? `review loop status: ${status}`)
    : null;
  if (!statusText && !ddd.measures_pre_fix_artifact) return null;
  return (
    <span className="mt-1 block text-[0.85rem] leading-[1.6] text-muted-foreground">
      {statusText && (
        <span>
          {statusText}
          {ddd.iterations_completed != null &&
            ` after ${ddd.iterations_completed} full ${
              ddd.iterations_completed === 1 ? "pass" : "passes"
            }`}
          .{" "}
        </span>
      )}
      {ddd.measures_pre_fix_artifact && (
        <span className="text-foreground">
          {isMember
            ? "This score and recording measure a version that has since been fixed — they do not show the current build."
            : "This recording shows an earlier version that has since been fixed — it does not show the current build."}
        </span>
      )}
    </span>
  );
}

/**
 * How each phase status reads to someone who has never seen the Phase
 * Write-Back Contract. Same rule as `DDD_TERMINAL_STATUS_LABELS`: an
 * unrecognised value is rendered verbatim rather than swallowed, because
 * a status we do not know must not become silence.
 */
const BUILD_STATUS_LABELS: Record<string, string> = {
  partial: "shipped, but the build checks did not all pass",
  blocked: "the build stopped on a check it could not clear",
  failed: "the build did not pass its checks",
  halted: "the build was halted before it finished",
  error: "the build ended in an error",
};

/**
 * The producing phase's own verdict on the apps, rendered where the apps
 * are.
 *
 * `spark-facilitator/20260828-0703` wrote `status: partial` and a failed
 * `entity_state_fidelity` gate — the payment-key gate — and this section
 * showed both apps with no status at all. A reader could not tell it
 * from a clean run (ace-web#744).
 *
 * The wording is deliberately the same move `WalkthroughCaveats` makes
 * for the Phase 7 demo: name what did not pass, in plain words, beside
 * the thing it is about. The run's own `status_note` is preferred over
 * anything phrased here — it is the only text written by whoever
 * actually knows why.
 */
function BuildCaveats({ build }: { build: OppSummaryPayload["build"] }) {
  if (!build) return null;
  const status = build.status;
  const statusText = status
    ? (BUILD_STATUS_LABELS[status] ?? `build status: ${status}`)
    : null;
  const checks = build.failing_checks ?? [];
  const carried = build.carried_blockers ?? [];
  if (!statusText && checks.length === 0 && carried.length === 0) return null;
  return (
    <div className="mb-3 border-l-2 border-border pl-3 text-[0.85rem] leading-[1.6] text-muted-foreground">
      {statusText && <p className="text-foreground">These apps {statusText}.</p>}
      {build.note && <p className="mt-1">{build.note}</p>}
      {checks.map((c) => (
        <p key={c.name} className="mt-1">
          <span className="font-mono text-[0.8rem]">{c.name}</span>
          {` — ${c.verdict}`}
          {c.detail ? `. ${c.detail}` : "."}
        </p>
      ))}
      {carried.map((b) => (
        <p key={b.id} className="mt-1">
          {b.gate ? `${b.gate}: ` : ""}
          {b.disposition ?? "carried forward"}
          {b.residual_accepted ? `. ${b.residual_accepted}` : ""}
        </p>
      ))}
    </div>
  );
}

/**
 * That the dashboards and the demo are built on GENERATED data.
 *
 * Phase 7 invents its dataset — facilitators, visits, anomalies, a
 * coaching task — and nothing on this page said so. Without this line a
 * reader opens a dashboard of 223 records attributed to 12 named
 * facilitators and reads every one of them as an observation.
 *
 * The numbers come from the run's own `products.synthetic.source` block,
 * so this is a label on real recorded provenance, not an assertion. A
 * run that recorded no counts gets the sentence without them.
 */
function SyntheticNotice({
  synthetic,
}: {
  synthetic: OppSummaryPayload["synthetic"];
}) {
  if (!synthetic?.is_synthetic) return null;
  const parts: string[] = [];
  if (synthetic.visits != null) {
    parts.push(
      `${synthetic.visits} generated ${
        synthetic.visits === 1 ? "record" : "records"
      }`,
    );
  }
  if (synthetic.cohort_size != null) {
    parts.push(
      `${synthetic.cohort_size} synthetic ${
        synthetic.cohort_population ?? "participants"
      }`,
    );
  }
  return (
    <p className="mb-3 border-l-2 border-border pl-3 text-[0.85rem] leading-[1.6] text-muted-foreground">
      <span className="text-foreground">
        Demonstration data — not real programme activity.
      </span>{" "}
      {parts.length > 0 && `${joinList(parts)}. `}
      {synthetic.completed_works === 0 &&
        "No payments were made against it. "}
      Everything below shows how the programme would be reviewed once it
      runs, not what it has done.
    </p>
  );
}

/**
 * What the support assistant knows — stated ONLY when the run recorded
 * it (ace-web#740).
 *
 * This line used to be the constant "Trained on the design doc, training
 * pack, and app guides for this opportunity." It was derived from
 * nothing at all, and on spark-facilitator/20260820-0817 it was false:
 * the opp collection held 16 files (`00-program-contacts.md` …
 * `15-connect-setup-summary.md`) and none of the five training-pack
 * documents this same page links were among them. Two-thirds true is
 * what made it survive — the design doc and the app summaries WERE
 * indexed — and a reader has no way to tell which third is the lie.
 *
 * ACE shipped `ocs-knowledge-refresh` (ace#1715) so future runs do index
 * the training docs. The fallback must therefore say nothing about
 * training rather than something weaker-but-still-invented: a run where
 * it did not happen must not read as one where it did.
 */
/**
 * The assistant blurb has to say WHERE to ask, not just that asking is possible.
 *
 * The section used to read "Ask questions about this opportunity." above a single
 * "View in OCS" link — which is the admin console and bounces an outsider to
 * /accounts/login/. The chat is actually right there: `OcsWidgetMount` puts the
 * bot in the bottom-right corner of this page whenever the run served embed
 * credentials. An invitation whose only visible affordance is a login wall reads
 * as broken even when the answer is one click away (ace#1839).
 *
 * `canChatHere` is that condition, and the copy points at the widget rather than
 * anywhere else: the reader should not be sent off the review surface to do this.
 */
function assistantBlurb(
  knowledgeSources: string[] | undefined,
  canChatHere: boolean,
): string {
  const sources = (knowledgeSources ?? []).filter((s) => s.trim());
  const given = sources.length ? ` It was given ${joinList(sources)}.` : "";
  const where = canChatHere
    ? " Use the chat button in the bottom-right of this page — no account needed."
    : "";
  return `Ask questions about this opportunity.${given}${where}`;
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
  // Same reason: the write returns the merged row (value, attribution,
  // full history) so the row re-renders as changed immediately instead of
  // waiting out the 60s payload cache and looking like nothing happened.
  const [edits, setEdits] = useState<Record<string, PublicDecisionEdit>>({});
  // Where each decision came from across runs — fetched alongside, never
  // blocking the page (it renders nothing until it lands, or if it fails).
  const [lineageScope, setLineageScope] = useState<"lineage" | "opp">("lineage");
  const lineage = useDecisionLineage(workspace, slug, runId, lineageScope);

  async function handleReact(decisionId: string, body: ReactionSubmit) {
    const saved = await postDecisionReaction(workspace, slug, runId, decisionId, body);
    setReactions((prev) => ({
      ...prev,
      [decisionId]: [...(prev[decisionId] ?? []), saved],
    }));
  }

  async function handleEdit(decisionId: string, body: DecisionEditSubmit) {
    const saved = await postDecisionEdit(workspace, slug, runId, decisionId, body);
    setEdits((prev) => ({ ...prev, [decisionId]: saved }));
  }

  useEffect(() => {
    if (!workspace || !slug || !runId) return;
    let cancelled = false;
    getPublicOppSummary(workspace, slug, runId)
      .then((payload) => {
        if (cancelled) return;
        setState({ kind: "loaded", payload });
        setReactions(payload.reactions?.by_decision ?? {});
        setEdits(payload.decision_edits ?? {});
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
    opp, claims, design, apps, build, deep_qa, connect, training, assistant, feedback, workbench,
    walkthroughs, dashboards, synthetic, selected_llo, solicitation, launch, cycle_grade, opp_eval, learnings,
    stage, decisions, viewer,
  } = payload;

  // Every link is served to everyone and carries its own `access`. Whether
  // the page DRAWS the "admin only" tag is decided once, here: a member
  // already knows which links are internal, so the tag would be noise.
  // Two separate facts about the reader: `canWrite` (a member of any role)
  // is access; `plain` (partner view — viewer role or not a member) is
  // presentation. Owners and editors get the team view.
  const plain = isPlainViewer(viewer);
  const showAccessTags = plain;
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
    ? `Not started — this program is at the ${stage.label} stage`
    : "Not started yet";
  // A phase the run deliberately SKIPPED is neither: nothing is coming,
  // and nothing went missing. Its sections read the run's reason instead
  // ("Not part of this run — it stopped after the solicitation stage, by
  // design"), never "Not created".
  const skipped = new Map<string, string>();
  for (const entry of stage?.skipped ?? []) {
    for (const section of entry.sections) skipped.set(section, entry.reason);
  }
  const slot = (section: string, label: string, key?: string) => {
    const skipReason = skipped.get(section);
    if (skipReason) return <Placeholder key={key} label={label} text={skipReason} />;
    return pending.has(section) ? (
      <Placeholder key={key} label={label} text={notStartedText} />
    ) : (
      <NotCreated key={key} label={label} />
    );
  };
  // Per-section verdict caveats, looked up by payload key like `slot`.
  const caveats = new Map<string, string>();
  for (const entry of stage?.caveats ?? []) {
    for (const section of entry.sections) caveats.set(section, entry.text);
  }

  // The tab strip only exists when there is something to review. A run
  // with no decisions log renders exactly as it did before: one page, no
  // chrome for a tab that would be empty. The asks ARE decision rows — a
  // filter of the run's own decisions log, grouped on the Decisions tab —
  // so there is no second "open questions" list anywhere on the page
  // (operator decision 2026-10-07: no legacy ledger is read).
  const hasReviewSurface = Boolean(decisions);
  const showOverview = !hasReviewSurface || tab === "overview";
  // What the reviewer is asked to DO: the recommended confirmations still
  // waiting. Counted from the rows + edits through the same predicate the
  // Decisions tab uses, so the two can never disagree (ace-web#771). This
  // replaced "N need your eye", which counted ACE's own uncertainty
  // (conflicting sources) rather than anything the reviewer must act on.
  const asks = decisions
    ? askCounts(decisions.rows, edits)
    : {
        confirm: { total: 0, outstanding: 0 },
        answer: { total: 0, outstanding: 0 },
        total: 0,
        outstanding: 0,
      };
  const confirm = asks.confirm;
  // The decisions tab is a dense two-column list and uses a wide screen;
  // the Overview stays a reading column. One width for the whole page so
  // the hero, tabs and body share a left edge.
  const width = tab === "decisions" && hasReviewSurface ? "max-w-6xl" : "max-w-3xl";
  const tabs: ViewTab<SummaryTab>[] = [
    { kind: "overview", label: "Overview", icon: FileText },
    {
      kind: "decisions",
      label: "Decisions",
      icon: Scale,
      // What is waiting on the reader, not the size of the log: "120"
      // read as 120 questions when 25 were asks (owner, 2026-10-07).
      count: decisionsTabBadge(asks),
    },
  ];

  return (
    <div className="min-h-screen bg-background text-foreground">
      {/* Top utility bar — display name on the left (human-readable),
          run id on the right (technical reference) for members only. An
          outside reader gets nothing from "run 20261001-2208" as the first
          thing on the page; the footer still carries it. */}
      <div className="border-b border-border">
        <div
          className={cn(
            "mx-auto flex items-center justify-between gap-4 px-4 py-3 text-xs sm:px-6",
            width,
          )}
        >
          <div className="truncate text-muted-foreground">{opp.display_name}</div>
          {!plain && (
            <div className="font-mono tracking-tight text-muted-foreground/70">
              run {opp.run_id}
            </div>
          )}
        </div>
      </div>

      <SummaryHero
        opp={opp}
        cycleGrade={cycle_grade}
        pausedText={stage?.paused}
        widthClass={width}
      />

      {hasReviewSurface && (
        <div className="border-b border-border">
          <ViewSwitcher<SummaryTab>
            current={tab}
            tabs={tabs}
            onChange={setTab}
            className={cn("mx-auto px-4 sm:px-6", width)}
          />
        </div>
      )}

      {/* 16px gutters on a phone (px-4), more from sm up. */}
      <main className={cn("mx-auto space-y-14 px-4 py-14 sm:px-6", width)}>
        {showOverview && (
          <>
          {/* Orientation — what this page is and what we need from the
              reader. Outsiders only; a member already knows. */}
          <SummaryOrientation
            isMember={!plain}
            confirmOutstanding={confirm.outstanding}
            confirmTotal={confirm.total}
            answerOutstanding={asks.answer.outstanding}
            answerTotal={asks.answer.total}
            hasDecisions={hasReviewSurface}
            onOpenDecisions={() => setTab("decisions")}
            programDescription={opp.description}
          />

          {/* "What changed because you asked" — first, because
              it answers a returning reviewer's first question: did the
              thing I asked for happen. Before this the page showed 105
              decisions and zero claims, which is the inverse of the
              priority the design sets (ace#2420). Absent entirely on a
              run that authored no claims — most of them — so those pages
              render exactly as before, with no placeholder. */}
          {claims && (
            <SummarySection title="What changed because you asked">
              <ClaimsSection claims={claims} />
            </SummarySection>
          )}

          {/* Design — what everything below was built from and what a
              reviewer comments on. */}
          <SummarySection title="Design">
            <SectionCaveat text={caveats.get("design")} />
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
                {/* One population (ace-web#740, 2026-10-07). This once
                    read "51 calls ACE made building this run, 23 it
                    couldn't settle", splicing the decisions count with a
                    separate ledger's. The ledger is gone: every ask is a
                    decision row, so the asks below are a genuine subset
                    of the calls, counted by the Decisions tab's own
                    predicate. */}
                <p className="max-w-md text-[0.975rem] leading-[1.7] text-muted-foreground">
                  {decisions ? (
                    <>
                      {`${decisions.total} ${
                        decisions.total === 1 ? "call" : "calls"
                      } ACE made building this program. `}
                      <span className="text-foreground">
                        {asks.outstanding > 0
                          ? [
                              asks.answer.outstanding > 0 &&
                                `${asks.answer.outstanding} ${
                                  asks.answer.outstanding === 1 ? "question" : "questions"
                                } to answer`,
                              confirm.outstanding > 0 &&
                                `${confirm.outstanding} recommended to confirm before launch`,
                            ]
                              .filter(Boolean)
                              .join(", and ") + "."
                          : asks.answer.total === 0 && confirm.total > 0
                            ? `All ${confirm.total} recommended confirmations are answered.`
                            : asks.total > 0
                              ? `Everything ACE asked — ${asks.total} ${
                                  asks.total === 1 ? "item" : "items"
                                } — is answered.`
                            : "React to any of them."}
                      </span>
                    </>
                  ) : null}
                </p>
                {asks.outstanding > 0 && (
                  <p className="w-full text-[0.975rem] leading-[1.7] text-muted-foreground">
                    <span className="font-medium text-foreground">Questions for you</span>
                    {" "}— they are on the Decisions tab, each with who answers it and where,
                    so nothing is asked twice.
                  </p>
                )}
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
            <BuildCaveats build={build} />
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
            <SectionCaveat text={caveats.get("connect")} />
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
            <SectionCaveat text={caveats.get("assistant")} />
            {assistant ? (
              <SummaryRow
                label="Bot"
                name={assistantBlurb(
                  assistant.knowledge_sources,
                  Boolean(assistant.public_id && assistant.embed_key),
                )}
                links={
                  assistant.ocs_url
                    ? // Labelled for what it is. It is the operator's console, not
                      // the way a reader asks a question — that is the widget.
                      [link("Open in OCS (operators)", assistant.ocs_url, assistant.access)]
                    : []
                }
              />
            ) : (
              slot("assistant", "Bot")
            )}
          </SummarySection>

          {/* Deep QA — absent entirely unless `/ace:qa-deep` actually ran.
              It grades the apps AND the assistant, so it sits below both
              rather than inside either. Leads with the GATE: on
              spark-facilitator/20260828-0703 the assistant scores 8.03
              against a 7.0 bar and its gate is `iterate` anyway, because
              a deep pass needs zero failures and two answers fabricated
              safety-adjacent procedure. */}
          {deep_qa && (
            <SummarySection title="Deep QA">
              <DeepQaSection deepQa={deep_qa} isMember={!plain} />
            </SummarySection>
          )}

          {/* Training pack */}
          <SummarySection title="Training pack">
            <SectionCaveat text={caveats.get("training")} />
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
            {/* The walkthrough films the same generated dataset the
                dashboards chart, so it carries the same label. A demo
                that looks like a recording of real fieldwork is the
                more misleading of the two. */}
            {walkthroughs.length > 0 && <SyntheticNotice synthetic={synthetic} />}
            {walkthroughs.length > 0 && <SectionCaveat text={caveats.get("walkthroughs")} />}
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
                        <WalkthroughCaveats ddd={w.ddd} isMember={!plain} />
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
                        {/* The eval score is ACE's internal concept-judge
                            grade — members only (a partner reading "eval
                            3/5" learns nothing about the demo). */}
                        {!plain && w.eval_score != null && (
                          <span className="text-muted-foreground">
                            {" · "}eval {formatEvalScore(w.eval_score)}
                          </span>
                        )}
                        <WalkthroughCaveats ddd={w.ddd} isMember={!plain} />
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
            <SyntheticNotice synthetic={synthetic} />
            {dashboards.length > 0 && <SectionCaveat text={caveats.get("dashboards")} />}
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
            <SectionCaveat text={caveats.get("solicitation")} />
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
                edits={edits}
                viewerIsMember={!!viewer?.is_member}
                plain={plain}
                onReact={handleReact}
                onEdit={handleEdit}
                lineage={lineage}
                onLineageScopeChange={setLineageScope}
              />
            </SummarySection>
          )}

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
