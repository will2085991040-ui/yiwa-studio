"use client";

// YIWA 创作 IDE 外壳：顶部工具条 + 左侧项目树 + 中央画布/内容工作区 + 右侧 Inspector + 底部运行。
import { useEffect, useMemo, useRef, useState } from "react";
import dynamic from "next/dynamic";
import { useIde } from "./useGraph";
import Inspector from "./Inspector";
import ContentWorkspace from "./ContentWorkspace";
import VideoPanel from "./VideoPanel";
import AssetsPanel from "./AssetsPanel";
import Playthrough from "./Playthrough";
import ErrorBoundary from "@/components/ErrorBoundary";
import { KIND_COLOR, latestOf, WORKSPACES, type IdeEdge, type WorkspaceKey } from "./workspace";
import { getOrchestration, orchestrateProject, storyOperation, sceneOperation, generateProjectBranchImage } from "@/lib/api";
import { appendAiProgress, clearAiProgress, setAiProgress } from "@/lib/aiProgress";

const Canvas = dynamic(() => import("./Canvas"), {
  ssr: false,
  loading: () => <p className="p-8 text-slate-500">加载画布…</p>,
});

export default function IdePage() {
  const [projectId, setProjectId] = useState("");
  const [workspace, setWorkspace] = useState<WorkspaceKey>("story");
  const [sideOpen, setSideOpen] = useState(true);
  const [bottomOpen, setBottomOpen] = useState(true);
  const [bottomTab, setBottomTab] = useState<"run" | "trace" | "edit">("run");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [videoMode, setVideoMode] = useState(false);
  const [playOpen, setPlayOpen] = useState(false);
  const [posters, setPosters] = useState<Record<string, string>>({}); // node_id -> 该共创分支的海报 image_url（真实验证）
  const [aiInstr, setAiInstr] = useState("");
  const [aiBusy, setAiBusy] = useState(false);
  const [aiMsg, setAiMsg] = useState("");
  const [notif, setNotif] = useState("");
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const flash = (msg: string) => {
    setNotif(msg);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setNotif(""), 2600);
  };

  useEffect(() => {
    setProjectId(new URLSearchParams(window.location.search).get("project") ?? "");
  }, []);

  const ide = useIde({ projectId, flash });

  const canvasEdges: IdeEdge[] = useMemo(
    () => ide.edges.map((e) => ({ edge_id: e.id, source: e.source, target: e.target, label: (e.label as string) ?? "" })),
    [ide.edges],
  );
  const nodeIds = useMemo(() => ide.nodes.map((n) => n.id), [ide.nodes]);
  const latestArts = latestOf(ide.artifacts);

  const selected = ide.nodes.find((n) => n.id === selectedId);
  const selectedMeta = selectedId ? ide.nodeMeta[selectedId] : undefined;

  const onModify = async () => {
    if (!selectedId) return flash("请先在画布上选中一个节点");
    setAiBusy(true);
    setAiMsg("");
    const res = await ide.aiModify(selectedId, aiInstr);
    setAiMsg(res.msg);
    if (res.ok) setAiInstr("");
    setAiBusy(false);
  };

  const saveAll = () => {
    ide.saveGraph();
    ide.reloadArtifacts();
    ide.reloadTraces();
  };

  const [regenerating, setRegenerating] = useState(false);
  const regenerateStory = async () => {
    if (!projectId || regenerating) return;
    setRegenerating(true);
    setAiProgress({ label: "重新生成完整剧情图", detail: "AI 一键重跑流水线，把剧情节点/分支/场景/对白/分镜补齐…", pct: 0 });
    const st = window.setInterval(() => {
      getOrchestration(projectId).then((o) => {
        const steps = o?.steps ?? [];
        const DONE = ["ok", "done", "succeeded", "success"];
        const done = steps.filter((s) => DONE.includes(s.status)).length;
        const pct = steps.length ? Math.round((done / steps.length) * 100) : 0;
        const cur = steps.find((s) => s.status === "running");
        appendAiProgress({ pct, detail: cur ? `正在生成：${cur.label || cur.key}` : `${done}/${steps.length} 个步骤完成` });
      }).catch(() => {});
    }, 900);
    try {
      await orchestrateProject(projectId);
      ide.loadGraph();
      ide.reloadArtifacts();
      ide.reloadTraces();
      ide.reloadChars();
      flash("已重新生成完整剧情图（画布/链接/对白/分镜均已补齐）");
    } catch (e) {
      flash(`重新生成失败：${String((e as Error).message ?? e)}`);
    } finally {
      window.clearInterval(st);
      clearAiProgress();
      setRegenerating(false);
    }
  };

  const countFor = (key: string, charCount: number) => {
    if (key === "characters") return charCount;
    const base = key === "scenes" ? "scene" : key === "dialogues" ? "dialogue" : "world_bible";
    return latestArts.filter((a) => a.kind === base || a.kind.startsWith(base + ":")).length;
  };

  return (
    <div className="fixed inset-0 flex flex-col overflow-hidden bg-[#0c0b1d] text-slate-100">
      {/* 顶部工具条 */}
      <header className="flex h-12 shrink-0 items-center gap-2 border-b border-white/10 bg-[#14162a]/90 px-3">
        <a href="/" className="flex items-center gap-2 font-black">
          <span className="grid h-6 w-6 place-items-center rounded-md bg-gradient-to-br from-[#d90b46] to-accent text-sm text-white">Y</span>
          <span>YIWA</span>
        </a>
        <span className="mx-1 text-slate-600">/</span>
        <span className="truncate text-sm">{ide.projName}</span>
        <span className="rounded-full border border-white/10 bg-panel2 px-2 py-0.5 text-[10px] text-slate-400">● {ide.projStatus}</span>

        <nav className="ml-4 flex items-center gap-0.5">
          {WORKSPACES.map((w) => (
            <button
              key={w.key}
              onClick={() => setWorkspace(w.key as WorkspaceKey)}
              className={`rounded-lg px-2 py-1 text-sm ${workspace === w.key ? "bg-accent/15 text-accent" : "text-slate-300 hover:bg-white/5"}`}
            >
              {w.emoji} {w.label}
            </button>
          ))}
        </nav>

        <div className="ml-auto flex items-center gap-1.5">
          {workspace === "story" && (
            <>
              <button onClick={() => setVideoMode((v) => !v)} className={`rounded-lg border px-2 py-1 text-xs ${videoMode ? "border-accent bg-accent/15 text-accent" : "border-white/10 bg-panel2 hover:bg-white/5"}`}>
                🎬 分镜视频
              </button>
              <button onClick={() => ide.addNode("scene")} className="rounded-lg border border-white/10 bg-panel2 px-2 py-1 text-xs hover:bg-white/5">
                + 剧情
              </button>
            </>
          )}
          <button onClick={saveAll} className="rounded-lg border border-white/10 bg-panel2 px-2.5 py-1 text-xs hover:bg-white/5">保存</button>
          <button onClick={regenerateStory} disabled={regenerating} title="把剧情节点/分支/场景/对白/分镜一键补齐成完整剧情图" className={`rounded-lg border px-2.5 py-1 text-xs hover:bg-white/5 disabled:opacity-50 ${regenerating ? "border-mint/40 text-mint" : "border-white/10 bg-panel2"}`}>{regenerating ? "● 正在补齐完整剧情图…" : "🔁 重新生成"}</button>
          <button onClick={() => setPlayOpen(true)} className="rounded-lg bg-accent/20 px-3 py-1 text-sm font-bold text-accent hover:bg-accent/30">▶ 可视化运行</button>
        </div>
        {notif && (
          <span className="absolute right-3 top-12 z-50 rounded-lg border border-mint/40 bg-panel2 px-3 py-1 text-xs text-mint">{notif}</span>
        )}
      </header>

      <div className="flex min-h-0 flex-1">
        {/* 左侧项目树 */}
        {sideOpen ? (
          <aside className="flex w-52 shrink-0 flex-col overflow-y-auto border-r border-white/10 bg-panel/50 p-2">
            <div className="px-2 py-1 text-[10px] font-bold uppercase tracking-widest text-slate-500">项目</div>
            <div className="mb-2 rounded-lg border border-white/10 bg-panel2 px-2 py-2">
              <div className="text-sm font-bold">{ide.projName}</div>
              <div className="mt-1 flex items-center gap-1 text-[10px] text-slate-400">
                <span className="h-2 w-2 rounded-full bg-emerald-400" /> main · v{ide.graphVersion}
              </div>
            </div>
            <button onClick={() => setSideOpen(false)} className="mb-1 text-right text-[10px] text-slate-600 hover:text-white">›› 收缩</button>

            <div className="px-2 py-1 text-[10px] font-bold uppercase tracking-widest text-slate-500">剧情节点</div>
            <div className="space-y-0.5">
              {ide.nodes.map((n) => (
                <button
                  key={n.id}
                  onClick={() => { setSelectedId(n.id); setWorkspace("story"); }}
                  className={`flex w-full items-center gap-1.5 rounded-md px-1.5 py-1 text-left text-xs ${selectedId === n.id ? "bg-accent/15 text-accent" : "text-slate-300 hover:bg-white/5"}`}
                >
                  <span style={{ width: 8, height: 8, borderRadius: 3, background: KIND_COLOR[n.data.kind] ?? "#64748b" }} />
                  <span className="truncate">{n.data.title || n.id}</span>
                </button>
              ))}
              {ide.nodes.length === 0 && <p className="px-1 text-[10px] text-slate-600">暂无剧情节点，进入画布按「+ 剧情」</p>}
            </div>

            <div className="mt-3 px-2 py-1 text-[10px] font-bold uppercase tracking-widest text-slate-500">内容</div>
            {WORKSPACES.filter((w) => w.key !== "story" && w.key !== "run" && w.key !== "assets").map((w) => (
              <button key={w.key} onClick={() => setWorkspace(w.key as WorkspaceKey)} className="flex w-full items-center justify-between rounded-md px-2 py-1 text-left text-xs text-slate-300 hover:bg-white/5">
                <span>{w.label}</span>
                <span className="text-[10px] text-slate-500">{countFor(w.key, ide.chars.length)}</span>
              </button>
            ))}

            <div className="mt-3 px-2 py-1 text-[10px] font-bold uppercase tracking-widest text-slate-500">运行</div>
            <button onClick={() => setBottomOpen(true)} className="flex w-full items-center justify-between rounded-md px-2 py-1 text-left text-xs text-slate-300 hover:bg-white/5">
              <span>运行时 / 变量</span><span className="text-[10px] text-slate-500">●</span>
            </button>
          </aside>
        ) : (
          <button onClick={() => setSideOpen(true)} className="w-5 shrink-0 self-start border-r border-white/10 py-2 text-center text-[10px] text-slate-500 hover:text-white">›</button>
        )}

        {/* 中央 */}
        <main className="min-w-0 flex-1">
          <ErrorBoundary name="画布/内容工作区">
            {workspace === "assets" ? (
              <AssetsPanel />
            ) : workspace === "story" ? (
              videoMode && selectedId ? (
              <VideoPanel
                projectId={projectId}
                nodeId={selectedId}
                nodeTitle={selected?.data.title ?? selectedId}
                nodeKind={selected?.data.kind ?? "scene"}
                choices={selected?.data.choices ?? []}
                nodeNameOf={(id) => ide.nodes.find((n) => n.id === id)?.data.title || id}
                onPickNode={(id) => id && setSelectedId(id)}
                onUpdateChoice={(nid, cid, patch) => ide.updateChoice(nid, cid, patch)}
              />
            ) : (
              <div className="h-full">
                <Canvas
                  nodes={ide.nodes}
                  edges={canvasEdges}
                  onNodesChange={ide.onNodesChange}
                  onEdgesChange={ide.onEdgesChange}
                  onConnect={ide.onConnect}
                  onNodeClick={(id) => setSelectedId(id)}
                  onPaneClick={() => setSelectedId(null)}
                />
              </div>
            )
          ) : (
            <ContentWorkspace
              key={workspace}
              kind={workspace}
              artifacts={ide.artifacts}
              chars={ide.chars}
              projectId={projectId}
              onSaved={() => { ide.reloadArtifacts(); ide.reloadTraces(); flash("已保存并生成新版本"); }}
              onAddNode={(k) => { ide.addNode(k); flash(k === "scene" ? "已新增场景节点" : "已新增对白选择节点"); }}
              onDeleteNode={(kind, nodeId) => {
                const art = ide.artifacts.find((a) => a.kind.includes(`:${nodeId}`));
                if (art) {
                  // 节点删除会连带其内容制品失去 is_latest 视图；版本库仍保留历史
                  void art;
                }
                ide.deleteNode(nodeId);
                ide.reloadArtifacts();
                flash("已删除节点（旧版本仍保留）");
              }}
            />
          )}
          </ErrorBoundary>
        </main>

        {/* 右侧 Inspector */}
        <aside className="flex w-[330px] shrink-0 flex-col overflow-y-auto border-l border-white/10 bg-panel/50">
          <ErrorBoundary name="右侧检查器">
          {workspace === "story" ? (
            <Inspector
              node={selected?.data}
              nodeId={selectedId}
              meta={selectedMeta}
              nodeIds={nodeIds}
              aiInstr={aiInstr}
              setAiInstr={setAiInstr}
              aiBusy={aiBusy}
              aiMsg={aiMsg}
              onUpdate={ide.updateNode}
              onModify={onModify}
              onRerun={selectedId ? () => ide.rerunSelected(selectedId) : () => flash("请先选中节点")}
              onDelete={selectedId ? () => { ide.deleteNode(selectedId); setSelectedId(null); } : undefined}
              onEntry={selectedId ? () => { ide.setEntry(selectedId); flash("已设为入口"); } : undefined}
              onAddChoice={selectedId ? () => ide.addChoice(selectedId) : undefined}
              onDeleteChoice={selectedId ? (cid) => ide.deleteChoice(selectedId, cid) : undefined}
              chars={ide.chars}
              onInsert={
                selectedId
                  ? (target, text) => {
                      const n = ide.nodes.find((x) => x.id === selectedId);
                      if (!n) return;
                      if (target === "title") ide.updateNode(selectedId, { title: (n.data.title || "") + text });
                      else ide.updateNode(selectedId, { summary: (n.data.summary || "") + text });
                      flash("已插入角色参照");
                    }
                  : undefined
              }
            />
          ) : (
            <div className="flex-1 overflow-y-auto p-3 text-xs text-slate-500">
              在左侧「内容」中打开某项，用右侧可视化表单编辑；保存会生成新版本并保留旧版本。
            </div>
          )}
          </ErrorBoundary>
        </aside>
      </div>

      {/* 底部面板 */}
      {bottomOpen && (
        <footer className="flex h-44 shrink-0 flex-col border-t border-white/10 bg-[#14162a]/90">
          <ErrorBoundary name="底部面板">
          <div className="flex h-8 items-center gap-1 border-b border-white/10 px-2">
            {([["run", "运行 / 变量"], ["trace", "Agent 轨迹"], ["edit", "可视化手动编辑"]] as const).map(([k, l]) => (
              <button key={k} onClick={() => setBottomTab(k)} className={`rounded-md px-2 py-0.5 text-xs ${bottomTab === k ? "bg-accent/15 text-accent" : "text-slate-400 hover:bg-white/5"}`}>{l}</button>
            ))}
            <button onClick={() => setBottomOpen(false)} className="ml-auto text-slate-500 hover:text-white">▼ 收起</button>
          </div>
          <div className="flex-1 overflow-y-auto px-3 py-2 text-xs">
            {bottomTab === "run" && (
              <div className="grid h-full grid-cols-2 gap-3">
                <div>
                  <div className="mb-1 font-semibold text-slate-300">交互变量</div>
                  <div className="flex flex-wrap gap-1.5">
                    {ide.variables.length === 0 && <span className="text-slate-500">暂无变量</span>}
                    {ide.variables.map((v) => (
                      <span key={v.name} className="rounded-full border border-white/10 bg-panel px-2 py-0.5 text-slate-300">{v.name} <span className="text-slate-500">: {String(v.initial)}</span></span>
                    ))}
                  </div>
                </div>
                <div>
                  <div className="mb-1 font-semibold text-slate-300">试玩会话</div>
                  {ide.play ? (
                    <pre className="whitespace-pre-wrap rounded-md bg-panel p-2 text-[11px] text-slate-300">{JSON.stringify(ide.play.state, null, 2)}</pre>
                  ) : (
                    <p className="text-slate-500">尚未运行 · 点顶部「▶ 试玩」</p>
                  )}
                  {ide.playErr && <p className="mt-1 text-accent">{ide.playErr}</p>}
                </div>
              </div>
            )}
            {bottomTab === "trace" && (
              <div className="space-y-1.5">
                {ide.traces.length === 0 && <p className="text-slate-500">暂未运行 Agent · 生成 / 保存后这里会出现真实轨迹</p>}
                {ide.traces.slice(0, 8).map((t) => (
                  <details key={t.id} className="rounded-md bg-panel px-2 py-1">
                    <summary className="flex gap-2">
                      <span className="text-glow">{t.kind}</span>
                      <span className={t.status === "ok" ? "text-mint" : "text-accent"}>{t.status}</span>
                      <span className="text-slate-500">{new Date(t.started_at).toLocaleTimeString()}</span>
                    </summary>
                    {(t.steps ?? []).map((s) => (
                      <div key={s.id} className="ml-1 border-l border-accent/30 pl-2 text-[11px] text-slate-400">
                        #{s.seq} <span className="text-slate-200">{s.agent}</span> · {s.step_key} · 耗时{s.latency_ms}ms
                      </div>
                    ))}
                  </details>
                ))}
              </div>
            )}
            {bottomTab === "edit" && (
              <div>
                <div className="mb-1 font-semibold text-slate-300">可视化手动编辑</div>
                <div className="grid grid-cols-2 gap-1.5">
                  {latestArts.length === 0 && <p className="text-slate-500">暂无已生成内容</p>}
                  {latestArts.slice(0, 12).map((a) => (
                    <div key={a.id} className="flex items-center justify-between rounded-md bg-panel px-2 py-1">
                      <span className="truncate">{(a.content?.title as string) || (a.content?.name as string) || a.kind}</span>
                      <span className="text-[10px] text-slate-500">· {a.kind} · v{a.version}</span>
                    </div>
                  ))}
                </div>
                <p className="mt-1 text-slate-500">在「剧情」或左侧内容选中后，右侧 / 内容工作区即可可视化修改，保存生成新版本。</p>
              </div>
            )}
          </div>
          </ErrorBoundary>
        </footer>
      )}

      <Playthrough
        open={playOpen}
        projectId={projectId}
        nodes={ide.nodes.map((n) => n.data)}
        entryNodeId={ide.entry}
        variables={ide.variables}
        onClose={() => setPlayOpen(false)}
        nodeTitleOf={(id) => ide.nodes.find((n) => n.id === id)?.data.title || id}
        onOpenBranch={async (instruction, anchorNodeId) => {
          const before = new Set(ide.nodes.map((n) => n.id));
          flash("AI 正在创建开放分支…");
          await storyOperation(projectId, "branch", instruction, anchorNodeId);
          await ide.loadGraph();
          // 找到刚新增的分支节点（kind=scene 且标题=指令）
          const added = ide.nodes.find((n) => !before.has(n.id) && n.data.kind === "scene" && n.data.title === instruction);
          if (!added) return null;
          const nodeId = added.id;
          // AI 生文：按该走向自由扩写完整场景（真实 Agent 编排）
          await sceneOperation(projectId, "expand", nodeId, "请围绕这条玩家书写的走向自由展开完整场景、对白与情绪。")
            .then(() => ide.loadGraph())
            .catch(() => {});
          // AI 生图：为这条分支生成一张关键帧海报（真实媒体生成），并显示为分支缩略图
          const imgRes = await generateProjectBranchImage(projectId, `互动影视剧情分支关键帧：${instruction}`)
            .catch(() => null);
          const posterUrl =
            imgRes?.image_url ?? imgRes?.url ?? (Array.isArray(imgRes?.images) ? imgRes.images[0] : undefined) ?? (typeof imgRes?.content === "string" && imgRes.content.startsWith("data:") ? imgRes.content : undefined);
          if (posterUrl) setPosters((p) => ({ ...p, [nodeId]: posterUrl }));
          // 锁定：创作者（玩家不可再编辑，交由 AI/共创管理）
          ide.updateNode(nodeId, { locked: true });
          await ide.saveGraph();
          ide.reloadArtifacts();
          flash("已完成开放分支（锁定，AI 管理）");
          return nodeId;
        }}
        onEditChoices={async (nid, ntitle, choices) => {
          try {
            ide.updateNode(nid, { choices: choices });
            await ide.saveGraph();
            ide.reloadArtifacts();
            flash(`已保存「${ntitle || nid}」的 ${choices.length} 个选项（含各自出现时间）`);
            return true;
          } catch (e) {
            flash(`保存失败：${String((e as Error).message ?? e)}`);
            return false;
          }
        }}
        posters={posters}
      />
    </div>
  );
}