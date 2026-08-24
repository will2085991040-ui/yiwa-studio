"use client";

// YIWA 项目工作台：Director 规划 + Orchestrator 执行流水线 + Artifacts + 修改/局部执行 + 轨迹
import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import TopNav from "@/components/TopNav";
import {
  chat,
  dialogueOperation,
  getArtifactHistory,
  getDirectorPlan,
  getHealth,
  getOrchestration,
  getStorygraphCheck,
  getTraces,
  createCharacter,
  deleteCharacter,
  editArtifactContent,
  getCharacter,
  listCharacters,
  orchestrateProject,
  updateCharacter,
  rerunTask,
  reviseArtifact,
  sceneOperation,
  storyOperation,
} from "@/lib/api";
import type { StorygraphCheck } from "@/lib/api";
import type { Health } from "@/lib/api";
import type {
  AgentRunOut,
  ArtifactOut,
  CharacterCardContent,
  DialogueContent,
  DirectorPlanView,
  Orchestration,
  RelationshipGraphContent,
  SceneContent,
  StoryGraphContent,
  WorldBibleContent,
} from "@/types";

const STATUS_STYLE: Record<string, string> = {
  pending: "bg-panel2 text-slate-500",
  ready: "bg-glow/10 text-glow",
  running: "bg-accent/20 text-accent",
  succeeded: "bg-mint/20 text-mint",
  failed: "bg-accent/30 text-accent",
  blocked: "bg-amber-500/15 text-amber-400",
  skipped: "bg-slate-600/30 text-slate-400",
  done: "bg-mint/20 text-mint",
};

const REVISABLE = ["world_bible", "character_card", "relationship_graph", "story_graph"];
const RERUNNABLE = ["world", "character", "relationship", "plot"];

// Funloom「7 步闭环」映射：一站式生成按序跑完，最后一步编译/质检收尾并汇总剧本书
const PIPELINE_STAGES: { agent: string; icon: string; label: string }[] = [
  { agent: "world", icon: "🌍", label: "世界观" },
  { agent: "character", icon: "👤", label: "角色卡" },
  { agent: "relationship", icon: "🔗", label: "关系图" },
  { agent: "plot", icon: "🗺️", label: "剧情图" },
  { agent: "scene", icon: "🎬", label: "场景" },
  { agent: "dialogue", icon: "💬", label: "对白" },
  { agent: "finalize", icon: "📦", label: "编译质检" },
];
const TERMINAL_STATUSES = new Set(["succeeded", "skipped"]);

