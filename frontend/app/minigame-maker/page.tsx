"use client";

// 小游戏制作台：AI 一键生成（10 种类型 + 画风 + 创意文本）+ 手动可视化配置，插入剧情节点。
// 全部走真实后端（minigames 端点），不造假数据。
import { useEffect, useState } from "react";
import TopNav from "@/components/TopNav";
import { GAME_TYPES, GAME_META, generateMinigame, listMinigames, insertMinigame, type GameConfig } from "@/lib/api";

type GameType = "click" | "memory";

const MANUAL_META: Record<GameType, { label: string; desc: string }> = {
  click: { label: "连点挑战", desc: "在限定时间内完成指定次数的点击" },
  memory: { label: "记忆配对", desc: "翻开卡片找出所有配对图案" },
};

const STYLE_PRESETS = ["像素风", "水墨风", "赛博朋克", "手绘动漫", "8-bit 复古", "低保真合成器"];

export default function MinigameMakerPage() {
  // ---- AI 生成模式状态 ----
  const [projectId, setProjectId] = useState("");
  const [pidInput, setPidInput] = useState("");
  const [aiType, setAiType] = useState<string>("click");
  const [aiStyle, setAiStyle] = useState("赛博朋克");
  const [aiPrompt, setAiPrompt] = useState("");
  const [aiBusy, setAiBusy] = useState(false);
  const [aiMsg, setAiMsg] = useState("");
  const [aiResult, setAiResult] = useState<GameConfig | null>(null);
  const [insertNodeId, setInsertNodeId] = useState("");
  const [insertMsg, setInsertMsg] = useState("");
  const [library, setLibrary] = useState<{ game_id: string; config: GameConfig; kind: string }[] | null>(null);

  // ---- 手动模式状态（保留原功能） ----
  const [gameId, setGameId] = useState<GameType>("click");
  const [title, setTitle] = useState("连点挑战");
  const [description, setDescription] = useState("在限定时间内完成点击次数");
  const [target, setTarget] = useState("8");
  const [timeLimit, setTimeLimit] = useState("8");
  const [grid, setGrid] = useState("8");
  const [successResult, setSuccessResult] = useState<"success" | "perfect">("success");
  const [scoreVariable, setScoreVariable] = useState("");
  const [copied, setCopied] = useState(false);
  const [usePreview, setUsePreview] = useState(true);

  useEffect(() => {
    setProjectId(new URLSearchParams(window.location.search).get("project") ?? "");
  }, []);

  useEffect(() => {
    if (!projectId) return;
    listMinigames(projectId).then(setLibrary).catch(() => {});
  }, [projectId]);

  const aiGene = async () => {
    if (!projectId.trim()) { setAiMsg("请输入项目 ID"); return; }
    if (!aiPrompt.trim()) { setAiMsg("请先写下你的创意/玩法描述"); return; }
    setAiBusy(true);
    setAiMsg("");
    try {
      const r = await generateMinigame(projectId, { game_type: aiType, style: aiStyle, prompt: aiPrompt.trim() });
      setAiResult(r.config);
      setAiMsg(`✅ 已生成「${r.config.title}」（${aiType} · ${aiStyle}）`);
      setInsertNodeId("");
      listMinigames(projectId).then(setLibrary).catch(() => {});
    } catch (e) {
      setAiMsg(`生成失败：${String((e as Error).message ?? e)}`);
    } finally {
      setAiBusy(false);
    }
  };

  const doInsert = async () => {
    if (!insertNodeId.trim()) { setInsertMsg("请填写剧情节点 ID"); return; }
    try {
      const r = await insertMinigame(projectId, aiResult?.game_id ?? "", insertNodeId.trim());
      setInsertMsg(`✅ 已把「${aiResult?.title ?? ""}」插入剧情节点 ${r.node_id}（该节点将编译该小游戏）`);
    } catch (e) {
      setInsertMsg(`插入失败：${String((e as Error).message ?? e)}`);
    }
  };

  const inputCls = "w-full rounded-xl bg-panel border border-white/10 px-3 py-2 text-sm outline-none focus:border-accent";
  const manualConfig = {
    game_id: gameId,
    title,
    description,
    success_result: successResult,
    score_variable: scoreVariable.trim() ? scoreVariable : null,
    settings: {
      target: Math.max(1, Number(target) || 8),
      time_limit_s: Math.max(1, Number(timeLimit) || (gameId === "memory" ? 30 : 8)),
      grid: Math.max(2, Number(grid) || 8),
    },
  };
  const manualPreviewUrl = `/minigame?game=${gameId}&config=${encodeURIComponent(JSON.stringify(manualConfig))}`;

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(JSON.stringify(manualConfig, null, 2));
    } catch {
      const ta = document.createElement("textarea");
      ta.value = JSON.stringify(manualConfig, null, 2);
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      document.body.removeChild(ta);
    }
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <div className="min-h-screen bg-[#0c0b1d] text-slate-100">
      <TopNav active="minigame" projectId={projectId}>
        <input
          value={pidInput}
          onChange={(e) => setPidInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && pidInput.trim()) setProjectId(pidInput.trim()); }}
          placeholder="项目 ID"
          className="w-40 rounded-md bg-panel2 px-2 py-1 text-xs text-slate-200 outline-none placeholder:text-slate-500"
        />
      </TopNav>
      <main className="mx-auto max-w-6xl px-6 py-8">
        <h1 className="text-2xl font-bold text-glow">小游戏生成器</h1>
        <p className="mt-1 text-sm text-slate-500">选类型 + 画风 + 写一段创意，AI 生成可插入剧情的小游戏；也可手动微调配置。</p>

        {/* AI 一键生成区 */}
        <section className="mt-6 rounded-2xl border border-accent/20 bg-panel/60 p-6">
          <h2 className="mb-3 text-sm font-bold text-accent">✨ AI 生成小游戏（消耗 token）</h2>

          <div className="mb-3">
            <div className="mb-1 text-xs text-slate-400">选择玩法类型（10 种）</div>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
              {GAME_TYPES.map((t) => (
                <button key={t} onClick={() => setAiType(t)}
                  className={`rounded-xl border px-3 py-2 text-xs ${aiType === t ? "border-accent/60 bg-accent/15 text-accent" : "border-white/10 bg-panel2 text-slate-300 hover:bg-white/5"}`}>
                  <span className="mr-1">{GAME_META[t]?.emoji}</span>{GAME_META[t]?.label}
                </button>
              ))}
            </div>
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <label className="block text-xs text-slate-400">画风 / 风格
              <input value={aiStyle} onChange={(e) => setAiStyle(e.target.value)} className={`${inputCls} mt-1`} />
              <span className="mt-1 flex flex-wrap gap-1">
                {STYLE_PRESETS.map((s) => (
                  <button key={s} onClick={() => setAiStyle(s)} className="rounded bg-white/5 px-2 py-0.5 text-[10px] hover:bg-white/10">{s}</button>
                ))}
              </span>
            </label>
            <label className="block text-xs text-slate-400">你的创意/玩法（自然语言）
              <textarea value={aiPrompt} onChange={(e) => setAiPrompt(e.target.value)} rows={3}
                placeholder="例如：一条赛博朋克街头的连点挑战，要在霓虹里救出被机械侠抱走的队友……"
                className={`${inputCls} mt-1`} />
            </label>
          </div>

          <div className="mt-4 flex items-center gap-3">
            <button onClick={aiGene} disabled={aiBusy}
              className="rounded-xl bg-accent/25 text-accent px-5 py-2.5 text-sm font-bold hover:bg-accent/35 disabled:opacity-50">
              {aiBusy ? "AI 生成中…" : "🚀 生成小游戏"}
            </button>
            {aiMsg && <span className="text-xs text-glow">{aiMsg}</span>}
          </div>

          {aiResult ? (
            <div className="mt-4 rounded-xl bg-[#0a0c1c] p-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="text-sm font-bold">{aiResult.title} <span className="text-xs text-slate-500">· {GAME_META[aiResult.game_id]?.label}</span></span>
                <a href={`/minigame?game=${aiResult.game_id}&config=${encodeURIComponent(JSON.stringify(aiResult))}`}
                  target="_blank" rel="noreferrer"
                  className="rounded bg-glow/15 px-3 py-1 text-xs text-glow">▶ 预览</a>
              </div>
              <p className="mt-1 text-xs text-slate-400">{aiResult.description}</p>
              <pre className="mt-2 overflow-x-auto rounded-lg bg-panel2 p-2 font-mono text-[10px] text-slate-300">{JSON.stringify(aiResult, null, 2)}</pre>
              <div className="mt-3 flex items-center gap-2">
                <span className="text-xs text-slate-400">插入剧情节点：</span>
                <input value={insertNodeId} onChange={(e) => setInsertNodeId(e.target.value)} placeholder="node_id" className="w-44 rounded-md bg-panel2 px-2 py-1 text-xs outline-none" />
                <button onClick={doInsert} className="rounded-lg bg-mint/20 px-3 py-1 text-xs text-mint">插入剧情</button>
                {insertMsg && <span className="text-xs text-glow">{insertMsg}</span>}
              </div>
            </div>
          ) : null}

          {library && library.length > 0 && (
            <div className="mt-4">
              <div className="text-xs font-bold text-slate-400">本项目已生成：{library.length}</div>
              <div className="mt-1 flex flex-wrap gap-2">
                {library.map((g) => (
                  <button key={g.game_id} onClick={() => setAiResult(g.config)}
                    className="rounded-lg border border-white/10 bg-panel2 px-3 py-1.5 text-xs text-slate-300 hover:bg-white/5">
                    {GAME_META[g.config.game_id]?.emoji} {g.config.title}
                  </button>
                ))}
              </div>
            </div>
          )}
        </section>

        {/* 手动微调（保留原功能） */}
        <section className="mt-6 grid gap-6 md:grid-cols-2">
          <div className="rounded-2xl bg-panel border border-white/10 p-6">
            <h2 className="mb-4 text-sm font-bold">游戏设置（手动微调）</h2>
            <label className="mb-3 block text-xs text-slate-400">
              游戏类型
              <select value={gameId} onChange={(e) => setGameId(e.target.value as GameType)} className={`${inputCls} mt-1`}>
                {Object.entries(MANUAL_META).map(([k, v]) => (
                  <option key={k} value={k}>{v.label} · {v.desc}</option>
                ))}
              </select>
            </label>
            <label className="mb-3 block text-xs text-slate-400">
              标题
              <input value={title} onChange={(e) => setTitle(e.target.value)} className={`${inputCls} mt-1`} />
            </label>
            <label className="mb-3 block text-xs text-slate-400">
              规则说明
              <textarea value={description} onChange={(e) => setDescription(e.target.value)} rows={2} className={`${inputCls} mt-1`} />
            </label>
            <div className="mb-3 grid grid-cols-3 gap-3">
              {gameId === "memory" ? (
                <label className="block text-xs text-slate-400">卡片数量
                  <input value={grid} onChange={(e) => setGrid(e.target.value)} className={`${inputCls} mt-1`} /></label>
              ) : (
                <label className="block text-xs text-slate-400">目标次数
                  <input value={target} onChange={(e) => setTarget(e.target.value)} className={`${inputCls} mt-1`} /></label>
              )}
              <label className="block text-xs text-slate-400">时间（秒）
                <input value={timeLimit} onChange={(e) => setTimeLimit(e.target.value)} className={`${inputCls} mt-1`} /></label>
              <label className="block text-xs text-slate-400">通过结果
                <select value={successResult} onChange={(e) => setSuccessResult(e.target.value as "success" | "perfect")} className={`${inputCls} mt-1`}>
                  <option value="success">success</option>
                  <option value="perfect">perfect</option>
                </select></label>
            </div>
            <label className="mb-4 block text-xs text-slate-400">得分写入变量（可留空）
              <input value={scoreVariable} onChange={(e) => setScoreVariable(e.target.value)} placeholder="如 favorability" className={`${inputCls} mt-1`} />
            </label>
            <button onClick={copy} className="rounded-xl bg-glow/20 text-glow px-4 py-2 text-sm font-bold hover:bg-glow/30">
              {copied ? "已复制 ✓" : "复制配置"}
            </button>
            <button onClick={() => setUsePreview((u) => !u)} className="ml-2 rounded-xl bg-panel2 border border-white/10 px-4 py-2 text-sm text-slate-300">
              {usePreview ? "隐藏预览" : "显示预览"}
            </button>
          </div>

          <div className="rounded-2xl bg-panel border border-white/10 p-6">
            <h2 className="mb-2 text-sm font-bold">实时预览</h2>
            <p className="mb-3 text-xs text-slate-500">下方 iframe 使用当前配置渲染游戏</p>
            {usePreview ? (
              <iframe key={manualPreviewUrl} src={manualPreviewUrl} className="h-[420px] w-full rounded-2xl bg-slate-950" title="minigame preview" />
            ) : (
              <div className="flex h-[420px] items-center justify-center rounded-2xl bg-slate-950 text-slate-600">预览已隐藏</div>
            )}
          </div>
        </section>
      </main>
    </div>
  );
}