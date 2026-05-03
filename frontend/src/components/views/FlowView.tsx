import { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import {
  Background,
  Controls,
  MiniMap,
  ReactFlow,
  ReactFlowProvider,
  type Edge,
  type Node,
} from "@xyflow/react";

import "@xyflow/react/dist/style.css";

import { getLinkedChats, getOpp } from "@/api/opps";
import type { LinkedChat, OppSnapshot } from "@/api/types";

import { layoutDag } from "./flow/layout";
import { buildGraphFromRun } from "./flow/graphFromRun";
import { NODE_TYPES } from "./flow/nodes";

interface Props {
  oppSlug: string;
  /** Run id to render. Defaults to the snapshot's selected_run_id (typically "r1"). */
  runId?: string;
}

/**
 * Per-opp flow view: a left-to-right DAG showing chats → artifacts →
 * verdicts → gates for one run, with React Flow + dagre.
 *
 * Data source is the existing /api/opps/<slug>?run_id=<run> snapshot
 * plus /api/opps/<slug>/runs/<run>/steps/<skill>/chats per step.
 * No new backend endpoint — the snapshot already carries everything
 * needed.
 *
 * Steps that have no artifacts / verdict / gate (recurring + pending
 * steps that haven't produced anything) are dropped from the graph
 * to keep the canvas focused on causal events.
 */
export function FlowView({ oppSlug, runId }: Props) {
  const { workspaceSlug = "" } = useParams<{ workspaceSlug?: string }>();
  const [snapshot, setSnapshot] = useState<OppSnapshot | null>(null);
  const [chats, setChats] = useState<LinkedChat[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setError(null);
    setSnapshot(null);
    let cancelled = false;
    getOpp(oppSlug, runId)
      .then((s) => {
        if (cancelled) return;
        setSnapshot(s);
      })
      .catch((e) => {
        if (!cancelled) setError(String((e as Error)?.message ?? e));
      });
    return () => {
      cancelled = true;
    };
  }, [oppSlug, runId]);

  // Once we have the snapshot, fetch chats for every step that has any
  // artifacts / verdict / gate (i.e. would render in the graph). The
  // existing per-step endpoint is the easiest way; we union the
  // results client-side. Cap to first 50 steps to bound the fan-out.
  useEffect(() => {
    if (!snapshot) return;
    const candidateSteps = snapshot.current_run.steps
      .filter((s) => s.artifacts.length > 0 || s.judge || s.gates.length > 0)
      .slice(0, 50);
    if (candidateSteps.length === 0) {
      setChats([]);
      return;
    }
    let cancelled = false;
    Promise.all(
      candidateSteps.map((s) =>
        getLinkedChats(oppSlug, snapshot.current_run.run_id, s.skill_name)
          .catch(() => [] as LinkedChat[]),
      ),
    ).then((lists) => {
      if (cancelled) return;
      // Dedupe by chat slug — opp-wide chats appear in every step's list.
      const seen = new Set<string>();
      const merged: LinkedChat[] = [];
      for (const list of lists) {
        for (const c of list) {
          if (seen.has(c.slug)) continue;
          seen.add(c.slug);
          merged.push(c);
        }
      }
      setChats(merged);
    });
    return () => {
      cancelled = true;
    };
  }, [snapshot, oppSlug]);

  const { nodes, edges } = useMemo<{ nodes: Node[]; edges: Edge[] }>(() => {
    if (!snapshot) return { nodes: [], edges: [] };
    const { nodes, edges } = buildGraphFromRun({
      run: snapshot.current_run,
      chats,
      workspaceSlug,
      oppSlug,
    });
    return { nodes: layoutDag(nodes, edges), edges };
  }, [snapshot, chats, workspaceSlug, oppSlug]);

  if (error) {
    return (
      <div className="p-6 text-center text-sm text-destructive">{error}</div>
    );
  }
  if (!snapshot) {
    return (
      <div className="p-6 text-center text-sm text-muted-foreground">
        Loading flow…
      </div>
    );
  }
  if (nodes.length === 0) {
    return (
      <div className="p-6 text-center text-sm text-muted-foreground">
        No artifacts, verdicts, or gates produced yet for this run.
      </div>
    );
  }

  return (
    <div className="h-full w-full bg-background">
      <ReactFlowProvider>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={NODE_TYPES}
          fitView
          fitViewOptions={{ padding: 0.15 }}
          proOptions={{ hideAttribution: true }}
          nodesDraggable={false}
          nodesConnectable={false}
        >
          <Background gap={16} color="hsl(var(--border))" />
          <Controls position="bottom-right" showInteractive={false} />
          <MiniMap
            position="top-right"
            pannable
            zoomable
            ariaLabel="Flow minimap"
            style={{
              background: "hsl(var(--card))",
              border: "1px solid hsl(var(--border))",
            }}
          />
        </ReactFlow>
      </ReactFlowProvider>
    </div>
  );
}