export default function AgentPage() {
  const [id, setId] = useState("");
  const [plan, setPlan] = useState<DirectorPlanView | null>(null);
  const [orchestration, setOrchestration] = useState<Orchestration | null>(null);
  const [history, setHistory] = useState<ArtifactOut[]>([]);
  const [traces, setTraces] = useState<AgentRunOut[]>([]);
  const [messages, setMessages] = useState<{ role: "user" | "agent"; text: string }[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [reviseKind, setReviseKind] = useState("character_card");
  const [reviseInstruction, setReviseInstruction] = useState("");
  const [revising, setRevising] = useState(false);
  const [rerunning, setRerunning] = useState<string | null>(null);
  const [storyInstruction, setStoryInstruction] = useState("");
  const [storying, setStorying] = useState(false);
  const [sceneNodeId, setSceneNodeId] = useState("");
  const [sceneInstruction, setSceneInstruction] = useState("");
  const [sceneing, setSceneing] = useState(false);
  const [dialogueNodeId, setDialogueNodeId] = useState("");
  const [dialogueChoiceId, setDialogueChoiceId] = useState<string | null>(null);
  const [dialogueInstruction, setDialogueInstruction] = useState("");
  const [dialogueing, setDialogueing] = useState(false);
  const [orchestrating, setOrchestrating] = useState(false);
  const [check, setCheck] = useState<StorygraphCheck | null>(null);
  const [checking, setChecking] = useState(false);
  const [health, setHealth] = useState<Health | null>(null);
  const [roster, setRoster] = useState<{ character_id: string; name: string; role: string }[]>([]);

  useEffect(() => {
    const project = new URLSearchParams(window.location.search).get("project") ?? "";
    setId(project);
  }, []);

  useEffect(() => {
    getHealth().then(setHealth).catch(() => {});
  }, []);

  const refresh = async () => {
    getOrchestration(id).then(setOrchestration).catch(() => {});
    getTraces(id).then(setTraces).catch(() => {});
    if (id) listCharacters(id).then(setRoster).catch(() => {});
    return getArtifactHistory(id).then(setHistory).catch(() => {});
  };

  useEffect(() => {
    if (!id) return;
    getDirectorPlan(id).then(setPlan).catch(() => {});
    void refresh();
  }, [id]);

  const send = async () => {
    if (!input.trim() || busy) return;
    setBusy(true);
    setMessages((m) => [...m, { role: "user", text: input.trim() }]);
    try {
      const out = await chat(id, input.trim());
      setMessages((m) => [...m, { role: "agent", text: out.reply }]);
      getTraces(id).then(setTraces).catch(() => {});
      setInput("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "发送失败");
    } finally {
      setBusy(false);
    }
  };

  const doRevise = async () => {
    if (!reviseInstruction.trim() || revising) return;
    setRevising(true);
    try {
      await reviseArtifact(id, reviseKind, reviseInstruction.trim());
      setReviseInstruction("");
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "修改失败");
    } finally {
      setRevising(false);
    }
  };

  const doRerun = async (taskId: string) => {
    if (rerunning) return;
    setRerunning(taskId);
    try {
      await rerunTask(id, taskId);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "局部执行失败");
    } finally {
      setRerunning(null);
    }
  };

  const doStoryOp = async (operation: "extend" | "branch") => {
    if (!storyInstruction.trim() || storying) return;
    setStorying(true);
    try {
      await storyOperation(id, operation, storyInstruction.trim());
      setStoryInstruction("");
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "剧情操作失败");
    } finally {
      setStorying(false);
    }
  };

  const doSceneOp = async (nodeId: string, operation: "generate" | "revise" | "expand") => {
    if (!nodeId || sceneing) return;
    if ((operation === "revise" || operation === "expand") && !sceneInstruction.trim()) return;
    setSceneing(true);
    try {
      await sceneOperation(id, operation, nodeId, sceneInstruction.trim());
      setSceneInstruction("");
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "场景操作失败");
    } finally {
      setSceneing(false);
    }
  };

  const doDialogueOp = async (
    nodeId: string,
    choiceId: string | null,
    operation: "generate" | "revise" | "expand",
  ) => {
    if (!nodeId || dialogueing) return;
    if ((operation === "revise" || operation === "expand") && !dialogueInstruction.trim()) return;
    setDialogueing(true);
    try {
      await dialogueOperation(id, operation, nodeId, choiceId, dialogueInstruction.trim());
      setDialogueInstruction("");
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "对白操作失败");
    } finally {
      setDialogueing(false);
    }
  };

  const doOrchestrate = async () => {
    if (orchestrating) return;
    setOrchestrating(true);
    setError("");
    // 同步 POST 运行期间，轮询 GET 状态刷新步骤与进度 → 进度条随 step.progress 前进。
    const timer = window.setInterval(() => {
      getOrchestration(id).then(setOrchestration).catch(() => {});
    }, 900);
    try {
      await orchestrateProject(id);
      await refresh();
      // 闭环收尾后自动质检，并把问题清单直接带回画布
      setCheck(await getStorygraphCheck(id));
    } catch (e) {
      setError(e instanceof Error ? e.message : "一键生成失败");
    } finally {
      window.clearInterval(timer);
      setOrchestrating(false);
      await refresh();
    }
  };

  const doCheck = async () => {
    if (checking) return;
    setChecking(true);
    try {
      setCheck(await getStorygraphCheck(id));
    } catch (e) {
      setError(e instanceof Error ? e.message : "质检失败");
    } finally {
      setChecking(false);
    }
  };

  const steps = orchestration?.steps ?? [];
  const succeededCount = steps.filter((s) => s.status === "succeeded").length;
  const doneCount = steps.filter((s) => TERMINAL_STATUSES.has(s.status)).length;
  const loopComplete = steps.length > 0 && steps.every((s) => TERMINAL_STATUSES.has(s.status));
  const stageStatus = new Map<string, string>();
  steps.forEach((s) => stageStatus.set(s.agent, s.status));
  // 实时进度：已完成步骤记 1，运行中按其内部扇出进度折算，pending 记 0 → 全局条平滑推进。
  const runningStep = steps.find((s) => s.status === "running");
  // 运行中步骤的中文名：优先取 7 步阶段名，回退到后端 label / agency。
  const runningProgressLabel = runningStep
    ? (PIPELINE_STAGES.find((p) => p.agent === runningStep.agent)?.label ?? runningStep.label ?? runningStep.agent)
    : "";
  const progressTotal = steps.length || 7;
  const liveProgress = steps.length
    ? Math.max(
        0,
        Math.min(
          100,
          Math.round(
            (steps.reduce((acc, s) => {
              if (s.status === "succeeded" || s.status === "skipped") return acc + 1;
              if (s.status === "running" && s.progress?.total) return acc + s.progress.done / s.progress.total;
              return acc;
            }, 0) /
              progressTotal) *
              100
          )
        )
      )
    : 0;
  const worldArtifact = orchestration?.artifacts.find((a) => a.kind === "world_bible");
  const world = (worldArtifact?.content ?? {}) as Partial<WorldBibleContent>;
  const characterArtifacts = (orchestration?.artifacts ?? []).filter((a) => a.kind.startsWith("character_card"));
  const relationshipArtifacts = (orchestration?.artifacts ?? []).filter((a) => a.kind === "relationship_graph");
  const storyArtifacts = (orchestration?.artifacts ?? []).filter((a) => a.kind === "story_graph");
  const storyGraph = storyArtifacts[0];
  const charName = new Map<string, string>();
  characterArtifacts.forEach((a) => {
    const c = a.content as Partial<CharacterCardContent>;
    if (c.character_id) charName.set(c.character_id, c.name ?? c.character_id);
  });
  const sceneNodeIds = (((storyGraph?.content as unknown as StoryGraphContent | undefined)?.nodes) ?? [])
    .filter((n) => n.kind === "scene" || n.kind === "branch")
    .map((n) => n.node_id);
  const sceneArtifacts = (orchestration?.artifacts ?? []).filter((a) => a.kind.startsWith("scene:"));
  const dialogueNodes = (((storyGraph?.content as unknown as StoryGraphContent | undefined)?.nodes) ?? [])
    .filter((n) => n.kind === "scene" || n.kind === "branch");
  const dialogueArtifacts = (orchestration?.artifacts ?? []).filter((a) => a.kind.startsWith("dialogue:"));
  const dialogueChoicesOf = (nodeId: string) =>
    dialogueNodes.find((n) => n.node_id === nodeId)?.choices ?? [];

  return (
    <>
      <TopNav projectId={id}>
        <a
          href={`/portraits?project=${id}`}
          className="text-sm rounded-lg border border-fuchsia-500/40 bg-fuchsia-500/10 px-3 py-1 text-fuchsia-300 hover:bg-fuchsia-500/20"
        >
          角色立绘
        </a>
        <a
          href={`/storygraph?project=${id}`}
          className="text-sm rounded-lg border border-sky-500/40 bg-sky-500/10 px-3 py-1 text-sky-300 hover:bg-sky-500/20"
        >
          剧情画布
        </a>
        <a
          href={`/storyboard?project=${id}`}
          className="text-sm rounded-lg border border-violet-500/40 bg-violet-500/10 px-3 py-1 text-violet-300 hover:bg-violet-500/20"
        >
          分镜视频
        </a>
        <a
          href={`/worldplay?project=${id}`}
          className="text-sm rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-1 text-amber-300 hover:bg-amber-500/20"
        >
          世界试玩
        </a>
      </TopNav>
      <main className="min-h-screen px-6 py-8">
      <div className="mx-auto flex max-w-7xl gap-6 items-start">
        <aside className="w-64 shrink-0 sticky top-20 hidden lg:block space-y-4">
          <div className="rounded-2xl bg-panel border border-white/10 p-4">
            <div className="text-xs text-slate-500">当前作品</div>
            <div className="font-bold mt-1 truncate">{(plan?.agent_plan?.goal ?? "…").slice(0, 40)}</div>
            <div className="mt-3 grid grid-cols-2 gap-2 text-xs">
              <div className="rounded-lg bg-panel2 border border-white/10 p-2">
                <div className="text-[10px] uppercase text-slate-500">类型</div>
                <div className="text-glow">{plan?.agent_plan?.project_type ?? "-"}</div>
              </div>
              <div className="rounded-lg bg-panel2 border border-white/10 p-2">
                <div className="text-[10px] uppercase text-slate-500">状态</div>
                <div>{orchestration?.status ?? "planning"}</div>
              </div>
            </div>
          </div>

          <div className="rounded-2xl bg-panel border border-white/10 p-4">
            <div className="flex items-center justify-between mb-1">
              <div className="text-xs text-slate-500">7 步闭环一键生成</div>
              <span className={`text-[10px] font-bold rounded px-1.5 py-0.5 ${
                loopComplete ? "bg-mint/15 text-mint" : steps.length ? "bg-accent/15 text-accent" : "bg-panel2 text-slate-500"
              }`}>
                {loopComplete ? "◉ 闭环完成" : steps.length ? "◌ 生成中" : "未开始"}
              </span>
            </div>
            <div className="mt-2 grid grid-cols-7 gap-1">
              {PIPELINE_STAGES.map((st) => {
                const status = stageStatus.get(st.agent) ?? "pending";
                const cls =
                  status === "succeeded" ? "border-mint/50 bg-mint/10 text-mint"
                  : status === "running" ? "border-accent/60 bg-accent/15 text-accent animate-pulse"
                  : status === "skipped" ? "border-slate-600/50 bg-slate-600/10 text-slate-500"
                  : status === "failed" ? "border-rose-500/50 bg-rose-500/10 text-rose-400"
                  : "border-white/10 bg-panel2 text-slate-600";
                return (
                  <div key={st.agent} className={`rounded-lg border p-1.5 text-center ${cls}`} title={`${st.label}: ${status}`}>
                    <div className="text-sm leading-none">{st.icon}</div>
                    <div className="mt-1 text-[9px] leading-tight">{st.label}</div>
                    <div className="text-[9px] opacity-80">{status === "succeeded" ? "✓" : status === "running" ? "…" : status === "pending" ? "·" : status === "skipped" ? "≡" : "✕"}</div>
                  </div>
                );
              })}
            </div>
            <div className="mt-2 flex items-baseline justify-between text-sm">
              <span className="font-bold text-glow">{doneCount}/{steps.length || 7}</span>
              <span className="text-[10px] text-slate-500">
                {runningStep?.progress
                  ? `${runningStep.agent} ${runningStep.progress.label}`
                  : `${succeededCount} 成功 · 末步编译质检`}
              </span>
            </div>
            <div className="mt-1.5 h-2 rounded-full bg-panel2 overflow-hidden">
              <div
                className="h-full bg-gradient-to-r from-[#d90b46] to-accent transition-all duration-700"
                style={{ width: `${steps.length ? liveProgress : 0}%` }}
              />
            </div>
            {/* 运行中步骤的子进度条：长链 scene/dialogue 扇出时逐节点推进 */}
            {runningStep?.progress && (
              <div className="mt-2">
                <div className="mb-0.5 flex items-center justify-between text-[10px] text-slate-400">
                  <span className="truncate">{runningProgressLabel}</span>
                  <span className="tabular-nums">{runningStep.progress.pct}%</span>
                </div>
                <div className="h-1 rounded-full bg-panel2 overflow-hidden">
                  <div
                    className="h-full bg-accent/80 transition-all duration-500"
                    style={{ width: `${runningStep.progress.pct}%` }}
                  />
                </div>
              </div>
            )}
            <button
              onClick={doOrchestrate}
              disabled={orchestrating}
              className="mt-3 w-full rounded-lg bg-gradient-to-r from-[#d90b46] to-accent px-3 py-2 text-sm font-bold text-white disabled:opacity-40"
            >
              {orchestrating ? "生成中…" : loopComplete ? "↻ 一键重新生成" : "▶ 一键生成互动游戏"}
            </button>
          </div>

          <div className="rounded-2xl bg-panel border border-white/10 p-4">
            <div className="text-xs text-slate-500 mb-2">快捷入口</div>
            <div className="space-y-2">
              <a href={`/ide?project=${id}`} className="block rounded-lg bg-accent/15 border border-accent/40 px-3 py-2 text-sm font-bold text-accent hover:bg-accent/25">✏ 进入 IDE 编辑器（修改 & 可视化）</a>
              <a href={`/storygraph?project=${id}`} className="block rounded-lg bg-sky-500/10 border border-sky-500/30 px-3 py-2 text-sm text-sky-300 hover:bg-sky-500/20">🎨 剧情画布</a>
              <a href={`/portraits?project=${id}`} className="block rounded-lg bg-fuchsia-500/10 border border-fuchsia-500/30 px-3 py-2 text-sm text-fuchsia-300 hover:bg-fuchsia-500/20">🖼 角色立绘</a>
              <a href={`/storyboard?project=${id}`} className="block rounded-lg bg-violet-500/10 border border-violet-500/30 px-3 py-2 text-sm text-violet-300 hover:bg-violet-500/20">🎬 分镜视频</a>
              <a href={`/worldplay?project=${id}`} className="block rounded-lg bg-amber-500/10 border border-amber-500/30 px-3 py-2 text-sm text-amber-300 hover:bg-amber-500/20">🧭 世界试玩</a>
              <a href={`/api/projects/${id}/storygraph/export.html`} target="_blank" className="block rounded-lg bg-white/5 border border-white/10 px-3 py-2 text-sm text-slate-300 hover:bg-white/10">📤 导出 HTML</a>
              <button onClick={doCheck} className="w-full text-left rounded-lg bg-white/5 border border-white/10 px-3 py-2 text-sm text-slate-300 hover:bg-white/10">
                {checking ? "🔍 质检中…" : "🔍 一键质检"}
              </button>
            </div>
          </div>

          {check && (
            <div className="rounded-2xl bg-panel border border-white/10 p-4">
              <div className="flex items-center justify-between mb-1">
                <span className="text-sm font-bold">{check.ok ? "✓ 质检通过" : "⚠ 质检问题清单"}</span>
                <span className="text-[10px] text-slate-500">v{check.version}</span>
              </div>
              <div className="text-[11px] text-slate-500 mb-2">
                {check.counts.nodes} 节点 · {check.counts.edges} 边 · {check.counts.endings} 结局 · {check.counts.variables} 变量
              </div>
              {check.errors.length > 0 && (
                <div className="mb-2">
                  <div className="text-[11px] font-bold text-accent mb-1">错误（{check.errors.length}）</div>
                  {check.errors.map((e) => (
                    <div key={e} className="text-xs text-accent mt-0.5">✕ {e}</div>
                  ))}
                </div>
              )}
              {check.warnings.length > 0 && (
                <div>
                  <div className="text-[11px] font-bold text-amber-300 mb-1">警告（{check.warnings.length}）</div>
                  {check.warnings.map((w) => (
                    <div key={w} className="text-xs text-amber-200/90 mt-0.5">△ {w}</div>
                  ))}
                </div>
              )}
              {check.errors.length === 0 && check.warnings.length === 0 && (
                <div className="text-xs text-mint">故事图结构完整，无错误与警告。</div>
              )}
            </div>
          )}
        </aside>

        <div className="flex-1 min-w-0">
        <h1 className="text-2xl font-bold mb-6">项目工作台</h1>

        {health && health.llm_mode === "mock" && (
          <div className={`mb-4 flex items-center gap-2 rounded-xl border px-4 py-3 text-sm ${
            health.llm_fallback
              ? "border-amber-500/40 bg-amber-500/10 text-amber-200"
              : "border-white/10 bg-panel text-slate-400"
          }`}>
            <span>{health.llm_fallback ? "⚠" : "ⓘ"}</span>
            <span>{health.llm_fallback ? "当前 LLM 配置无效，已回退离线演示：" : "当前为离线演示模式（mock 产出）。"}</span>
            <span className="font-medium">{health.llm_note}</span>
            <a href="/settings" className="ml-auto shrink-0 rounded bg-white/10 px-2.5 py-1 text-xs hover:bg-white/20">
              前往设置
            </a>
          </div>
        )}

        {error && <p className="mb-4 text-sm text-accent">{error}</p>}

        {plan && (
          <section className="mb-6 rounded-2xl bg-panel border border-white/10 p-6">
            <div className="flex items-center justify-between mb-2">
              <h2 className="font-bold">Director 规划</h2>
              <span className="text-xs text-slate-500">{plan.prompt_version} · {plan.provider}/{plan.model}</span>
            </div>
            <p className="text-sm text-slate-300 mb-4 whitespace-pre-wrap">{plan.agent_plan.goal}</p>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4 text-sm">
              <div><div className="text-[10px] uppercase text-slate-500">Project Type</div>{plan.agent_plan.project_type}</div>
              <div><div className="text-[10px] uppercase text-slate-500">Genre</div>{plan.agent_plan.genre}</div>
              <div><div className="text-[10px] uppercase text-slate-500">Tone</div>{plan.agent_plan.tone}</div>
              <div><div className="text-[10px] uppercase text-slate-500">Target Audience</div>{plan.agent_plan.target_audience}</div>
            </div>
            {plan.agent_plan.success_metrics.length > 0 && (
              <div className="flex flex-wrap gap-2">
                {plan.agent_plan.success_metrics.map((m) => (
                  <span key={m} className="text-xs rounded-full bg-mint/10 text-mint px-3 py-1">{m}</span>
                ))}
              </div>
            )}
          </section>
        )}

        {/* Production Pipeline：Orchestrator 真实执行状态（7 步闭环） */}
        <section className="mb-6 rounded-2xl bg-panel border border-white/10 p-6">
          <h2 className="font-bold mb-1">Production Pipeline · 7 步闭环</h2>
          <p className="text-xs text-slate-500 mb-4">
            Orchestrator 执行 · {doneCount}/{steps.length || 7} 步完成{loopComplete ? "（闭环已收尾，剧本书已编译）" : ""} · 状态：{orchestration?.status ?? "-"}
          </p>
          {steps.length === 0 && <p className="text-sm text-slate-600">尚未执行（等待编排）</p>}
          <ol className="space-y-1.5">
            {steps.map((s, i) => (
              <li key={s.key} className="flex items-start gap-3 text-sm">
                <span className={`w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold ${STATUS_STYLE[s.status] ?? "bg-panel2 text-slate-500"}`}>
                  {s.status === "succeeded" ? "✓" : s.status === "running" ? "…" : i + 1}
                </span>
                <div className="flex-1">
                  <span className="font-mono text-glow">{s.key}</span>{" "}
                  <span className={s.status === "pending" ? "text-slate-400" : "text-white"}>{s.label}</span>
                  {s.dependencies.length > 0 && (
                    <span className="ml-2 text-xs text-slate-500">依赖：{s.dependencies.join(", ")}</span>
                  )}
                  <div className="text-xs text-slate-500">{s.description}</div>
                  {s.reason && <div className="text-xs text-slate-500 mt-0.5">↳ {s.reason}</div>}
                </div>
                <span className={`text-[10px] uppercase rounded px-2 py-0.5 ${STATUS_STYLE[s.status] ?? ""}`}>{s.status}</span>
                {s.status === "succeeded" && RERUNNABLE.includes(s.agent) && (
                  <button
                    onClick={() => doRerun(s.key)}
                    disabled={rerunning !== null}
                    className="text-[10px] rounded bg-panel2 border border-white/10 px-2 py-0.5 text-slate-400 hover:text-white disabled:opacity-40"
                  >
                    {rerunning === s.key ? "…" : "↻ 重跑"}
                  </button>
                )}
              </li>
            ))}
          </ol>
        </section>

        {/* Interactive Creation Layer：用户修改 + 版本历史 */}
        <section className="mb-6 rounded-2xl bg-panel border border-white/10 p-4">
          <h3 className="text-sm font-bold mb-2">修改内容（生成新版本，旧版本保留）</h3>
          <div className="flex gap-2">
            <select
              value={reviseKind}
              onChange={(e) => setReviseKind(e.target.value)}
              className="rounded-xl bg-panel2 border border-white/10 px-3 py-2 text-sm outline-none"
            >
              {REVISABLE.map((k) => (
                <option key={k} value={k}>
                  {kindLabel(k)}
                </option>
              ))}
            </select>
            <input
              value={reviseInstruction}
              onChange={(e) => setReviseInstruction(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && doRevise()}
              placeholder="修改要求，如：让女主更加傲娇"
              className="flex-1 rounded-xl bg-panel2 border border-white/10 px-3 py-2 text-sm outline-none focus:border-accent"
            />
            <button
              onClick={doRevise}
              disabled={revising || !reviseInstruction.trim()}
              className="rounded-xl bg-glow/20 text-glow px-4 text-sm font-bold disabled:opacity-40"
            >
              {revising ? "…" : "修改"}
            </button>
          </div>
          {history.length > 0 && (
            <div className="mt-3 flex flex-wrap gap-2">
              {history.map((h) => (
                <span key={h.id} className="text-[11px] rounded bg-panel2 border border-white/10 px-2 py-1 text-slate-400">
                  {h.kind}·v{h.version}
                  <span className={h.source === "user" ? "text-glow" : "text-slate-500"}>
                    {" "}{h.source === "user" ? "用户" : "Agent"}
                  </span>
                  {!h.is_latest && <span className="text-slate-600"> 旧</span>}
                </span>
              ))}
            </div>
          )}
        </section>

        {/* 手动编辑：生成的东西都能改（结构化 JSON，schema 校验后落新版本） */}
        <ManualEditPanel projectId={id} artifacts={orchestration?.artifacts ?? []} onDone={refresh} />

        {/* WorldBible Artifact：WorldAgent 的结构化产出 */}
        {worldArtifact && (
          <section className="mb-6 rounded-2xl bg-panel border border-white/10 p-6">
            <div className="flex items-center justify-between mb-3">
              <h2 className="font-bold">WorldBible</h2>
              <span className="text-xs text-slate-500">{worldArtifact.prompt_version} · {worldArtifact.agent}</span>
            </div>
            <ArtifactMeta a={worldArtifact} />
            <h3 className="text-lg font-semibold text-glow mb-1">{world.title}</h3>
            <p className="text-sm text-slate-300 mb-4">{world.setting}</p>
            <div className="grid grid-cols-2 md:grid-cols-3 gap-3 text-sm mb-4">
              <div><div className="text-[10px] uppercase text-slate-500">world_id</div>{world.world_id}</div>
              <div><div className="text-[10px] uppercase text-slate-500">Era</div>{world.era || "-"}</div>
              <div><div className="text-[10px] uppercase text-slate-500">Location</div>{world.location || "-"}</div>
              <div><div className="text-[10px] uppercase text-slate-500">Social Structure</div>{world.social_structure || "-"}</div>
              <div><div className="text-[10px] uppercase text-slate-500">Culture</div>{world.culture || "-"}</div>
              <div><div className="text-[10px] uppercase text-slate-500">Technology</div>{world.technology || "-"}</div>
            </div>
            {((world.rules?.length ?? 0) > 0) && <FieldList title="Rules" items={world.rules!} />}
            {((world.conflicts?.length ?? 0) > 0) && <FieldList title="Conflicts" items={world.conflicts!} />}
            {((world.world_constraints?.length ?? 0) > 0) && <FieldList title="World Constraints" items={world.world_constraints!} />}
            {((world.factions?.length ?? 0) > 0) && (
              <div className="mb-3">
                <h4 className="text-[10px] uppercase tracking-widest text-slate-500 mb-1">Factions</h4>
                <div className="flex flex-wrap gap-2">
                  {world.factions!.map((f) => (
                    <span key={f.name} className="text-xs rounded-lg bg-panel2 border border-white/10 px-3 py-1.5">
                      <span className="text-accent">{f.name}</span>
                      <span className="text-slate-500"> · {f.role || f.description}</span>
                    </span>
                  ))}
                </div>
              </div>
            )}
            {((world.key_locations?.length ?? 0) > 0) && (
              <div className="mb-3">
                <h4 className="text-[10px] uppercase tracking-widest text-slate-500 mb-1">Key Locations</h4>
                <div className="flex flex-wrap gap-2">
                  {world.key_locations!.map((l) => (
                    <span key={l.name} className="text-xs rounded-lg bg-panel2 border border-white/10 px-3 py-1.5">
                      <span className="text-glow">{l.name}</span>
                      <span className="text-slate-500"> · {l.description}</span>
                    </span>
                  ))}
                </div>
              </div>
            )}
            {world.consistency_notes && (
              <p className="text-xs text-slate-500">一致性备注：{world.consistency_notes}</p>
            )}
          </section>
        )}

        {/* CharacterCard Artifacts：CharacterAgent 的结构化产出（支持手动新增/编辑/删除） */}
        <CharacterWorkspace
          projectId={id}
          roster={roster}
          characterArtifacts={characterArtifacts}
          onChanged={() => refresh()}
        />

        {/* RelationshipGraph Artifact：RelationshipAgent 的互动关系输出 */}
        {relationshipArtifacts.length > 0 && (
          <section className="mb-6 rounded-2xl bg-panel border border-white/10 p-6">
            <div className="flex items-center justify-between mb-3">
              <h2 className="font-bold">角色关系图（{relationshipArtifacts.length}）</h2>
              <span className="text-xs text-slate-500">{relationshipArtifacts[0].prompt_version}</span>
            </div>
            {relationshipArtifacts.map((a) => (
              <div key={a.id}>
                <ArtifactMeta a={a} />
                <RelationshipGraphView g={a.content as unknown as RelationshipGraphContent} charName={charName} />
              </div>
            ))}
          </section>
        )}

        {/* StoryGraph Artifact：PlotAgent 的互动剧情图 + 延长/分支操作 */}
        {storyGraph && (
          <section className="mb-6 rounded-2xl bg-panel border border-white/10 p-6">
            <div className="flex items-center justify-between mb-3">
              <h2 className="font-bold">互动剧情图（StoryGraph）</h2>
              <span className="text-xs text-slate-500">{storyGraph.prompt_version}</span>
            </div>
            <ArtifactMeta a={storyGraph} />
            <StoryGraphView g={storyGraph.content as unknown as StoryGraphContent} />
            <div className="mt-4 border-t border-white/10 pt-4">
              <p className="text-xs text-slate-500 mb-2">剧情操作（生成新版本，旧版本保留）：</p>
              <div className="flex gap-2">
                <input
                  value={storyInstruction}
                  onChange={(e) => setStoryInstruction(e.target.value)}
                  placeholder="如：在女主发现男主欺骗后，再发展三场"
                  className="flex-1 rounded-xl bg-panel2 border border-white/10 px-4 py-2 text-sm outline-none focus:border-accent"
                />
                <button
                  onClick={() => doStoryOp("extend")}
                  disabled={storying}
                  className="rounded-xl bg-accent px-4 text-sm font-bold disabled:opacity-40"
                >
                  延长剧情
                </button>
                <button
                  onClick={() => doStoryOp("branch")}
                  disabled={storying}
                  className="rounded-xl bg-glow/20 border border-glow/40 text-glow px-4 text-sm font-bold disabled:opacity-40"
                >
                  增加分支
                </button>
              </div>
            </div>
          </section>
        )}

        {/* Scene 局部工作台（Step 11）：按节点生成/修改/扩写场景，不含对白 */}
        {storyGraph && (
          <section className="mb-6 rounded-2xl bg-panel border border-white/10 p-6">
            <div className="flex items-center justify-between mb-3">
              <h2 className="font-bold">场景工作台（Scene）</h2>
              <span className="text-xs text-slate-500">按选定节点局部生成 · 不含对白</span>
            </div>
            <div className="flex flex-wrap gap-2 mb-3">
              <select
                value={sceneNodeId || sceneNodeIds[0] || ""}
                onChange={(e) => setSceneNodeId(e.target.value)}
                className="rounded-xl bg-panel2 border border-white/10 px-3 py-2 text-sm outline-none"
              >
                {sceneNodeIds.map((n) => (
                  <option key={n} value={n}>{n}</option>
                ))}
              </select>
              <input
                value={sceneInstruction}
                onChange={(e) => setSceneInstruction(e.target.value)}
                placeholder="对选定场景的要求（修改/扩写必填），如：改成暧昧的雨夜"
                className="flex-1 min-w-[200px] rounded-xl bg-panel2 border border-white/10 px-4 py-2 text-sm outline-none focus:border-accent"
              />
            </div>
            <div className="flex gap-2">
              <button
                onClick={() => doSceneOp(sceneNodeId || sceneNodeIds[0] || "", "generate")}
                disabled={sceneing || !(sceneNodeId || sceneNodeIds[0])}
                className="rounded-xl bg-accent px-4 text-sm font-bold disabled:opacity-40"
              >
                生成场景
              </button>
              <button
                onClick={() => doSceneOp(sceneNodeId || sceneNodeIds[0] || "", "revise")}
                disabled={sceneing || !sceneInstruction.trim()}
                className="rounded-xl bg-glow/20 border border-glow/40 text-glow px-4 text-sm font-bold disabled:opacity-40"
              >
                修改
              </button>
              <button
                onClick={() => doSceneOp(sceneNodeId || sceneNodeIds[0] || "", "expand")}
                disabled={sceneing || !sceneInstruction.trim()}
                className="rounded-xl bg-mint/10 border border-mint/40 text-mint px-4 text-sm font-bold disabled:opacity-40"
              >
                扩写
              </button>
            </div>
            {sceneArtifacts.length > 0 && (
              <div className="mt-4 border-t border-white/10 pt-4 grid grid-cols-1 md:grid-cols-2 gap-4">
                {sceneArtifacts.map((a) => (
                  <div key={a.id}>
                    <ArtifactMeta a={a} />
                    <SceneView s={a.content as unknown as SceneContent} />
                  </div>
                ))}
              </div>
            )}
          </section>
        )}

        {/* Dialogue 局部工作台（Step 12）：按 (node_id, choice_id) 生成/修改/扩写对白 */}
        {storyGraph && (
          <section className="mb-6 rounded-2xl bg-panel border border-white/10 p-6">
            <div className="flex items-center justify-between mb-3">
              <h2 className="font-bold">对白工作台（Dialogue）</h2>
              <span className="text-xs text-slate-500">按 (节点, 选择) 局部生成 · 声明式条件/效果</span>
            </div>
            <div className="flex flex-wrap gap-2 mb-3">
              <select
                value={dialogueNodeId || dialogueNodes[0]?.node_id || ""}
                onChange={(e) => {
                  setDialogueNodeId(e.target.value);
                  setDialogueChoiceId(null);
                }}
                className="rounded-xl bg-panel2 border border-white/10 px-3 py-2 text-sm outline-none"
              >
                {dialogueNodes.map((n) => (
                  <option key={n.node_id} value={n.node_id}>{n.node_id}</option>
                ))}
              </select>
              <select
                value={dialogueChoiceId ?? ""}
                onChange={(e) => setDialogueChoiceId(e.target.value || null)}
                className="rounded-xl bg-panel2 border border-white/10 px-3 py-2 text-sm outline-none"
              >
                <option value="">默认/开场对白</option>
                {dialogueChoicesOf(dialogueNodeId || dialogueNodes[0]?.node_id || "").map((c) => (
                  <option key={c.choice_id} value={c.choice_id}>{c.choice_id} · {c.text}</option>
                ))}
              </select>
              <input
                value={dialogueInstruction}
                onChange={(e) => setDialogueInstruction(e.target.value)}
                placeholder="对白要求（修改/扩写必填），如：让女主的台词更傲娇"
                className="flex-1 min-w-[200px] rounded-xl bg-panel2 border border-white/10 px-4 py-2 text-sm outline-none focus:border-accent"
              />
            </div>
            <div className="flex gap-2">
              <button
                onClick={() => doDialogueOp(dialogueNodeId || dialogueNodes[0]?.node_id || "", dialogueChoiceId, "generate")}
                disabled={dialogueing || !(dialogueNodeId || dialogueNodes[0]?.node_id)}
                className="rounded-xl bg-accent px-4 text-sm font-bold disabled:opacity-40"
              >
                生成对白
              </button>
              <button
                onClick={() => doDialogueOp(dialogueNodeId || dialogueNodes[0]?.node_id || "", dialogueChoiceId, "revise")}
                disabled={dialogueing || !dialogueInstruction.trim()}
                className="rounded-xl bg-glow/20 border border-glow/40 text-glow px-4 text-sm font-bold disabled:opacity-40"
              >
                修改
              </button>
              <button
                onClick={() => doDialogueOp(dialogueNodeId || dialogueNodes[0]?.node_id || "", dialogueChoiceId, "expand")}
                disabled={dialogueing || !dialogueInstruction.trim()}
                className="rounded-xl bg-mint/10 border border-mint/40 text-mint px-4 text-sm font-bold disabled:opacity-40"
              >
                扩写
              </button>
            </div>
            {dialogueArtifacts.length > 0 && (
              <div className="mt-4 border-t border-white/10 pt-4 grid grid-cols-1 md:grid-cols-2 gap-4">
                {dialogueArtifacts.map((a) => (
                  <div key={a.id}>
                    <ArtifactMeta a={a} />
                    <DialogueView d={a.content as unknown as DialogueContent} />
                  </div>
                ))}
              </div>
            )}
          </section>
        )}

        {/* 运行台（草稿期真实响应） */}
        <section className="rounded-2xl bg-panel border border-white/10 p-6 mb-6">
          <h2 className="font-bold mb-1">Run Agent</h2>
          <p className="text-xs text-slate-500 mb-4">可发送消息验证 Runtime 与 Trace 链路（互动能力随 Phase 接入）</p>
          <div className="min-h-[160px] max-h-[260px] overflow-auto space-y-2 mb-3">
            {messages.length === 0 && <p className="text-sm text-slate-600">试着发一句消息…</p>}
            {messages.map((m, i) => (
              <div key={i} className={`text-sm rounded-xl p-3 ${m.role === "user" ? "bg-panel2 ml-8" : "bg-accent/10 mr-8"}`}>
                <div className="text-[10px] uppercase text-slate-500 mb-1">{m.role === "user" ? "你" : "Agent"}</div>
                <div className="whitespace-pre-wrap">{m.text}</div>
              </div>
            ))}
          </div>
          <div className="flex gap-2">
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && send()}
              placeholder="输入消息…"
              className="flex-1 rounded-xl bg-panel2 border border-white/10 px-4 py-2 text-sm outline-none focus:border-accent"
            />
            <button onClick={send} disabled={busy} className="rounded-xl bg-accent px-5 text-sm font-bold disabled:opacity-40">
              {busy ? "…" : "发送"}
            </button>
          </div>
        </section>

        {/* Traces：真实轨迹 */}
        <section className="rounded-2xl bg-panel border border-white/10 p-6">
          <h2 className="font-bold mb-3">运行轨迹（{traces.length} 次）</h2>
          {traces.length === 0 && <p className="text-sm text-slate-600">暂无轨迹</p>}
          <div className="space-y-3">
            {traces.map((run) => (
              <details key={run.id} className="rounded-xl bg-panel2 border border-white/5 p-3">
                <summary className="text-sm cursor-pointer flex items-center gap-3">
                  <span className="text-glow font-mono">{run.kind}</span>
                  <span className="text-xs text-slate-500">{new Date(run.started_at).toLocaleString()}</span>
                  <span className={`text-xs ${run.status === "ok" ? "text-mint" : "text-accent"}`}>{run.status}</span>
                  <span className="ml-auto text-xs text-slate-600">{run.steps.length} 步</span>
                </summary>
                <div className="mt-3 space-y-2">
                  {run.steps.map((s) => (
                    <div key={s.id} className="text-xs border-l-2 border-accent/40 pl-3">
                      <div className="flex gap-2">
                        <span className="font-mono text-glow">#{s.seq}</span>
                        <span>{s.agent}</span>
                        <span className="text-slate-500">· {s.step_key}</span>
                        <span className="text-slate-600">· 耗时 {s.latency_ms} ms</span>
                      </div>
                      <details>
                        <summary className="text-slate-500 cursor-pointer">输入/输出</summary>
                        <pre className="mt-1 text-[11px] text-slate-400 overflow-auto">{JSON.stringify(
                          { input: s.input_data || {}, output: s.output_data || {} },
                          null,
                          2
                        )}</pre>
                      </details>
                    </div>
                  ))}
                </div>
              </details>
            ))}
          </div>
        </section>
        </div>
      </div>
      </main>
    </>
  );
}

