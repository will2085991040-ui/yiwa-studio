"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import ReactFlow, {
  Background,
  Controls,
  Handle,
  MarkerType,
  MiniMap,
  Position,
  addEdge,
  useEdgesState,
  useNodesState,
  type Connection,
  type Edge,
  type Node,
  type NodeProps,
  type NodeTypes,
} from "reactflow";
import "reactflow/dist/style.css";
import { authenticatedFetch } from "@/lib/api";

// ---- 领域类型（与后端 app/schemas/story_graph.py 对齐）----
type SChoice = {
  choice_id: string;
  text: string;
  condition: string | null;
  effects: { variable: string; op: string; value: unknown }[];
  next_node: string | null;
};
type SMinigame = {
  game_id: string;
  title: string;
  description: string;
  success_result: string;
  score_variable: string | null;
};
type SNode = {
  node_id: string;
  kind: string;
  title: string;
  summary: string;
  choices: SChoice[];
  minigame?: SMinigame | null;
  position?: { x: number; y: number } | null;
};
type SVariable = { name: string; type: string; initial: unknown; description?: string };
type SGraph = {
  graph_id: string;
  nodes: SNode[];
  edges: { edge_id: string; source: string; target: string; label: string }[];
  variables: SVariable[];
  entry_node_id: string | null;
};

const KIND_LABEL: Record<string, string> = {
  scene: "剧情",
  choice: "选择",
  ending: "结局",
  branch: "分支",
  merge: "汇合",
  minigame: "小游戏",
};
const KIND_COLOR: Record<string, string> = {
  scene: "#38bdf8",
  choice: "#a78bfa",
  ending: "#f472b6",
  branch: "#fbbf24",
  merge: "#34d399",
  minigame: "#f59e0b",
};

function StoryNodeComp({ data }: NodeProps) {
  const color = KIND_COLOR[data.kind] ?? "#64748b";
  return (
    <div
      style={{
        minWidth: 200,
        maxWidth: 260,
        border: `2px solid ${color}`,
        borderRadius: 10,
        background: "#0f172a",
        padding: "10px 12px",
        color: "#e2e8f0",
        fontSize: 12,
        boxShadow: "0 4px 14px rgba(0,0,0,.35)",
      }}
    >
      <Handle type="target" position={Position.Left} style={{ background: color, width: 8, height: 8 }} />
      <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 4 }}>
        <span style={{ background: color, color: "#0b1120", borderRadius: 4, padding: "0 6px", fontWeight: 700 }}>
          {KIND_LABEL[data.kind] ?? data.kind}
        </span>
        {data.isEntry ? <span style={{ color: "#fbbf24" }}>入口</span> : null}
      </div>
      <div style={{ fontWeight: 600 }}>{data.title || data.node_id}</div>
      {data.summary ? <div style={{ color: "#94a3b8", marginTop: 2 }}>{data.summary}</div> : null}
      <div style={{ color: "#64748b", marginTop: 6 }}>选项 {data.choices?.length ?? 0}</div>
      <Handle type="source" position={Position.Right} style={{ background: color, width: 8, height: 8 }} />
    </div>
  );
}

const nodeTypes: NodeTypes = { story: StoryNodeComp };

function uid(prefix: string) {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
}

