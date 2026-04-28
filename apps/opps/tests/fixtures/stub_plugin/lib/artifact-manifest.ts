/**
 * Canonical artifact manifest for ACE opportunities.
 *
 * Every file that an ACE skill reads from or writes to Google Drive under
 * `ACE/<opp-name>/` is listed here. This module is the single source of truth
 * for:
 *   - What artifacts exist at each lifecycle phase
 *   - Which skill produces each artifact
 *   - Which skills consume each artifact
 *   - Whether an artifact is required or optional at phase completion
 *
 * Skills are SKILL.md prompt files and cannot import this module at runtime.
 * The manifest is used by:
 *   - Test fixture validation (does the fixture have the right files?)
 *   - Future ace:doctor checks on live opportunity Drive folders
 *   - Documentation generation
 *
 * To audit: grep -r 'ACE/<opp-name>' skills/ agents/
 */

// ── Types ──────────────────────────────────────────────────────────

export type Phase = 'design' | 'commcare' | 'connect' | 'ocs' | 'operate' | 'closeout';

export interface ArtifactEntry {
  /** Relative path under ACE/<opp-name>/, e.g. "pdd.md" or "apps/learn-app.json" */
  path: string;
  /** Skill that creates this artifact (or "external" for human-provided inputs) */
  producedBy: string;
  /** Skills that read this artifact as input */
  consumedBy: string[];
  /** Lifecycle phase when this artifact is produced */
  phase: Phase;
  /** Must exist when this phase completes (false = conditional/optional) */
  required: boolean;
  /** Human-readable purpose */
  description: string;
}

// ── Phase ordering ─────────────────────────────────────────────────

export const PHASES = ['design', 'commcare', 'connect', 'ocs', 'operate', 'closeout'] as const;

// ── Manifest ───────────────────────────────────────────────────────