function FieldList({ title, items }: { title: string; items: string[] }) {
  return (
    <div className="mb-3">
      <h4 className="text-[10px] uppercase tracking-widest text-slate-500 mb-1">{title}</h4>
      <ul className="space-y-0.5">
        {items.map((it) => (
          <li key={it} className="text-sm text-slate-300">· {it}</li>
        ))}
      </ul>
    </div>
  );
}

function ArtifactMeta({ a }: { a: ArtifactOut }) {
  return (
    <div className="flex flex-wrap items-center gap-1.5 text-[11px] text-slate-500 mb-2">
      <span className="rounded bg-panel2 border border-white/10 px-2 py-0.5">v{a.version}</span>
      <span className={`rounded px-2 py-0.5 ${a.source === "user" ? "bg-glow/10 text-glow" : "bg-accent/10 text-accent"}`}>
        {a.source === "user" ? "用户修改" : "Agent 生成"}
      </span>
      {a.parent_version != null && <span>← v{a.parent_version}</span>}
      {a.change_reason && <span className="text-slate-400">「{a.change_reason}」</span>}
    </div>
  );
}

function Chip({ label, value }: { label: string; value: string }) {
  return (
    <span className="text-xs rounded-lg bg-panel2 border border-white/10 px-3 py-1.5">
      <span className="text-slate-500">{label}</span>
      <span className="text-accent"> {value}</span>
    </span>
  );
}