export default function Editor({ projectId }: { projectId: string }) {
  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  const [graphId, setGraphId] = useState("");
  const [variables, setVariables] = useState<SVariable[]>([]);
  const [entry, setEntry] = useState<string | null>(null);
  const [version, setVersion] = useState(0);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [diag, setDiag] = useState<{ ok: boolean; errors: string[]; warnings: string[] } | null>(null);
  const [saving, setSaving] = useState(false);
  const [fullscreen, setFullscreen] = useState(false);
  // 试玩状态
  const [session, setSession] = useState<{ session_id: string; current_node_id: string; state: Record<string, unknown> } | null>(null);
  const [playChoices, setPlayChoices] = useState<{ choice_id: string; text: string }[]>([]);
  const [playError, setPlayError] = useState("");

  const nodeIds = useMemo(() => nodes.map((n) => n.id), [nodes]);

  // 载入
  useEffect(() => {
    if (!projectId) return;
    authenticatedFetch(`/api/projects/${projectId}/storygraph`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((d) => {
        const g: SGraph = d.graph;
        setVersion(d.version ?? 0);
        setGraphId(g.graph_id ?? "story");
        setEntry(g.entry_node_id ?? null);
        setVariables(g.variables ?? []);
        const ns: Node<SNode & { isEntry?: boolean }>[] = (g.nodes ?? []).map((n, i) => ({
          id: n.node_id,
          type: "story",
          position:
            n.position && typeof n.position.x === "number" && typeof n.position.y === "number"
              ? { x: n.position.x, y: n.position.y }
              : { x: 40 + (i % 4) * 320, y: 80 + Math.floor(i / 4) * 240 },
          data: { ...n, isEntry: g.entry_node_id === n.node_id },
        }));
        setNodes(ns);
        const es: Edge[] = (g.edges ?? []).map((e) => ({
          id: e.edge_id,
          source: e.source,
          target: e.target,
          label: e.label,
          markerEnd: { type: MarkerType.ArrowClosed },
        }));
        (g.nodes ?? []).forEach((n) =>
          (n.choices ?? []).forEach((c) => {
            if (c.next_node) {
              es.push({
                id: `ch-${n.node_id}-${c.choice_id}`,
                source: n.node_id,
                target: c.next_node,
                label: c.text,
                style: { stroke: "#38bdf8", strokeDasharray: "5 5" },
                markerEnd: { type: MarkerType.ArrowClosed },
              });
            }
          }),
        );
        setEdges(es);
      })
      .catch((e) => setDiag({ ok: false, errors: [`载入失败：${String(e?.message ?? e)}`], warnings: [] }));
  }, [projectId, setNodes, setEdges]);

  const onConnect = useCallback(
    (c: Connection) => setEdges((eds) => addEdge({ ...c, markerEnd: { type: MarkerType.ArrowClosed } }, eds)),
    [setEdges],
  );

  const updateNode = (id: string, patch: Partial<SNode>) => {
    setNodes((nds) => nds.map((n) => (n.id === id ? { ...n, data: { ...n.data, ...patch } } : n)));
  };

  const addNode = (kind: string) => {
    const id = uid(kind);
    const title = kind === "ending" ? "新结局" : kind === "minigame" ? "新小游戏" : "新剧情";
    const data: SNode = { node_id: id, kind, title, summary: "", choices: [] };
    if (kind === "minigame") {
      data.minigame = {
        game_id: "click", title: "连点挑战", description: "8 秒内点击 8 次",
        success_result: "success", score_variable: null,
      };
    }
    setNodes((nds) => [
      ...nds,
      {
        id,
        type: "story",
        position: { x: 80 + Math.random() * 200, y: 80 + Math.random() * 200 },
        data,
      },
    ]);
  };

  const addChoice = (nodeId: string) => {
    const id = uid("choice");
    updateNode(nodeId, {
      choices: [
        ...(nodes.find((n) => n.id === nodeId)?.data.choices ?? []),
        { choice_id: id, text: "新选项", condition: null, effects: [], next_node: null },
      ],
    });
  };

  const setChoice = (nodeId: string, ci: number, patch: Partial<SChoice>) => {
    const node = nodes.find((n) => n.id === nodeId);
    if (!node) return;
    const choices = ((node.data.choices as SChoice[]) ?? []).map((c, i) => (i === ci ? { ...c, ...patch } : c));
    updateNode(nodeId, { choices });
  };

  const removeChoice = (nodeId: string, ci: number) => {
    const node = nodes.find((n) => n.id === nodeId);
    if (!node) return;
    updateNode(nodeId, { choices: ((node.data.choices as SChoice[]) ?? []).filter((_, i) => i !== ci) });
  };

  const deleteNode = (nodeId: string) => {
    setNodes((nds) =>
      nds
        .filter((n) => n.id !== nodeId)
        .map((n) => ({
          ...n,
          data: {
            ...n.data,
            choices: ((n.data.choices as SChoice[]) ?? []).filter((c) => c.next_node !== nodeId),
          },
        })),
    );
    setEdges((eds) => eds.filter((e) => e.source !== nodeId && e.target !== nodeId));
    if (selectedId === nodeId) setSelectedId(null);
    if (entry === nodeId) setEntry(null);
  };

  const setMinigame = (nodeId: string, patch: Partial<SMinigame>) => {
    const node = nodes.find((n) => n.id === nodeId);
    if (!node) return;
    const cur = (node.data.minigame as SMinigame | null) ?? {
      game_id: "click", title: "", description: "", success_result: "success", score_variable: null,
    };
    updateNode(nodeId, { minigame: { ...cur, ...patch } });
  };

  const buildGraph = (): SGraph => {
    const storyNodes: SNode[] = nodes.map((n) => ({
      node_id: n.id,
      kind: n.data.kind,
      title: n.data.title,
      summary: n.data.summary,
      minigame: n.data.minigame ?? null,
      position: n.position ? { x: n.position.x, y: n.position.y } : null,
      choices: ((n.data.choices as SChoice[]) ?? []).map((c) => ({
        choice_id: c.choice_id,
        text: c.text,
        condition: c.condition ?? null,
        effects: c.effects ?? [],
        next_node: c.next_node ?? null,
      })),
    }));
    const storyEdges = edges
      .filter((e) => !e.id.startsWith("ch-"))
      .map((e) => ({ edge_id: e.id, source: e.source, target: e.target, label: (e.label as string) ?? "" }));
    return { graph_id: graphId || `story-${projectId}`, nodes: storyNodes, edges: storyEdges, variables, entry_node_id: entry };
  };

  const toBackendNode = (n: Node): SNode => ({
    node_id: n.id,
    kind: n.data.kind,
    title: n.data.title,
    summary: n.data.summary,
    minigame: n.data.minigame ?? null,
    position: n.position ? { x: n.position.x, y: n.position.y } : null,
    choices: ((n.data.choices as SChoice[]) ?? []).map((c) => ({
      choice_id: c.choice_id,
      text: c.text,
      condition: c.condition ?? null,
      effects: c.effects ?? [],
      next_node: c.next_node ?? null,
    })),
  });

  const save = async () => {
    setSaving(true);
    try {
      const graph = {
        graph_id: graphId || `story-${projectId}`,
        nodes: nodes.map(toBackendNode),
        edges: edges
          .filter((e) => !e.id.startsWith("ch-"))
          .map((e) => ({ edge_id: e.id, source: e.source, target: e.target, label: (e.label as string) ?? "" })),
        variables,
        entry_node_id: entry,
      };
      const r = await authenticatedFetch(`/api/projects/${projectId}/storygraph`, {
        method: "PUT",
        body: JSON.stringify({ graph, change_reason: "画布手动编辑" }),
      });
      const data = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(data?.error?.message || data?.detail || `HTTP ${r.status}`);
      setVersion(data.version);
      setDiag({ ok: true, errors: [], warnings: [] });
    } catch (e: any) {
      setDiag({ ok: false, errors: [`保存失败：${String(e?.message ?? e)}`], warnings: [] });
    } finally {
      setSaving(false);
    }
  };

  const validate = async () => {
    try {
      const r = await authenticatedFetch(`/api/projects/${projectId}/storygraph/validate`, {
        method: "POST",
        body: JSON.stringify({ graph: buildGraph() }),
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) setDiag({ ok: false, errors: [JSON.stringify(d)], warnings: [] });
      else setDiag({ ok: d.ok, errors: d.errors ?? [], warnings: d.warnings ?? [] });
    } catch (e: any) {
      setDiag({ ok: false, errors: [`校验失败：${String(e?.message ?? e)}`], warnings: [] });
    }
  };

  const play = async () => {
    setPlayError("");
    try {
      const r = await authenticatedFetch(`/api/projects/${projectId}/runtime/sessions`, { method: "POST" });
      const s = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(s?.error?.message || `HTTP ${r.status}`);
      setSession(s);
      const cr = await authenticatedFetch(`/api/projects/${projectId}/runtime/sessions/${s.session_id}/choices`);
      const cs = await cr.json().catch(() => []);
      setPlayChoices(Array.isArray(cs) ? cs : []);
    } catch (e: any) {
      setPlayError(String(e?.message ?? e));
    }
  };

  const choose = async (choiceId: string) => {
    if (!session) return;
    try {
      const r = await authenticatedFetch(`/api/projects/${projectId}/runtime/sessions/${session.session_id}/choice`, {
        method: "POST",
        body: JSON.stringify({ choice_id: choiceId }),
      });
      const s = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(s?.error?.message || `HTTP ${r.status}`);
      setSession(s);
      const cr = await authenticatedFetch(`/api/projects/${projectId}/runtime/sessions/${session.session_id}/choices`);
      const cs = await cr.json().catch(() => []);
      setPlayChoices(Array.isArray(cs) ? cs : []);
    } catch (e: any) {
      setPlayError(String(e?.message ?? e));
    }
  };

  const selected = nodes.find((n) => n.id === selectedId);
  const currentTitle = useMemo(() => {
    const n = nodes.find((x) => x.id === session?.current_node_id);
    return n?.data?.title ?? session?.current_node_id ?? "";
  }, [nodes, session]);
  const currentMinigame = useMemo(() => {
    const n = nodes.find((x) => x.id === session?.current_node_id);
    if (n?.data?.kind !== "minigame") return null;
    return (n.data.minigame as SMinigame) ?? null;
  }, [nodes, session]);

  const submitGameResult = async (result: string, score?: number) => {
    if (!session) return;
    try {
      const body: { result: string; score?: number; game_id?: string } = { result };
      if (typeof score === "number") body.score = score;
      if (currentMinigame?.game_id) body.game_id = currentMinigame.game_id;
      const r = await authenticatedFetch(`/api/projects/${projectId}/runtime/sessions/${session.session_id}/minigame-result`, {
        method: "POST",
        body: JSON.stringify(body),
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(d?.error?.message || `HTTP ${r.status}`);
      setSession(d.session);
      setPlayChoices(Array.isArray(d.choices) ? d.choices : []);
    } catch (e: any) {
      setPlayError(String(e?.message ?? e));
    }
  };

  useEffect(() => {
    if (!currentMinigame) return;
    const onMsg = (e: MessageEvent) => {
      const d = e.data as { type?: string; result?: string; score?: number };
      if (d && d.type === "funloom:minigame:complete" && d.result) {
        submitGameResult(d.result, typeof d.score === "number" ? d.score : undefined);
      }
    };
    window.addEventListener("message", onMsg);
    return () => window.removeEventListener("message", onMsg);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentMinigame, session, projectId]);

  return (
    <div className={`flex ${fullscreen ? "fixed inset-0 z-50 bg-slate-950" : "h-[calc(100vh-56px)]"}`}>
      {/* 画布 */}
      <div className="flex-1">
        <div className="flex items-center gap-2 border-b border-slate-800 px-4 py-2">
          <button onClick={() => addNode("scene")} className="rounded bg-sky-600 px-3 py-1.5 text-sm hover:bg-sky-500">+ 剧情</button>
          <button onClick={() => addNode("ending")} className="rounded bg-pink-600 px-3 py-1.5 text-sm hover:bg-pink-500">+ 结局</button>
          <button onClick={() => addNode("minigame")} className="rounded bg-amber-600 px-3 py-1.5 text-sm hover:bg-amber-500">+ 小游戏</button>
          <button
            onClick={() => selectedId && setEntry(selectedId)}
            className="rounded bg-amber-600 px-3 py-1.5 text-sm hover:bg-amber-500 disabled:opacity-40"
            disabled={!selectedId}
          >
            设为入口
          </button>
          <button onClick={validate} className="rounded border border-slate-600 px-3 py-1.5 text-sm hover:bg-slate-800">校验</button>
          <button onClick={save} disabled={saving} className="rounded bg-emerald-600 px-3 py-1.5 text-sm hover:bg-emerald-500 disabled:opacity-50">
            {saving ? "保存中…" : "保存"}
          </button>
          <button onClick={play} className="rounded bg-indigo-600 px-3 py-1.5 text-sm hover:bg-indigo-500">试玩</button>
          <a
            href={`/api/projects/${projectId}/storygraph/export.html`}
            target="_blank"
            rel="noreferrer"
            className="rounded bg-teal-600 px-3 py-1.5 text-sm hover:bg-teal-500"
          >
            导出 HTML
          </a>
          <button
            onClick={() => setFullscreen((f) => !f)}
            className="rounded border border-slate-600 px-3 py-1.5 text-sm hover:bg-slate-800"
            title="放大/还原画布"
          >
            {fullscreen ? "✕ 还原" : "⛶ 放大"}
          </button>
          <span className="ml-auto text-xs text-slate-400">版本 v{version}</span>
        </div>
        <div style={{ height: "calc(100% - 45px)" }}>
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            onNodeClick={(_, n) => setSelectedId(n.id)}
            nodeTypes={nodeTypes}
            fitView
            proOptions={{ hideAttribution: true }}
          >
            <Background gap={20} />
            <Controls />
            <MiniMap pannable zoomable nodeColor={(n) => KIND_COLOR[(n.data as SNode).kind] ?? "#64748b"} />
          </ReactFlow>
        </div>
      </div>

      {/* 右栏：检查器 + 变量 + 试玩 */}
      <aside className="w-[360px] overflow-y-auto border-l border-slate-800 bg-slate-900 p-4">
        {diag && (
          <div className={`mb-4 rounded-lg border p-3 text-xs ${diag.ok ? "border-emerald-700 bg-emerald-900/30" : "border-rose-700 bg-rose-900/30"}`}>
            <div className="font-semibold">{diag.ok ? "✓ 校验通过" : "存在错误"}</div>
            {diag.errors.map((e, i) => <div key={i} className="text-rose-300">· {e}</div>)}
            {diag.warnings.map((w, i) => <div key={i} className="text-amber-300">· {w}</div>)}
          </div>
        )}

        <h2 className="mb-2 text-sm font-semibold text-slate-300">节点检查器</h2>
        {selected ? (
          <div className="mb-5 space-y-2 text-sm">
            <div className="rounded border border-slate-700 p-2 text-xs">
              <div className="mb-1 flex items-center justify-between">
                <span className="text-slate-400">节点 {selected.id}</span>
                <button
                  onClick={() => deleteNode(selected.id)}
                  className="rounded bg-rose-700 px-2 py-1 text-xs hover:bg-rose-600"
                >
                  删除节点
                </button>
              </div>
              <div className="text-[10px] text-slate-500">直接拖动画布即可移动位置，保存后自动记住。</div>
            </div>
            <label className="block text-xs text-slate-400">
              类型
              <select value={selected.data.kind} onChange={(e) => updateNode(selected.id, { kind: e.target.value })} className="mt-1 w-full rounded bg-slate-800 px-2 py-1">
                {Object.keys(KIND_LABEL).map((k) => <option key={k} value={k}>{KIND_LABEL[k]}</option>)}
              </select>
            </label>
            <label className="block text-xs text-slate-400">
              标题
              <input value={selected.data.title} onChange={(e) => updateNode(selected.id, { title: e.target.value })} className="mt-1 w-full rounded bg-slate-800 px-2 py-1" />
            </label>
            <label className="block text-xs text-slate-400">
              正文 / 摘要
              <textarea value={selected.data.summary} onChange={(e) => updateNode(selected.id, { summary: e.target.value })} rows={3} className="mt-1 w-full rounded bg-slate-800 px-2 py-1" />
            </label>
            {selected.data.kind === "minigame" && (
              <div className="space-y-2 rounded border border-amber-700/60 p-2">
                <label className="block text-xs text-slate-400">
                  游戏 ID
                  <input value={selected.data.minigame?.game_id ?? "click"} onChange={(e) => setMinigame(selected.id, { game_id: e.target.value })} className="mt-1 w-full rounded bg-slate-800 px-2 py-1" />
                </label>
                <label className="block text-xs text-slate-400">
                  标题
                  <input value={selected.data.minigame?.title ?? ""} onChange={(e) => setMinigame(selected.id, { title: e.target.value })} className="mt-1 w-full rounded bg-slate-800 px-2 py-1" />
                </label>
                <label className="block text-xs text-slate-400">
                  说明
                  <input value={selected.data.minigame?.description ?? ""} onChange={(e) => setMinigame(selected.id, { description: e.target.value })} className="mt-1 w-full rounded bg-slate-800 px-2 py-1" />
                </label>
                <div className="flex items-center gap-2">
                  <label className="block flex-1 text-xs text-slate-400">
                    通过结果
                    <select value={selected.data.minigame?.success_result ?? "success"} onChange={(e) => setMinigame(selected.id, { success_result: e.target.value })} className="mt-1 w-full rounded bg-slate-800 px-2 py-1">
                      <option value="success">success</option>
                      <option value="perfect">perfect</option>
                    </select>
                  </label>
                  <label className="block flex-1 text-xs text-slate-400">
                    得分写入变量
                    <select value={selected.data.minigame?.score_variable ?? ""} onChange={(e) => setMinigame(selected.id, { score_variable: e.target.value || null })} className="mt-1 w-full rounded bg-slate-800 px-2 py-1">
                      <option value="">（无）</option>
                      {variables.map((v) => <option key={v.name} value={v.name}>{v.name}</option>)}
                    </select>
                  </label>
                </div>
              </div>
            )}
            <div className="pt-1">
              <div className="mb-1 flex items-center justify-between text-xs text-slate-400">
                <span>选项（{selected.data.choices?.length ?? 0}）</span>
                <button onClick={() => addChoice(selected.id)} className="rounded bg-slate-700 px-2 py-0.5">+ 添加</button>
              </div>
              {((selected.data.choices as SChoice[]) ?? []).map((c, i) => (
                <div key={c.choice_id} className="mb-2 rounded border border-slate-700 p-2">
                  <input value={c.text} onChange={(e) => setChoice(selected.id, i, { text: e.target.value })} className="mb-1 w-full rounded bg-slate-800 px-2 py-1" />
                  <div className="flex items-center gap-1">
                    <select value={c.next_node ?? ""} onChange={(e) => setChoice(selected.id, i, { next_node: e.target.value || null })} className="flex-1 rounded bg-slate-800 px-2 py-1 text-xs">
                      <option value="">（无去向）</option>
                      {nodeIds.filter((x) => x !== selected.id).map((x) => <option key={x} value={x}>{x}</option>)}
                    </select>
                    <button onClick={() => removeChoice(selected.id, i)} className="rounded bg-rose-700 px-2 py-1 text-xs">删</button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        ) : (
          <p className="mb-5 text-xs text-slate-500">点击画布上的节点进行编辑。</p>
        )}

        <h2 className="mb-2 text-sm font-semibold text-slate-300">变量</h2>
        <div className="mb-5 space-y-2 text-sm">
          {variables.map((v, i) => (
            <div key={v.name} className="flex items-center gap-1">
              <input value={v.name} onChange={(e) => setVariables(vars => vars.map((x, j) => j === i ? { ...x, name: e.target.value } : x))} className="w-24 rounded bg-slate-800 px-2 py-1" />
              <select value={v.type} onChange={(e) => setVariables(vars => vars.map((x, j) => j === i ? { ...x, type: e.target.value } : x))} className="w-24 rounded bg-slate-800 px-1 py-1">
                {["number", "bool", "string", "enum"].map((t) => <option key={t} value={t}>{t}</option>)}
              </select>
              <input
                value={String(v.initial ?? "")}
                onChange={(e) => setVariables(vars => vars.map((x, j) => j === i ? { ...x, initial: e.target.value } : x))}
                className="flex-1 rounded bg-slate-800 px-2 py-1 text-xs"
                placeholder="初始值"
              />
              <button onClick={() => setVariables(vars => vars.filter((_, j) => j !== i))} className="rounded bg-rose-700 px-2 py-1 text-xs">删</button>
            </div>
          ))}
          <button onClick={() => setVariables(vars => [...vars, { name: `var_${vars.length + 1}`, type: "number", initial: 0 }])} className="rounded bg-slate-700 px-2 py-1 text-xs">+ 变量</button>
        </div>

        <h2 className="mb-2 text-sm font-semibold text-slate-300">试玩</h2>
        {session ? (
          <div className="rounded-lg border border-slate-700 p-3 text-sm">
            <div className="mb-1 text-xs text-slate-400">当前节点</div>
            <div className="mb-2 font-semibold text-sky-300">{currentTitle}</div>
            <div className="mb-2 text-xs text-slate-400">变量：{JSON.stringify(session.state)}</div>
            {currentMinigame && (
              <div className="mb-2 rounded border border-amber-700 p-2">
                <div className="mb-1 text-xs font-semibold text-amber-300">小游戏：{currentMinigame.title || currentMinigame.game_id}</div>
                <iframe
                  src={`/minigame?game=${currentMinigame.game_id}&config=${encodeURIComponent(JSON.stringify(currentMinigame))}`}
                  className="h-44 w-full rounded bg-slate-950"
                  title="minigame"
                />
                <div className="mt-1 text-[10px] text-slate-500">完成后自动回传成绩并刷新后续选项。</div>
              </div>
            )}
            {playChoices.length ? (
              <div className="space-y-1">
                {playChoices.map((c) => <button key={c.choice_id} onClick={() => choose(c.choice_id)} className="block w-full rounded bg-indigo-600 px-2 py-1.5 text-left text-xs hover:bg-indigo-500">{c.text}</button>)}
              </div>
            ) : (
              <div className="text-xs text-slate-500">{currentMinigame ? "完成小游戏后出现后续选项。" : "已到达终点或无可选项。"}</div>
            )}
            <button onClick={() => { setSession(null); setPlayChoices([]); }} className="mt-3 rounded border border-slate-600 px-2 py-1 text-xs">结束试玩</button>
          </div>
        ) : (
          <button onClick={play} className="rounded bg-indigo-600 px-3 py-1.5 text-sm hover:bg-indigo-500">从入口开始试玩</button>
        )}
        {playError && <p className="mt-2 text-xs text-rose-400">{playError}</p>}
      </aside>
    </div>
  );
}