export const ARTIFACT_MANIFEST: readonly ArtifactEntry[] = [
  // ── Design phase (Phase 1) ─────────────────────────────────────

  {
    path: 'idea.md',
    producedBy: 'external',
    consumedBy: ['idea-to-pdd'],
    phase: 'design',
    required: true,
    description: 'Initial opportunity idea or brief',
  },
  {
    path: 'pdd.md',
    producedBy: 'idea-to-pdd',
    consumedBy: [
      'pdd-to-test-prompts', 'pdd-to-learn-app', 'pdd-to-deliver-app', 'app-test',
      'training-materials', 'connect-program-setup', 'connect-opp-setup',
      'llo-invite', 'ocs-agent-setup', 'timeline-monitor', 'flw-data-review',
      'cycle-grade', 'learnings-summary',
    ],
    phase: 'design',
    required: true,
    description: 'Program Design Document with archetype, Evidence Model, and stress-test appendix',
  },
  {
    path: 'test-prompts.md',
    producedBy: 'pdd-to-test-prompts',
    consumedBy: ['ocs-chatbot-qa'],
    phase: 'design',
    required: true,
    description: 'Opp-specific Q&A pairs derived from the PDD; each entry has an expected-answer summary that ocs-chatbot-qa embeds in the transcript and ocs-chatbot-eval grades against',
  },
  {
    path: 'state.yaml',
    producedBy: 'ace-orchestrator',
    consumedBy: ['timeline-monitor'],
    phase: 'design',
    required: true,
    description: 'Opportunity lifecycle state: phase, step, mode, gate approvals, initiated_by / last_actor / last_actor_at',
  },
  {
    path: 'gate-briefs/idea-to-pdd.md',
    producedBy: 'idea-to-pdd',
    consumedBy: ['ace-orchestrator'],
    phase: 'design',
    required: true,
    description: 'Gate brief for the Phase 1→2 gate: checklist + stress-test concerns for the PDD',
  },

  // ── CommCare phase (Phase 2) ───────────────────────────────────

  {
    path: 'apps/learn-app.json',
    producedBy: 'pdd-to-learn-app',
    consumedBy: [],
    phase: 'commcare',
    required: false,
    description: 'Optional historical snapshot of the Learn app structure (output of `/nova:show <id>`). Not required: Nova is the system of record for the app, and the canonical handle is `nova_app_id` in the summary frontmatter (see 2026-04-27 Nova-plugin migration note).',
  },
  {
    path: 'apps/deliver-app.json',
    producedBy: 'pdd-to-deliver-app',
    consumedBy: [],
    phase: 'commcare',
    required: false,
    description: 'Optional historical snapshot of the Deliver app structure (output of `/nova:show <id>`). Not required — see Learn equivalent above.',
  },
  {
    path: 'app-summaries/learn-app-summary.md',
    producedBy: 'pdd-to-learn-app',
    consumedBy: ['app-deploy', 'app-test', 'training-materials', 'ocs-agent-setup', 'flw-data-review'],
    phase: 'commcare',
    required: true,
    description: 'Learn app structure summary for downstream skills. Required frontmatter: `nova_app_id`, `nova_app_url`, `archetype`. `app-deploy` reads `nova_app_id` from here to feed `/nova:upload_to_hq`.',
  },
  {
    path: 'app-summaries/deliver-app-summary.md',
    producedBy: 'pdd-to-deliver-app',
    consumedBy: ['app-deploy', 'app-test', 'training-materials', 'ocs-agent-setup', 'flw-data-review'],
    phase: 'commcare',
    required: true,
    description: 'Deliver app structure summary for downstream skills. Required frontmatter: `nova_app_id`, `nova_app_url`, `archetype`, `delivery_unit`. `app-deploy` reads `nova_app_id` from here.',
  },
  {
    path: 'deployment-summary.md',
    producedBy: 'app-deploy',
    consumedBy: ['app-test', 'connect-opp-setup', 'llo-uat', 'llo-launch'],
    phase: 'commcare',
    required: true,
    description: 'App deployment details: IDs, URLs, build status',
  },
  {
    path: 'gate-briefs/app-deploy.md',
    producedBy: 'app-deploy',
    consumedBy: ['ace-orchestrator'],
    phase: 'commcare',
    required: true,
    description: 'Gate brief for the Phase 2→3 gate: build status, Connectify flags, and an HQ-domain-mismatch BLOCKER if Nova is bound to the wrong project space',
  },
  {
    path: 'test-results/test-plan.md',
    producedBy: 'app-test',
    consumedBy: ['learnings-summary', 'cycle-grade'],
    phase: 'commcare',
    required: true,
    description: 'Full test plan with Evidence Model cross-references',
  },
  {
    path: 'test-results/test-results.md',
    producedBy: 'app-test',
    consumedBy: ['learnings-summary', 'cycle-grade'],
    phase: 'commcare',
    required: true,
    description: 'Test execution results: pass/fail per test case',
  },
  {
    path: 'test-results/bugs.md',
    producedBy: 'app-test',
    consumedBy: ['learnings-summary', 'cycle-grade'],
    phase: 'commcare',
    required: true,
    description: 'Bugs found during testing with severity and repro steps',
  },
  {
    path: 'training-materials/llo-manager-guide.md',
    producedBy: 'training-materials',
    consumedBy: ['llo-onboarding', 'ocs-agent-setup'],
    phase: 'commcare',
    required: true,
    description: 'LLO Manager guide for overseeing FLW deployment',
  },
  {
    path: 'training-materials/flw-training-guide.md',
    producedBy: 'training-materials',
    consumedBy: ['llo-onboarding', 'ocs-agent-setup'],
    phase: 'commcare',
    required: true,
    description: 'FLW training guide for app usage and protocols',
  },
  {
    path: 'training-materials/quick-reference.md',
    producedBy: 'training-materials',
    consumedBy: ['llo-onboarding', 'ocs-agent-setup'],
    phase: 'commcare',
    required: true,
    description: 'Quick reference card for FLWs in the field',
  },
  {
    path: 'training-materials/faq.md',
    producedBy: 'training-materials',
    consumedBy: ['llo-onboarding', 'ocs-agent-setup'],
    phase: 'commcare',
    required: true,
    description: 'Frequently asked questions for LLOs and FLWs',
  },

  // ── Connect phase (Phase 3) ────────────────────────────────────

  {
    path: 'connect-setup/program.md',
    producedBy: 'connect-program-setup',
    consumedBy: ['connect-opp-setup'],
    phase: 'connect',
    required: true,
    description: 'Connect Program ID, name, config details',
  },
  {
    path: 'connect-setup/opportunity.md',
    producedBy: 'connect-opp-setup',
    consumedBy: ['llo-invite', 'llo-onboarding', 'llo-uat', 'llo-launch', 'ocs-agent-setup', 'opp-closeout'],
    phase: 'connect',
    required: true,
    description: 'Connect Opportunity ID, verification rules, delivery/payment unit config',
  },
  // llo-invite artifacts moved to Phase 5 (operate) on 2026-04-20 — see
  // the "Operate phase" block below. invite-list prep no longer blocks
  // Phase 3→4; it now runs as the first step of Phase 5 after the OCS
  // chatbot has cleared its deep-eval gate.

  // ── OCS phase (Phase 4) ────────────────────────────────────────

  {
    path: 'ocs-agent-config.md',
    producedBy: 'ocs-agent-setup',
    consumedBy: ['ocs-chatbot-qa', 'ocs-chatbot-eval', 'llo-onboarding', 'timeline-monitor', 'flw-data-review'],
    phase: 'ocs',
    required: true,
    description: 'OCS chatbot config: experiment_id, public_id, embed_key, collection_id',
  },
  {
    path: 'ocs-setup/widget-handoff.md',
    producedBy: 'ocs-setup',
    consumedBy: ['llo-onboarding'],
    phase: 'ocs',
    required: true,
    description: 'Operator-facing handoff doc: creds + paste instructions for the Connect opportunity widget (until update_opportunity API lands)',
  },
  {
    path: 'qa-captures/YYYY-MM-DD-ocs-chat-quick.md',
    producedBy: 'ocs-chatbot-qa',
    consumedBy: ['ocs-chatbot-eval'],
    phase: 'ocs',
    required: false,
    description: 'Transcript from the --quick suite (5 smoke prompts): each entry has prompt + response + cited_files + expected_answer_summary + structural-pass flag. Input to ocs-chatbot-eval --quick',
  },
  {
    path: 'qa-captures/YYYY-MM-DD-ocs-chat-deep.md',
    producedBy: 'ocs-chatbot-qa',
    consumedBy: ['ocs-chatbot-eval'],
    phase: 'ocs',
    required: true,
    description: 'Transcript from the --deep suite (Connect-general + ACE-specific + opp-specific + edge cases): structured transcript input to ocs-chatbot-eval --deep',
  },
  {
    path: 'verdicts/ocs-chatbot-eval-quick.yaml',
    producedBy: 'ocs-chatbot-eval',
    consumedBy: [],
    phase: 'ocs',
    required: false,
    description: 'Machine-readable verdict from --quick LLM-as-Judge grading: overall_score, per-dimension scores, per-prompt verdicts, gate disposition. Shape matches skills/README.md § QA vs Eval',
  },
  {
    path: 'verdicts/ocs-chatbot-eval-deep.yaml',
    producedBy: 'ocs-chatbot-eval',
    consumedBy: [],
    phase: 'ocs',
    required: true,
    description: 'Machine-readable verdict from --deep LLM-as-Judge grading; read by opp-eval (future) for cross-skill aggregation',
  },
  {
    path: 'gate-briefs/ocs-chatbot-eval-deep.md',
    producedBy: 'ocs-chatbot-eval',
    consumedBy: ['ace-orchestrator'],
    phase: 'ocs',
    required: true,
    description: 'Gate brief for the Phase 4→5 gate: deep-eval scorecard, failing prompts, dimension weak spots',
  },

  // ── Operate phase (Phase 5) ────────────────────────────────────

  // Path kept as ``connect-setup/invites.md`` rather than renamed to
  // ``invites/…`` so existing opps don't orphan their prior invite
  // lists on the phase-reassignment date (2026-04-20).
  {
    path: 'connect-setup/invites.md',
    producedBy: 'llo-invite',
    consumedBy: ['llo-onboarding', 'llo-uat', 'llo-launch', 'llo-feedback'],
    phase: 'operate',
    required: true,
    description: 'LLO invite list (prepared and sent within Phase 5)',
  },
  {
    path: 'gate-briefs/llo-invite.md',
    producedBy: 'llo-invite',
    consumedBy: ['ace-orchestrator'],
    phase: 'operate',
    required: true,
    description: 'Gate brief for the Phase 5 invite-list gate (blocks llo-onboarding): invite-list completeness, duplicates, count drift',
  },
  {
    path: 'comms-log/onboarding-emails.md',
    producedBy: 'llo-onboarding',
    consumedBy: ['learnings-summary'],
    phase: 'operate',
    required: true,
    description: 'Onboarding email records with recipients, subject, body, timestamp',
  },
  {
    path: 'uat/uat-results.md',
    producedBy: 'llo-uat',
    consumedBy: ['llo-launch'],
    phase: 'operate',
    required: true,
    description: 'Per-LLO sign-off status, issues found, overall UAT verdict',
  },
  {
    path: 'launch/launch-record.md',
    producedBy: 'llo-launch',
    consumedBy: ['timeline-monitor'],
    phase: 'operate',
    required: true,
    description: 'Activation timestamp, LLO notifications, app URLs, outstanding issues',
  },
  {
    path: 'gate-briefs/llo-launch.md',
    producedBy: 'llo-launch',
    consumedBy: ['ace-orchestrator'],
    phase: 'operate',
    required: true,
    description: 'Gate brief for the Phase 5 launch gate: UAT sign-offs, app build status, launch-readiness',
  },
  {
    path: 'qa-captures/YYYY-MM-DD-ocs-chat-monitor.md',
    producedBy: 'ocs-chatbot-qa',
    consumedBy: ['ocs-chatbot-eval'],
    phase: 'operate',
    required: false,
    description: 'Transcript from recurring --monitor runs; structured input to ocs-chatbot-eval --monitor',
  },
  {
    path: 'verdicts/ocs-chatbot-eval-monitor.yaml',
    producedBy: 'ocs-chatbot-eval',
    consumedBy: [],
    phase: 'operate',
    required: false,
    description: 'Machine-readable verdict from recurring --monitor runs. Latest-wins file; see eval-reports/trend.md for history',
  },
  {
    path: 'eval-reports/YYYY-MM-DD-ocs-eval.md',
    producedBy: 'ocs-chatbot-eval',
    consumedBy: [],
    phase: 'ocs',
    required: false,
    description: 'Human-readable eval report (Phase 4 deep gate + Phase 5 recurring monitor). Complements the machine-readable verdicts/ yaml',
  },
  {
    path: 'eval-reports/trend.md',
    producedBy: 'ocs-chatbot-eval',
    consumedBy: [],
    phase: 'operate',
    required: false,
    description: 'Rolling trend of OCS eval scores from --monitor runs; one line per run',
  },
  {
    path: 'monitoring/YYYY-MM-DD-timeline-check.md',
    producedBy: 'timeline-monitor',
    consumedBy: ['learnings-summary', 'cycle-grade'],
    phase: 'operate',
    required: false,
    description: 'Weekly timeline status, progress indicators, prompting email drafts',
  },
  {
    path: 'data-reviews/YYYY-MM-DD-review.md',
    producedBy: 'flw-data-review',
    consumedBy: ['learnings-summary', 'cycle-grade'],
    phase: 'operate',
    required: false,
    description: 'FLW data quality assessment: per-delivery (Layer B) and cross-delivery (Layer C)',
  },

  // ── Closeout phase ─────────────────────────────────────────────

  {
    path: 'closeout/invoices.md',
    producedBy: 'opp-closeout',
    consumedBy: [],
    phase: 'closeout',
    required: true,
    description: 'Invoice details, total payment amount, Jira ticket link',
  },
  {
    path: 'closeout/llo-feedback.md',
    producedBy: 'llo-feedback',
    consumedBy: ['learnings-summary', 'cycle-grade'],
    phase: 'closeout',
    required: true,
    description: 'Per-LLO feedback responses, common themes, improvement suggestions',
  },
  {
    path: 'closeout/learnings.md',
    producedBy: 'learnings-summary',
    consumedBy: ['cycle-grade'],
    phase: 'closeout',
    required: true,
    description: 'Process/content/technical/relationship learnings against original PDD',
  },
  {
    path: 'closeout/new-pdd.md',
    producedBy: 'learnings-summary',
    consumedBy: [],
    phase: 'closeout',
    required: false,
    description: 'New PDD incorporating learnings (only if iteration warranted)',
  },
  {
    path: 'closeout/cycle-grade.md',
    producedBy: 'cycle-grade',
    consumedBy: [],
    phase: 'closeout',
    required: true,
    description: '6/7-dimension grades with evidence, recommendations, narrative assessment',
  },

  // ── Umbrella eval (opp-eval) — ad-hoc, opt-in; not part of the default 6-phase pipeline ──

  {
    path: 'scorecards/YYYY-MM-DD-opp-eval-quick.md',
    producedBy: 'opp-eval',
    consumedBy: [],
    phase: 'closeout',
    required: false,
    description: 'Human-readable quick scorecard from opp-eval --quick (structural artifact check only, no LLM cost)',
  },
  {
    path: 'scorecards/YYYY-MM-DD-opp-eval-deep.md',
    producedBy: 'opp-eval',
    consumedBy: [],
    phase: 'closeout',
    required: false,
    description: 'Human-readable run-level scorecard from opp-eval --deep: category breakdown, per-skill results, improvement recommendations',
  },
  {
    path: 'scorecards/YYYY-MM-DD-opp-eval-monitor.md',
    producedBy: 'opp-eval',
    consumedBy: [],
    phase: 'closeout',
    required: false,
    description: 'Human-readable scorecard from opp-eval --monitor runs; same shape as --deep plus a trend-file append',
  },
  {
    path: 'scorecards/trend.md',
    producedBy: 'opp-eval',
    consumedBy: [],
    phase: 'closeout',
    required: false,
    description: 'Rolling trend of run-level opp-eval scores from --monitor runs; one line per run with date, overall, and category breakdown',
  },
  {
    path: 'verdicts/opp-eval-deep.yaml',
    producedBy: 'opp-eval',
    consumedBy: [],
    phase: 'closeout',
    required: false,
    description: 'Machine-readable run-level verdict from opp-eval --deep: 6-category aggregation of every per-skill verdict found under verdicts/, plus improvement recommendations. Shape matches skills/README.md § QA vs Eval',
  },
  {
    path: 'verdicts/opp-eval-monitor.yaml',
    producedBy: 'opp-eval',
    consumedBy: [],
    phase: 'closeout',
    required: false,
    description: 'Machine-readable run-level verdict from opp-eval --monitor runs; latest-wins file (history lives in scorecards/trend.md)',
  },
  {
    path: 'gate-briefs/opp-eval-deep.md',
    producedBy: 'opp-eval',
    consumedBy: [],
    phase: 'closeout',
    required: false,
    description: 'Advisory brief from opp-eval --deep / --monitor. Written for contract uniformity with the 5 real gate briefs; does NOT gate any phase today (opp-eval is ad-hoc, not part of --mode review auto-pause flow)',
  },
] as const;