function CharacterWorkspace({
  projectId,
  roster,
  characterArtifacts,
  onChanged,
}: {
  projectId: string;
  roster: { character_id: string; name: string; role: string }[];
  characterArtifacts: ArtifactOut[];
  onChanged: () => void;
}) {
  const seedBy = new Map<string, CharacterCardContent>();
  characterArtifacts.forEach((a) => {
    const c = a.content as unknown as CharacterCardContent;
    if (c.character_id) seedBy.set(c.character_id, c);
  });
  return (
    <section className="mb-6 rounded-2xl bg-panel border border-white/10 p-6">
      <div className="flex items-center justify-between mb-3">
        <h2 className="font-bold">角色卡（{roster.length}）</h2>
        <span className="text-xs text-slate-500">可手动新增 / 编辑 / 删除，生成的内容也能改</span>
      </div>
      {roster.length === 0 ? (
        <p className="text-sm text-slate-500">还没有角色。可以先运行流水线生成，或用下方按钮手动添加。</p>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {roster.map((r) => (
            <CharacterCardEditor
              key={r.character_id}
              projectId={projectId}
              characterId={r.character_id}
              seed={seedBy.get(r.character_id)}
              onChanged={onChanged}
            />
          ))}
        </div>
      )}
    </section>
  );
}

