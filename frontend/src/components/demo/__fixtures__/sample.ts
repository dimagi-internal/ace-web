/**
 * A representative Demo Player payload.
 *
 * Shaped like a real completed run: seven phases, measured per-step timing,
 * one step its own judge refused to pass, and a decisions log with two rows a
 * human changed. Used by the page tests, and handy for working on the
 * player's visuals without a live run behind it.
 */
import type {
  DemoEvent,
  DemoLedger,
  DemoPayload,
  DemoTimeline,
  LedgerPhase,
  LedgerSkill,
} from "@/api/demo";

const PHASES: ReadonlyArray<readonly [string, string, number]> = [
  ["1-design", "Design", 4],
  ["2-scenarios", "Scenarios & acceptance", 2],
  ["3-commcare", "CommCare setup", 6],
  ["4-connect", "Connect setup", 3],
  ["5-ocs", "Support chatbot", 2],
  ["6-qa-training", "QA & training", 7],
  ["8-solicitation", "Solicitation", 2],
];

/** The one step whose judge refuses it, so the "what it caught" act has a subject. */
const FAILING_SKILL = "commcare-skill-5";
const FAILING_RATIONALE =
  "Deliver form asks visit outcome before the photo; a worker does that the other way round.";

const events: DemoEvent[] = [];
const ledgerPhases: LedgerPhase[] = [];

let clock = 0;
let seq = 0;

for (const [phase, phase_display, count] of PHASES) {
  const phaseStart = clock;
  events.push({ seq: seq++, t: clock, kind: "phase_start", phase, phase_display });

  const skills: LedgerSkill[] = [];
  for (let i = 0; i < count; i += 1) {
    const skill = `${phase.split("-")[1]}-skill-${i + 1}`;
    const skill_display = `${phase_display} step ${i + 1}`;
    // Deterministic but uneven, so bars and ticks don't come out uniform.
    const seconds = 780 + Math.round(Math.sin(seq) * 200);
    const failed = skill === FAILING_SKILL;

    events.push({
      seq: seq++, t: clock, kind: "step_start", phase, phase_display, skill, skill_display,
    });
    clock += seconds;
    events.push({
      seq: seq++, t: clock, kind: "step_end", phase, phase_display, skill, skill_display,
      status: failed ? "judge-fail" : "complete",
      duration_seconds: seconds,
      artifacts: [{ name: `${skill}.md`, url: "#" }],
      judge: failed
        ? { score: 2, passed: false, rationale: FAILING_RATIONALE }
        : { score: 8, passed: true },
      qa_result: null,
      error: null,
    });

    skills.push({
      skill, skill_display,
      status: failed ? "judge-fail" : "complete",
      seconds,
    });
    clock += 120; // handoff gap between skills
  }

  ledgerPhases.push({
    phase, phase_display,
    seconds: clock - phaseStart,
    active_seconds: skills.reduce((total, s) => total + (s.seconds ?? 0), 0),
    skill_count: count,
    skills,
  });
  clock += 300; // gap between phases
}

const WALL_SECONDS = clock;

const timeline: DemoTimeline = {
  timing_source: "measured",
  origin: "2026-07-22T13:41:00Z",
  wall_seconds: WALL_SECONDS,
  events,
};

const ledger: DemoLedger = {
  wall_seconds: WALL_SECONDS,
  timing_source: "measured",
  phases: ledgerPhases,
};

export const SAMPLE: DemoPayload = {
  schema_version: 1,
  run: {
    opp_slug: "hh-poverty-targeting",
    opp_title: "Household poverty targeting",
    run_id: "20260722-1341",
    status: "complete",
    started_at: "2026-07-22T13:41:00Z",
    completed_at: "2026-07-22T22:15:00Z",
    wall_seconds: WALL_SECONDS,
    step_count: PHASES.reduce((total, [, , count]) => total + count, 0),
  },
  timing_source: "measured",
  capabilities: { timeline: true, time_ledger: true, gates: true, decisions: true },
  acts: [
    { id: "timeline", title: "The run", available: true, unavailable_reason: null, data: timeline },
    {
      id: "time_ledger", title: "Where the time went",
      available: true, unavailable_reason: null, data: ledger,
    },
    {
      id: "gates", title: "What it caught",
      available: true, unavailable_reason: null,
      data: {
        gates: [
          {
            skill: FAILING_SKILL, skill_display: "CommCare setup step 5",
            phase: "3-commcare", phase_display: "CommCare setup", ordinal: 5,
            status: "judge-fail",
            judge: { score: 2, passed: false, rationale: FAILING_RATIONALE },
            qa_result: null, error: null,
          },
        ],
      },
    },
    {
      id: "decisions", title: "What it decided",
      available: true, unavailable_reason: null,
      data: {
        total: 5,
        overridden_count: 2,
        rows: [
          {
            row_id: "d1", status: "overridden",
            question: "Which programme archetype fits this design?",
            ai_default: "Data collection", override: "Service delivery",
            override_reasoning: "The partner pays per completed visit, not per form.",
          },
          {
            row_id: "d2", status: "overridden",
            question: "How much does a worker earn per verified visit?",
            ai_default: "1.50 per visit", override: "2.10 per visit",
          },
          { row_id: "d3", status: "ai-default", question: "Is a photo required on every visit?", ai_default: "Yes" },
          { row_id: "d4", status: "ai-default", question: "What is the daily visit cap per worker?", ai_default: "12" },
          { row_id: "d5", status: "ai-default", question: "Which language does the Learn app open in?", ai_default: "English" },
        ],
      },
    },
  ],
};
