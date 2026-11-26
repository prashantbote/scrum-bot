"use client";

import * as React from "react";
import { Background, MarkerType, ReactFlow, type Edge, type Node } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import type { DependencyGraph as Graph } from "@/lib/api/types";

/**
 * Who this team waits on. The selected team sits on the left; teams/people it depends on
 * fan out on the right. Edge width and label show how many times the dependency came up.
 */
export default function DependencyGraph({ graph, height = 220 }: { graph: Graph; height?: number }) {
  const { nodes, edges } = React.useMemo(() => {
    const self = graph.nodes.filter((n) => n.is_self);
    const others = graph.nodes.filter((n) => !n.is_self);
    const rowH = 56;
    const totalH = Math.max(others.length, 1) * rowH;
    const style = (isSelf: boolean): React.CSSProperties => ({
      background: isSelf ? "var(--teal-50)" : "var(--surface)",
      border: `1px solid ${isSelf ? "var(--teal-600)" : "var(--border-strong)"}`,
      color: isSelf ? "var(--teal-700)" : "var(--text)",
      borderRadius: 6,
      fontSize: 12,
      fontWeight: 500,
      padding: "6px 10px",
      width: 150,
      boxShadow: "var(--shadow-card)",
    });
    const nodes: Node[] = [
      ...self.map((n) => ({
        id: n.id,
        position: { x: 0, y: totalH / 2 - rowH / 2 },
        data: { label: n.label },
        style: style(true),
        sourcePosition: "right" as Node["sourcePosition"],
        targetPosition: "left" as Node["targetPosition"],
        draggable: false,
      })),
      ...others.map((n, i) => ({
        id: n.id,
        position: { x: 280, y: i * rowH },
        data: { label: n.label },
        style: style(false),
        targetPosition: "left" as Node["targetPosition"],
        sourcePosition: "right" as Node["sourcePosition"],
        draggable: false,
      })),
    ];
    const max = Math.max(1, ...graph.edges.map((e) => e.weight));
    const edges: Edge[] = graph.edges.map((e) => ({
      id: `${e.source}-${e.target}`,
      source: e.source,
      target: e.target,
      label: `×${e.weight}`,
      labelStyle: { fontSize: 11, fill: "var(--text-muted)" },
      labelBgStyle: { fill: "var(--surface)" },
      style: { stroke: e.weight === max ? "var(--blue-600)" : "var(--chart-5)", strokeWidth: 1 + (e.weight / max) * 2 },
      markerEnd: { type: MarkerType.ArrowClosed, color: e.weight === max ? "var(--blue-600)" : "var(--chart-5)" },
    }));
    return { nodes, edges };
  }, [graph]);

  const summary = graph.edges
    .slice()
    .sort((a, b) => b.weight - a.weight)
    .map((e) => `${graph.nodes.find((n) => n.id === e.target)?.label} ×${e.weight}`)
    .join(", ");

  return (
    <figure style={{ height }} className="m-0">
      <figcaption className="sr-only">Dependency map. Waits on: {summary || "nothing this period"}</figcaption>
      {/* Visual only: `inert` keeps the canvas out of the tab order and a11y tree; the figcaption carries the content. */}
      <div inert className="h-full">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        fitView
        fitViewOptions={{ padding: 0.2 }}
        nodesConnectable={false}
        nodesFocusable={false}
        edgesFocusable={false}
        elementsSelectable={false}
        panOnDrag={false}
        zoomOnScroll={false}
        zoomOnPinch={false}
        zoomOnDoubleClick={false}
      >
        <Background color="var(--border)" gap={16} size={1} />
      </ReactFlow>
      </div>
    </figure>
  );
}