function CharacterCardEditor({
  projectId,
  characterId,
  seed,
  onChanged,
}: {
  projectId: string;
  characterId: string;
  seed?: CharacterCardContent;
  onChanged: () => void;
}) {
  const [form, setForm] = useState<CharacterCardContent>(
    () =>
      seed ?? {
        character_id: characterId, name: characterId, role: "",
        age: "", gender: "", appearance: "", personality: [],
        background: "", motivation: "", goal: "", conflict: "", fear: "", secret: "",
        relationship_rules: [], speech_style: { tone: "", formality: "", catchphrases: [], quirks: [] },
        likes: [], dislikes: [], hidden_information: [], character_arc: [], possible_endings: [],
      },
  );
  const [loaded, setLoaded] = useState(Boolean(seed));
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");

  useEffect(() => {
    if (loaded) return;
    getCharacter(projectId, characterId)
      .then((res) => {
        if (res.card) setForm((f) => ({ ...f, ...(res.card as unknown as CharacterCardContent) }));
      })
      .catch(() => {})
      .finally(() => setLoaded(true));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, characterId, loaded]);

  const set = <K extends keyof CharacterCardContent>(key: K, value: CharacterCardContent[K]) =>
    setForm((f) => ({ ...f, [key]: value }));
  const setList = (key: "personality" | "likes" | "dislikes" | "relationship_rules", v: string) =>
    set(key, v.split(/[,\n]/).map((x) => x.trim()).filter(Boolean));

  const save = async () => {
    setBusy(true);
    setMsg("");
    try {
      await updateCharacter(projectId, characterId, form, "手动编辑角色");
      setDirty(false);
      setMsg("已保存");
      onChanged();
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "保存失败");
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    setBusy(true);
    try {
      await deleteCharacter(projectId, characterId);
      onChanged();
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "删除失败");
      setBusy(false);
    }
  };

  const input = (key: "name" | "role" | "age" | "gender" | "appearance") => (
    <input
      className="rounded-xl bg-panel2 border border-white/10 px-3 py-1.5 text-sm outline-none w-full"
      value={form[key]}
      onChange={(e) => { set(key, e.target.value); setDirty(true); }}
    />
  );

  return (
    <article className="rounded-xl bg-panel2 border border-white/5 p-4 flex flex-col">
      <div className="flex items-center justify-between mb-2 gap-2">
        <div className="min-w-0">
          <div className="text-xs text-slate-500 uppercase mb-1">{characterId}</div>
          <input
            className="rounded-lg bg-transparent border border-white/10 px-2 py-1 font-semibold text-glow outline-none w-full"
            value={form.name}
            onChange={(e) => { set("name", e.target.value); setDirty(true); }}
          />
        </div>
        <div className="flex gap-2 shrink-0">
          <button
            onClick={save}
            disabled={busy}
            className="text-xs rounded-lg bg-mint/20 text-mint px-3 py-1.5 hover:bg-mint/30 disabled:opacity-50"
          >
            {busy ? "保存中…" : dirty ? "● 保存" : "保存"}
          </button>
          <button
            onClick={remove}
            disabled={busy}
            className="text-xs rounded-lg bg-accent/20 text-accent px-3 py-1.5 hover:bg-accent/30 disabled:opacity-50"
          >
            删除
          </button>
        </div>
      </div>

      <div className="space-y-2.5">
        <div className="grid grid-cols-3 gap-2">
          <label className="text-[11px] text-slate-500">身份定位 {input("role")}</label>
          <label className="text-[11px] text-slate-500">性别 {input("gender")}</label>
          <label className="text-[11px] text-slate-500">年龄 {input("age")}</label>
        </div>
        <Field label="外貌特征"><input className={inp} value={form.appearance} onChange={(e) => { set("appearance", e.target.value); setDirty(true); }} /></Field>
        <Field label="背景故事">
          <textarea className={inp + " min-h-[64px]"} value={form.background} onChange={(e) => { set("background", e.target.value); setDirty(true); }} />
        </Field>
        <div className="grid grid-cols-2 gap-2">
          <Field label="动机"><textarea className={inp + " min-h-[52px]"} value={form.motivation} onChange={(e) => { set("motivation", e.target.value); setDirty(true); }} /></Field>
          <Field label="目标"><textarea className={inp + " min-h-[52px]"} value={form.goal} onChange={(e) => { set("goal", e.target.value); setDirty(true); }} /></Field>
        </div>
        <div className="grid grid-cols-2 gap-2">
          <Field label="冲突"><textarea className={inp + " min-h-[52px]"} value={form.conflict} onChange={(e) => { set("conflict", e.target.value); setDirty(true); }} /></Field>
          <Field label="秘密"><textarea className={inp + " min-h-[52px]"} value={form.secret} onChange={(e) => { set("secret", e.target.value); setDirty(true); }} /></Field>
        </div>
        <Field label="性格标签（逗号或换行分隔）">
          <input className={inp} value={form.personality.join("，")} onChange={(e) => { setList("personality", e.target.value); setDirty(true); }} />
        </Field>
        <Field label="喜欢"><input className={inp} value={form.likes.join("，")} onChange={(e) => { setList("likes", e.target.value); setDirty(true); }} /></Field>
        <Field label="厌恶"><input className={inp} value={form.dislikes.join("，")} onChange={(e) => { setList("dislikes", e.target.value); setDirty(true); }} /></Field>
      </div>
      {msg && <p className="text-xs text-mint mt-2">{msg}</p>}
    </article>
  );
}

