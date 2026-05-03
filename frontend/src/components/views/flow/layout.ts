import dagre from "dagre";
import type { Edge, Node } from "@xyflow/react";

const NODE_W = 220;
const NODE_H = 60;

/**
 * Run a left-to-right dagre layout over a node + edge set, returning
 * the same nodes with `position` populated. Node sizes are pinned to
 * the constants above; if the visual changes, update both.
 */
export function layoutDag(nodes: Node[], edges: Edge[]): Node[] {
  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({ rankdir: "LR", nodesep: 24, ranksep: 70, marginx: 16, marginy: 16 });

  for (const n of nodes) g.setNode(n.id, { width: NODE_W, height: NODE_H });
  for (const e of edges) g.setEdge(e.source, e.target);

  dagre.layout(g);

  return nodes.map((n) => {
    const p = g.node(n.id);
    return {
      ...n,
      position: { x: p.x - NODE_W / 2, y: p.y - NODE_H / 2 },
    };
  });
}
