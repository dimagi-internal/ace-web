import type { Edge, Node } from "@xyflow/react";

import type { LinkedChat, Run } from "@/api/types";

interface BuildArgs {
  run: Run;
  chats: LinkedChat[];
  /** Workspace slug for chat links. */
  workspaceSlug: string;
  /** Opp slug, used to build artifact + step deep links. */
  oppSlug: string;
}

interface BuildResult {
  nodes: Node[];
  edges: Edge[];
}

/**
 * Build a left-to-right DAG from a single run's steps + linked chats.
 *
 * Node layout per step (ordinal-ordered along the X axis):
 *   <chats for this step>  →  <step's artifacts>  →  <judge verdict>  →  <gate>
 *                                                              ↘ next step's chats / artifacts
 *
 * Edge derivation rules — kept simple, no timestamp arithmetic:
 *   - Every step's artifact connects forward to that step's verdict (if any),
 *     else to that step's gate (if any), else to the next step's first node.
 *   - Verdict → gate → next step's first node.
 *   - Chats linked to a step connect TO the step's first artifact.
 *
 * If a step has no artifacts / verdict / gate, it's skipped from the DAG —
 * the timeline thread just skips over it. Recurring or pending steps that
 * haven't produced anything aren't useful flow nodes.
 */
export function buildGraphFromRun({
  run,
  chats,
  workspaceSlug,
  oppSlug,
}: BuildArgs): BuildResult {
  const nodes: Node[] = [];
  const edges: Edge[] = [];

  // Steps with at least one artifact / verdict / gate — i.e. things
  // that actually have a node in the graph. Sort by ordinal so the
  // dagre LR layout matches the cycle order even when steps are
  // out-of-order in the JSON.
  const orderedSteps = [...run.steps]
    .filter((s) => s.artifacts.length > 0 || s.judge || s.gates.length > 0)
    .sort((a, b) => a.ordinal - b.ordinal);

  // For chat→step edges: index step-scoped chats by step_skill.
  const chatsByStep = new Map<string, LinkedChat[]>();
  for (const c of chats) {
    if (c.kind !== "step" || !c.step_skill) continue;
    const list = chatsByStep.get(c.step_skill) ?? [];
    list.push(c);
    chatsByStep.set(c.step_skill, list);
  }

  // Track per-step node IDs so we can wire forward edges step→step.
  const firstNodeOfStep: Record<string, string> = {};
  const lastNodeOfStep: Record<string, string> = {};

  for (const step of orderedSteps) {
    const stepKey = step.skill_name;
    const chainHere: string[] = []; // node IDs in flow order, this step

    // 1. Chats for this step (left-most) — only step-scoped, not opp-wide.
    const stepChats = chatsByStep.get(stepKey) ?? [];
    for (const chat of stepChats) {
      const id = `chat:${chat.slug}`;
      nodes.push({
        id,
        type: "chat",
        position: { x: 0, y: 0 }, // dagre overrides
        data: {
          label: chat.title || "(untitled)",
          sub: `${stepKey} · chat`,
          href: `/w/${workspaceSlug}/chat/${chat.slug}`,
        },
      });
      chainHere.push(id);
    }

    // 2. Artifacts for this step.
    for (let i = 0; i < step.artifacts.length; i++) {
      const a = step.artifacts[i];
      const id = `art:${stepKey}:${i}`;
      nodes.push({
        id,
        type: "artifact",
        position: { x: 0, y: 0 },
        data: {
          label: a.name,
          sub: `${stepKey} · ${a.mime_type?.split("/").pop() ?? "file"}`,
          href: a.drive_web_link || undefined,
        },
      });
      chainHere.push(id);
    }

    // 3. Verdict (judge) for this step, if present.
    if (step.judge) {
      const j = step.judge;
      const id = `verdict:${stepKey}`;
      const passed = j.passed;
      const score =
        j.score !== null && j.score !== undefined
          ? j.score > 10
            ? `${j.score.toFixed(0)}/100`
            : `${j.score.toFixed(1)}/10`
          : "scored";
      const label =
        passed === true
          ? `PASS ${score}`
          : passed === false
            ? `FAIL ${score}`
            : score;
      nodes.push({
        id,
        type: "verdict",
        position: { x: 0, y: 0 },
        data: {
          label,
          sub: `${stepKey} · verdict`,
          passed,
          href: `/w/${workspaceSlug}/opps/${oppSlug}/runs/${run.run_id}/steps/${stepKey}`,
        },
      });
      chainHere.push(id);
    }

    // 4. Gate decision for this step (the latest if multiple).
    if (step.gates.length > 0) {
      const gate = step.gates[step.gates.length - 1];
      const id = `gate:${stepKey}`;
      nodes.push({
        id,
        type: "gate",
        position: { x: 0, y: 0 },
        data: {
          label: `gate ${gate.decision}`,
          sub: gate.decided_by ? `by ${gate.decided_by}` : `${stepKey} · gate`,
          href: `/w/${workspaceSlug}/opps/${oppSlug}/runs/${run.run_id}/steps/${stepKey}`,
        },
      });
      chainHere.push(id);
    }

    // Wire intra-step edges (linear chain).
    for (let i = 0; i < chainHere.length - 1; i++) {
      edges.push({
        id: `e:${chainHere[i]}->${chainHere[i + 1]}`,
        source: chainHere[i],
        target: chainHere[i + 1],
      });
    }

    if (chainHere.length > 0) {
      firstNodeOfStep[stepKey] = chainHere[0];
      lastNodeOfStep[stepKey] = chainHere[chainHere.length - 1];
    }
  }

  // Inter-step edges: last node of step N → first node of step N+1.
  for (let i = 0; i < orderedSteps.length - 1; i++) {
    const a = orderedSteps[i].skill_name;
    const b = orderedSteps[i + 1].skill_name;
    const src = lastNodeOfStep[a];
    const tgt = firstNodeOfStep[b];
    if (src && tgt) {
      edges.push({ id: `e:step:${a}->${b}`, source: src, target: tgt });
    }
  }

  return { nodes, edges };
}