const inp =
  "rounded-xl bg-panel2 border border-white/10 px-3 py-1.5 text-sm outline-none w-full";

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block text-[11px] text-slate-500">
      {label}
      <div className="mt-1">{children}</div>
    </label>
  );
}

function CharacterCardView({ c }: { c: CharacterCardContent }) {
  return (
    <article className="rounded-xl bg-panel2 border border-white/5 p-4">
      <div className="flex items-baseline justify-between mb-1">
        <h3 className="font-semibold text-glow">{c.name}</h3>
        <span className="text-[10px] uppercase text-slate-500">{c.character_id}</span>
      </div>
      <div className="text-xs text-slate-400 mb-3">
        {c.role} · {c.gender || "-"} · {c.age || "-"} 岁
      </div>
      {c.personality.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mb-3">
          {c.personality.map((p) => (
            <span key={p} className="text-xs rounded-full bg-accent/10 text-accent px-2.5 py-0.5">{p}</span>
          ))}
        </div>
      )}
      {c.appearance && <Psy label="外貌" v={c.appearance} />}
      {c.background && <Psy label="背景" v={c.background} />}
      {c.motivation && <Psy label="动机" v={c.motivation} />}
      {c.goal && <Psy label="目标" v={c.goal} />}
      {c.conflict && <Psy label="冲突" v={c.conflict} />}
      {c.fear && <Psy label="恐惧" v={c.fear} />}
      {c.secret && <Psy label="秘密" v={c.secret} />}
      {c.speech_style.tone && (
        <div className="text-xs text-slate-400 mb-3">
          对白：{c.speech_style.tone}
          {c.speech_style.formality ? ` · ${c.speech_style.formality}` : ""}
        </div>
      )}
      {((c.likes.length ?? 0) > 0) && (
        <div className="flex flex-wrap gap-1.5 mb-2">
          {c.likes.map((x) => <Chip key={x} label="喜" value={x} />)}
        </div>
      )}
      {((c.dislikes.length ?? 0) > 0) && (
        <div className="flex flex-wrap gap-1.5 mb-2">
          {c.dislikes.map((x) => <Chip key={x} label="恶" value={x} />)}
        </div>
      )}
      {((c.relationship_rules.length ?? 0) > 0) && (
        <div className="flex flex-wrap gap-1.5 mb-2">
          {c.relationship_rules.map((x) => <Chip key={x} label="关系" value={x} />)}
        </div>
      )}
      {((c.hidden_information.length ?? 0) > 0) && <FieldList title="隐藏信息" items={c.hidden_information} />}
      {((c.character_arc.length ?? 0) > 0) && <FieldList title="角色弧光" items={c.character_arc} />}
      {((c.possible_endings.length ?? 0) > 0) && <FieldList title="可达结局" items={c.possible_endings} />}
    </article>
  );
}

