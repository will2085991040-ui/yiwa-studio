"use client";

// IDE 中央无限画布：真正的 ReactFlow 节点编辑器（受控组件）。
// 深紫蓝网格 + 粉紫节点卡片；支撑缩放 / 平移 / 拖动 / 连线 / 框选 / Minimap。
import { createContext, useContext, useMemo } from "react";
import ReactFlow, {
  Background,
  BackgroundVariant,
  Controls,
  Handle,
  MarkerType,
  MiniMap,
  Position,
  type Connection,
  type Edge,
  type Node,
  type NodeProps,
  type NodeTypes,
  type OnEdgesChange,
  type OnNodesChange,
} from "reactflow";
import "reactflow/dist/style.css";
import {
  KIND_COLOR,
  KIND_LABEL,
  type IdeEdge,
  type IdeNode,
} from "./workspace";

export type { IdeEdge, IdeNode };
export { KIND_COLOR, KIND_LABEL } from "./workspace";

const NodeUiCtx = createContext<{ onOpenCanvas?: (id: string) => void; thumbs?: Record<string, string> }>({});

type Badge = { label: string; border: string; bg: string; color: string };

function statusBadge(status?: string, generating?: boolean): Badge {
  const dim: Badge = { label: "○ 待生成", color: "#94a3b8", border: "rgba(148,163,184,.3)", bg: "rgba(148,163,184,.06)" };
  if (generating || status === "building") {
    return { label: "● 生成中", color: "#ffb3c8", border: "#ec4899", bg: "rgba(236,72,153,.14)" };
  }
  if (status === "ok" || status === "success" || status === "done") {
    return { label: "✓ ready", color: "#22c55e", border: "rgba(34,197,94,.4)", bg: "rgba(34,197,94,.1)" };
  }
  if (status === "failed" || status === "error") {
    return { label: "✕ failed", color: "#ff4d78", border: "rgba(255,77,120,.4)", bg: "rgba(255,77,120,.1)" };
  }
  return dim;
}

function NodeCard({ data }: NodeProps) {
  const d = data as unknown as IdeNode & { isEntry?: boolean };
  const color = KIND_COLOR[d.kind] ?? "#64748b";
  const st = statusBadge(d.status, d.generating);
  const { onOpenCanvas, thumbs } = useContext(NodeUiCtx);
  const thumb = thumbs?.[d.node_id];
  return (
    <div
      style={{
        width: 216,
        border: `1.5px solid ${color}`,
        borderRadius: 14,
        background: "linear-gradient(160deg, rgba(38,44,82,.95) 0%, rgba(20,23,42,.96) 100%)",
        backdropFilter: "blur(6px)",
        padding: "10px 12px",
        color: "#e8e6f5",
        fontSize: 12,
        boxShadow: "0 6px 22px rgba(0,0,0,.45)",
      }}
    >
      <Handle type="target" position={Position.Left} style={{ background: color, width: 9, height: 9, border: "2px solid #101322" }} />
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 6 }}>
        <span style={{ background: color, color: "#0b1120", borderRadius: 6, padding: "1px 7px", fontWeight: 800, fontSize: 9, letterSpacing: 0.5 }}>
          {KIND_LABEL[d.kind] ?? d.kind}
        </span>
        <div style={{ display: "flex", gap: 4, alignItems: "center" }}>
          {d.isEntry ? <span title="入口节点" style={{ color: "#fbbf24", fontSize: 10 }}>▲</span> : null}
          {d.locked ? <span style={{ color: "#94a3b8", fontSize: 10 }}>🔒</span> : null}
          <span style={{ border: `1px solid ${st.border}`, borderRadius: 8, padding: "0 5px", fontSize: 9, background: st.bg, color: st.color }}>
            {st.label}
          </span>
        </div>
      </div>
      <div style={{ fontWeight: 700, fontSize: 13, color: "#f4f2ff" }}>{d.title || d.node_id}</div>
      {d.summary ? (
        <div style={{ color: "#9ca3c8", marginTop: 2, lineHeight: 1.35, maxHeight: 52, overflow: "hidden" }}>{d.summary}</div>
      ) : null}
      {thumb ? (
        <a
          href="#canvas"
          onClick={(ev) => { ev.preventDefault(); ev.stopPropagation(); onOpenCanvas?.(d.node_id); }}
          title="点开节点小画布查看/制作"
          style={{ display: "block", height: 64, marginTop: 6, borderRadius: 8, overflow: "hidden", border: "1px solid rgba(255,255,255,.1)", background: "#0b0a1c", cursor: "pointer" }}
        >
          <img src={thumb} alt="" style={{ width: "100%", height: "100%", objectFit: "cover", display: "block" }} />
        </a>
      ) : null}
      {onOpenCanvas ? (
      <button
        onClick={(ev) => { ev.stopPropagation(); onOpenCanvas(d.node_id); }}
        style={{ marginTop: 8, width: "100%", border: "1px solid rgba(168,139,255,.4)", color: "#c9b8ff", background: "rgba(109,90,224,.14)", borderRadius: 8, padding: "3px 0", fontSize: 10, cursor: "pointer", textAlign: "center" }}
      >🎨 节点小画布</button>
    ) : null}
      <div style={{ marginTop: 7, display: "flex", alignItems: "center", gap: 6, color: "#7d85ad", fontSize: 10 }}>
        <span>💬 {d.choices?.length ?? 0} 选择</span>
        {d.agent ? (
          <span style={{ marginLeft: "auto", display: "inline-flex", alignItems: "center", gap: 3 }}>
            <span style={{ width: 6, height: 6, borderRadius: "50%", background: color }} />
            {d.agent}
            {typeof d.version === "number" ? ` · v${d.version}` : ""}
          </span>
        ) : null}
      </div>
      <Handle type="source" position={Position.Right} style={{ background: color, width: 9, height: 9, border: "2px solid #101322" }} />
    </div>
  );
}