// ── Helpers ────────────────────────────────────────────────────────

/** Return artifacts produced in (or before) the given phase. */
export function artifactsForPhase(phase: Phase): ArtifactEntry[] {
  const idx = PHASES.indexOf(phase);
  return ARTIFACT_MANIFEST.filter((a) => PHASES.indexOf(a.phase) <= idx);
}

/** Return artifacts a specific skill writes. */
export function artifactsProducedBy(skill: string): ArtifactEntry[] {
  return ARTIFACT_MANIFEST.filter((a) => a.producedBy === skill);
}

/** Return artifacts a specific skill reads. */
export function artifactsConsumedBy(skill: string): ArtifactEntry[] {
  return ARTIFACT_MANIFEST.filter((a) => a.consumedBy.includes(skill));
}

/**
 * Validate a set of file paths against the manifest up to a given phase.
 *
 * @param filePaths - actual file paths relative to the opp root (e.g. from listing a fixture or Drive folder)
 * @param upToPhase - include artifacts from phases up to and including this one
 * @param exempt - paths to ignore (e.g. "README.md")
 * @returns present, missing (required but absent), and unexpected (not in manifest) paths
 */
export function validateFixture(
  filePaths: string[],
  upToPhase: Phase,
  exempt: string[] = [],
): { present: string[]; missing: string[]; unexpected: string[] } {
  const expected = artifactsForPhase(upToPhase);
  // Only check required, non-dated artifacts (YYYY-MM-DD patterns are recurring/optional)
  const requiredPaths = expected
    .filter((a) => a.required && !a.path.includes('YYYY-MM-DD'))
    .map((a) => a.path);

  const knownPaths = new Set(
    expected.map((a) => a.path),
  );

  const present: string[] = [];
  const unexpected: string[] = [];

  for (const fp of filePaths) {
    if (exempt.includes(fp)) continue;
    if (knownPaths.has(fp)) {
      present.push(fp);
    } else {
      unexpected.push(fp);
    }
  }

  const presentSet = new Set(present);
  const missing = requiredPaths.filter((p) => !presentSet.has(p));

  return { present, missing, unexpected };
}