function Psy({ label, v }: { label: string; v: string }) {
  return (
    <div className="text-xs mb-2">
      <span className="text-slate-500">{label}：</span>
      <span className="text-slate-300">{v}</span>
    </div>
  );
}

function RelationshipGraphView({ g, charName }: { g: RelationshipGraphContent; charName: Map<string, string> }) {
  const name = (id: string) => charName.get(id) ?? id;
  return (
    <div>
      <div className="flex flex-wrap gap-2 mb-3">
        {g.characters.map((cid) => (
          <span key={cid} className="text-xs rounded-full bg-accent/10 text-accent px-3 py-1">
            {name(cid)} <span className="text-slate-500">({cid})</span>
          </span>
        ))}
      </div>
      {g.edges.length === 0 ? (
        <p className="text-sm text-slate-500">暂无关系边（当前仅单角色，多角色关系边随多张角色卡生成）。</p>
      ) : (
        <ul className="space-y-2">
          {g.edges.map((e) => (
            <li key={e.edge_id} className="rounded-xl bg-panel2 border border-white/5 p-3">
              <div className="flex items-center gap-2 text-sm">
                <span className="text-slate-200">{name(e.source_character)}</span>
                <span className="text-glow">—{e.relationship_type}→</span>
                <span className="text-slate-200">{name(e.target_character)}</span>
              </div>
              <div className="flex gap-3 mt-1 text-xs text-slate-400">
                <span>好感 {e.affection}</span>
                <span>信任 {e.trust}</span>
                <span>敌意 {e.hostility}</span>
              </div>
              {e.possible_changes.length > 0 && (
                <div className="mt-2 text-xs">
                  <span className="text-slate-500">玩家选择效果：</span>
                  {e.possible_changes.map((pc, i) => (
                    <div key={i} className="text-slate-400 ml-1">
                      「{pc.trigger}」 → {pc.effects.map((f) => `${f.variable} ${f.op} ${f.value}`).join("，")}
                      {pc.resulting_branch ? ` → ${pc.resulting_branch}` : ""}
                    </div>
                  ))}
                </div>
              )}
              {e.relationship_arc.length > 0 && <FieldList title="关系弧光" items={e.relationship_arc} />}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function StoryGraphView({ g }: { g: StoryGraphContent }) {
  const kindLabel: Record<string, string> = {
    scene: "场景", choice: "选择", ending: "结局", branch: "分支", merge: "合并",
  };
  return (
    <div>
      <div className="flex flex-wrap gap-2 mb-3">
        {g.variables.map((v) => (
          <span key={v.name} className="text-xs rounded-full bg-mint/10 text-mint px-3 py-1">
            {v.name} = {String(v.initial)}
          </span>
        ))}
      </div>
      <ul className="space-y-2">
        {g.nodes.map((n) => (
          <li key={n.node_id} className="rounded-xl bg-panel2 border border-white/5 p-3">
            <div className="flex items-center gap-2 text-sm">
              <span className={`text-[10px] uppercase rounded px-1.5 py-0.5 ${n.kind === "ending" ? "bg-amber-500/15 text-amber-400" : "bg-accent/10 text-accent"}`}>
                {kindLabel[n.kind] ?? n.kind}
              </span>
              <span className="text-slate-200">{n.title || n.node_id}</span>
              <span className="text-slate-500 text-xs">{n.node_id}</span>
              {n.locked && <span className="text-[10px] text-slate-500 border border-slate-500/40 rounded px-1">已锁定</span>}
            </div>
            {n.summary && <p className="text-xs text-slate-400 mt-1">{n.summary}</p>}
            {(n.choices.length ?? 0) > 0 && (
              <div className="mt-2 space-y-1">
                {n.choices.map((c) => (
                  <div key={c.choice_id} className="text-xs text-slate-400">
                    <span className="text-glow">◈ {c.text}</span>
                    {c.effects.map((f, i) => (
                      <span key={i} className="ml-2">({f.variable} {f.op} {String(f.value)})</span>
                    ))}
                    {c.next_node && <span className="ml-2 text-slate-500">→ {c.next_node}</span>}
                  </div>
                ))}
              </div>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

function SceneView({ s }: { s: SceneContent }) {
  return (
    <article className="rounded-xl bg-panel2 border border-white/5 p-4">
      <div className="flex items-baseline justify-between mb-1">
        <h3 className="font-semibold text-glow">{s.title}</h3>
        <span className="text-[10px] uppercase text-slate-500">{s.scene_id}</span>
      </div>
      {s.summary && <p className="text-sm text-slate-300 mb-3">{s.summary}</p>}
      <div className="grid grid-cols-2 md:grid-cols-3 gap-3 text-sm mb-3">
        <div><div className="text-[10px] uppercase text-slate-500">地点</div>{s.location || "-"}</div>
        <div><div className="text-[10px] uppercase text-slate-500">时间</div>{s.time || "-"}</div>
        <div><div className="text-[10px] uppercase text-slate-500">氛围</div>{s.atmosphere || "-"}</div>
      </div>
      {s.characters_present.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mb-3">
          {s.characters_present.map((cid) => <Chip key={cid} label="在场" value={cid} />)}
        </div>
      )}
      {s.events.length > 0 && <FieldList title="事件序列" items={s.events} />}
      {s.emotional_beats.length > 0 && <FieldList title="情绪节拍" items={s.emotional_beats} />}
      {s.visual_direction && <Psy label="视觉方向" v={s.visual_direction} />}
      {s.camera_direction && <Psy label="镜头方向" v={s.camera_direction} />}
      {s.stage_direction && <Psy label="舞台调度" v={s.stage_direction} />}
      {s.continuity_notes && <Psy label="衔接说明" v={s.continuity_notes} />}
      {s.state_changes.length > 0 && (
        <div className="mt-2 text-xs text-slate-400">
          <span className="text-slate-500">状态效果：</span>
          {s.state_changes.map((f, i) => (
            <span key={i} className="ml-1">({f.variable} {f.op} {String(f.value)})</span>
          ))}
        </div>
      )}
    </article>
  );
}

function DialogueView({ d }: { d: DialogueContent }) {
  return (
    <article className="rounded-xl bg-panel2 border border-white/5 p-4">
      <div className="flex items-baseline justify-between mb-3">
        <h3 className="font-semibold text-glow font-mono text-sm">{d.dialogue_id}</h3>
        <span className="text-[10px] uppercase text-slate-500">
          {d.choice_id ?? "default"} · {d.lines.length} 句
        </span>
      </div>
      <div className="space-y-2 mb-3">
        {d.lines.map((l, i) => (
          <div key={i} className="rounded-lg bg-panel border border-white/5 p-2.5">
            <div className="flex items-center gap-2 text-xs text-slate-500">
              <span className="text-accent font-mono">{l.speaker}</span>
              {l.target && <span>→ {l.target}</span>}
              {l.emotion && <span className="text-slate-400">· {l.emotion}</span>}
              {l.delivery && <span className="text-slate-400">· {l.delivery}</span>}
            </div>
            <p className="text-sm text-slate-200 mt-1">{l.text}</p>
            {l.action && <p className="text-xs text-slate-500 mt-1">〔{l.action}〕</p>}
          </div>
        ))}
      </div>
      {d.conditions.length > 0 && (
        <div className="text-xs text-slate-400 mb-1">
          条件：{d.conditions.map((c) => `${c.variable} ${c.op} ${String(c.value)}`).join("，")}
        </div>
      )}
      {d.effects.length > 0 && (
        <div className="text-xs text-slate-400 mb-1">
          效果：{d.effects.map((f) => `${f.variable} ${f.op} ${String(f.value)}`).join("，")}
        </div>
      )}
      {d.next_node && <div className="text-xs text-slate-400 mb-1">下一节点：{d.next_node}</div>}
      {d.tags.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mb-2">
          {d.tags.map((t) => <span key={t} className="text-[10px] rounded-full bg-panel border border-white/10 px-2 py-0.5 text-slate-500">{t}</span>)}
        </div>
      )}
      {d.continuity_notes && <div className="text-xs text-slate-500">衔接：{d.continuity_notes}</div>}
    </article>
  );
}

function kindLabel(kind: string): string {
  if (kind === "world_bible") return "世界观";
  if (kind === "relationship_graph") return "人物关系图";
  if (kind === "story_graph") return "剧情图";
  if (kind === "plot") return "剧情大纲";
  if (kind.startsWith("character_card")) return "角色卡";
  if (kind.startsWith("scene:")) return "场景";
  if (kind.startsWith("dialogue:")) return "对白";
  if (kind.startsWith("storyboard:")) return "分镜";
  return kind;
}

function ManualEditPanel({
  projectId,
  artifacts,
  onDone,
}: {
  projectId: string;
  artifacts: ArtifactOut[];
  onDone: () => void;
}) {
  const [open, setOpen] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [reasons, setReasons] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ kind: string; ok: boolean; text: string } | null>(null);

  const latest = (artifacts ?? []).filter((a) => a.is_latest);

  const toggle = (a: ArtifactOut) => {
    if (open === a.kind) {
      setOpen(null);
      return;
    }
    setOpen(a.kind);
    setDrafts((d) => ({ ...d, [a.kind]: d[a.kind] ?? JSON.stringify(a.content ?? {}, null, 2) }));
  };

  const save = async (a: ArtifactOut) => {
    setSaving(a.kind);
    setMsg(null);
    try {
      const parsed = JSON.parse(drafts[a.kind] ?? "{}");
      await editArtifactContent(projectId, a.kind, parsed, reasons[a.kind]?.trim() || `手动编辑 ${kindLabel(a.kind)}`);
      setMsg({ kind: a.kind, ok: true, text: "保存成功（已生成新版本）" });
      onDone();
    } catch (e: any) {
      setMsg({ kind: a.kind, ok: false, text: `保存失败：${String(e?.message ?? e)}` });
    } finally {
      setSaving(null);
    }
  };

  return (
    <section className="mb-6 rounded-2xl bg-panel border border-white/10 p-6">
      <div className="flex items-center justify-between mb-3">
        <h2 className="font-bold">手动编辑内容</h2>
        <span className="text-xs text-slate-500">生成后都能手动增删改 · 保存会生成新版本</span>
      </div>
      {latest.length === 0 && <p className="text-sm text-slate-600">暂无已生成的内容。</p>}
      <div className="space-y-2">
        {latest.map((a) => (
          <div key={a.kind} className="rounded-xl bg-panel2 border border-white/5 p-3">
            <div className="flex items-center justify-between">
              <button onClick={() => toggle(a)} className="flex-1 text-left">
                <span className="font-mono text-glow text-sm">{kindLabel(a.kind)}</span>
                <span className="ml-2 text-[10px] rounded bg-panel border border-white/10 px-2 py-0.5 text-slate-400">
                  {a.kind} · v{a.version}{a.source === "user" ? " · 用户" : ""}
                </span>
              </button>
              {open === a.kind && (
                <button
                  onClick={() => save(a)}
                  disabled={saving === a.kind}
                  className="rounded-xl bg-mint/20 text-mint px-3 py-1 text-sm font-bold disabled:opacity-40"
                >
                  {saving === a.kind ? "…" : "保存"}
                </button>
              )}
            </div>
            {msg && msg.kind === a.kind && (
              <div className={`mt-2 text-xs ${msg.ok ? "text-mint" : "text-accent"}`}>{msg.text}</div>
            )}
            {open === a.kind && (
              <div className="mt-2">
                <textarea
                  value={drafts[a.kind] ?? ""}
                  onChange={(e) => setDrafts((dd) => ({ ...dd, [a.kind]: e.target.value }))}
                  rows={8}
                  spellCheck={false}
                  className="w-full rounded-xl bg-panel border border-white/10 px-3 py-2 font-mono text-xs text-slate-200 outline-none focus:border-accent"
                />
                <input
                  value={reasons[a.kind] ?? ""}
                  onChange={(e) => setReasons((rr) => ({ ...rr, [a.kind]: e.target.value }))}
                  placeholder="修改说明（可选）"
                  className="mt-2 w-full rounded-xl bg-panel border border-white/10 px-3 py-2 text-xs outline-none focus:border-accent"
                />
              </div>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}