const nodeTypes: NodeTypes = { ide: NodeCard };

export default function IdeCanvas({
  nodes,
  edges,
  onNodesChange,
  onEdgesChange,
  onConnect,
  onNodeClick,
  onPaneClick,
  onOpenCanvas,
  thumbs,
}: {
  nodes: Node<IdeNode>[];
  edges: IdeEdge[];
  onNodesChange?: OnNodesChange;
  onEdgesChange?: OnEdgesChange;
  onConnect?: (c: Connection) => void;
  onNodeClick?: (id: string) => void;
  onPaneClick?: () => void;
  onOpenCanvas?: (id: string) => void;
  thumbs?: Record<string, string>;
}) {
  const nodeUi = useMemo(() => ({ onOpenCanvas, thumbs }), [onOpenCanvas, thumbs]);

  const flowEdges = useMemo<Edge[]>(
    () =>
      edges.map((e) => ({
        id: e.edge_id,
        source: e.source,
        target: e.target,
        label: e.label,
        style: e.edge_id.startsWith("ch-") ? { stroke: "#38bdf8", strokeDasharray: "5 5" } : { stroke: "#6d5ae0" },
        labelStyle: { fill: "#8b93c0", fontSize: 10 },
        markerEnd: { type: MarkerType.ArrowClosed, color: "#a78bfa" },
      })),
    [edges],
  );

  return (
    <NodeUiCtx.Provider value={nodeUi}>
    <ReactFlow
      nodes={nodes}
      edges={flowEdges}
      onNodesChange={onNodesChange}
      onEdgesChange={onEdgesChange}
      onConnect={onConnect}
      onNodeClick={(_, n) => onNodeClick?.(n.id)}
      onPaneClick={() => onPaneClick?.()}
      nodeTypes={nodeTypes}
      fitView
      proOptions={{ hideAttribution: true }}
    >
      <Background variant={BackgroundVariant.Dots} gap={22} size={1.1} color="#3b3660" />
      <Controls />
      <MiniMap pannable zoomable nodeColor={(n) => KIND_COLOR[(n.data as IdeNode).kind] ?? "#64748b"} maskColor="rgba(16,19,34,.7)" />
    </ReactFlow>
    </NodeUiCtx.Provider>
  );
}