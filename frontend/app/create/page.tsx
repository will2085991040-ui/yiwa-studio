"use client";

// 新建 / 导入创作台：选类型(galgame/avg/真人影视) → 一句创意 或 导入小说/剧本
// → AI 一键开工，自动生成世界观/角色/关系/剧情分支，落项目工作台(/agent)。
import { useRouter } from "next/navigation";
import { useState } from "react";
import TopNav from "@/components/TopNav";
import { createProjectViaDirector, getOrchestration, importNovel, orchestrateProject } from "@/lib/api";
import { appendAiProgress, clearAiProgress, setAiProgress } from "@/lib/aiProgress";

const TYPES: { id: "galgame" | "avg" | "interactive_film"; label: string; icon: string; desc: string }[] = [
  { id: "galgame", label: "Galgame", icon: "🌸", desc: "恋爱/多线结局，情感驱动" },
  { id: "avg", label: "AVG 冒险", icon: "🔍", desc: "互动叙事冒险，选择分支" },
  { id: "interactive_film", label: "真人影视", icon: "🎬", desc: "真人谍影互动剧情电影" },
];

export default function CreatePage() {
  const router = useRouter();
  const [mode, setMode] = useState<"goal" | "novel">("goal");
  const [gameType, setGameType] = useState<"galgame" | "avg" | "interactive_film">("galgame");
  const [title, setTitle] = useState("");
  const [goal, setGoal] = useState("");
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");

  const handleFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setMsg("");
    if (!/\.txt$/i.test(file.name) && file.type !== "text/plain") {
      setMsg("请选择 .txt 文本文件（暂不支持其他格式）");
      return;
    }
    const reader = new FileReader();
    reader.onload = () => setText(String(reader.result ?? ""));
    reader.onerror = () => setMsg("读取文件失败，请重试");
    reader.readAsText(file, "utf-8");
    e.target.value = "";
  };

  const start = async () => {
    setMsg("");
    if (!title.trim()) { setMsg("请填一个作品标题"); return; }
    if (mode === "goal" && !goal.trim()) { setMsg("请写下你的创意一句话，会由 AI 自动生成世界观/角色/关系/分支"); return; }
    if (mode === "novel" && text.trim().length < 50) { setMsg("请粘贴至少 50 字的小说/剧本原文，才能做有意义的拆解"); return; }
    setBusy(true);
    try {
      let pid = "";
      const label = TYPES.find((t) => t.id === gameType)?.label ?? gameType;
      if (mode === "goal") {
        const r = await createProjectViaDirector(goal.trim(), { game_type: gameType, title: title.trim() });
        pid = r.project_id;
        // 自动跑完整流水线：世界观/角色/关系 → 剧情图 → 场景/对白/分镜 → 立绘
        // 让剧情画布、分镜分解、角色立绘在“一键”后自动就位。
        setMsg(`✅ 「${title.trim()}」(${label}) 已创建，正在一键生成全部内容…`);
        setAiProgress({ label: "AI 一键生成全部内容", detail: "Director → 世界观/角色/关系 → 剧情图 → 场景/对白/分镜 → 立绘…", pct: 0 });
        const st = window.setInterval(() => {
          getOrchestration(pid).then((o) => {
            const steps = o?.steps ?? [];
            const DONE = ["ok", "done", "succeeded", "success"];
            const done = steps.filter((s) => DONE.includes(s.status)).length;
            const pct = steps.length ? Math.round((done / steps.length) * 100) : 0;
            const cur = steps.find((s) => s.status === "running");
            appendAiProgress({ pct, detail: cur ? `正在生成：${cur.label || cur.key}` : `${done}/${steps.length} 个步骤完成` });
          }).catch(() => {});
        }, 900);
        try {
          await orchestrateProject(pid);
          appendAiProgress({ pct: 100, detail: "全部内容已生成" });
        } finally {
          window.clearInterval(st);
          clearAiProgress();
        }
        setMsg("✅ 已自动生成全部内容（画布/对白/分镜/立绘均已就位），正在打开工作台…");
      } else {
        const r = await importNovel({ title: title.trim(), text: text.trim(), game_type: gameType });
        pid = r.project_id;
        setMsg(`✅ 「${title.trim()}」(${label}) 已拆解出角色与关系，正在打开工作台…`);
      }
      setTimeout(() => router.push(`/agent?project=${pid}`), 900);
    } catch (e) {
      setMsg(`创建失败：${String((e as Error).message ?? e)}`);
    } finally {
      setBusy(false);
    }
  };

  const inputCls = "w-full rounded-xl border border-white/10 bg-panel2 px-4 py-3 text-sm text-slate-200 outline-none focus:border-accent placeholder:text-slate-500";

  return (
    <div className="min-h-screen bg-[#0b0d1f] text-slate-100">
      <TopNav />
      <main className="mx-auto max-w-3xl px-6 py-10">
        <h1 className="text-2xl font-black text-glow">开始一部新作品</h1>
        <p className="mt-1 text-sm text-slate-400">
          选个类型 → 一句创意 或 导入小说/剧本 → AI 自动生成世界观、角色卡、角色关系、事件与分支，落到项目工作台继续完善。
        </p>

        {/* 类型选择 */}
        <div className="mt-6 grid grid-cols-1 gap-3 sm:grid-cols-3">
          {TYPES.map((t) => (
            <button
              key={t.id}
              onClick={() => { setGameType(t.id as typeof gameType); setMsg(""); }}
              className={`rounded-2xl border p-5 text-left transition-all ${gameType === t.id ? "border-accent/60 bg-accent/10" : "border-white/10 bg-panel/60 hover:bg-panel2"}`}
            >
              <div className="text-2xl">{t.icon}</div>
              <div className="mt-2 text-base font-bold text-white">{t.label}</div>
              <div className="mt-1 text-xs text-slate-400">{t.desc}</div>
            </button>
          ))}
        </div>

        {/* 输入方式 */}
        <div className="mt-6 rounded-2xl border border-white/10 bg-panel/70 p-6">
          <div className="mb-4 flex items-center gap-1 rounded-xl bg-panel2 p-1">
            {([["goal", "✍️ 一句创意"], ["novel", "📚 导入小说/剧本"]] as const).map(([m, label]) => (
              <button key={m} onClick={() => { setMode(m); setMsg(""); }}
                className={`flex-1 rounded-lg py-2 text-sm font-bold transition-colors ${mode === m ? "bg-accent/25 text-accent" : "text-slate-400 hover:text-white"}`}>
                {label}
              </button>
            ))}
          </div>

          <label className="mb-4 block text-xs text-slate-400">
            作品标题
            <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="例如：霓虹不再缄默" className={`${inputCls} mt-1`} />
          </label>

          {mode === "goal" ? (
            <label className="mb-4 block text-xs text-slate-400">
              一句话创意（AI 据此生成世界观/角色/关系/事件/分支）
              <textarea value={goal} onChange={(e) => setGoal(e.target.value)} rows={4}
                placeholder="例如：在废土之上的旧城区，一名女侦探要在一桩悬案里揪出背后的机械教团，而嫌疑犯是她的青梅竹马……"
                className={`${inputCls} mt-1`} />
            </label>
          ) : (
            <label className="mb-4 block text-xs text-slate-400">
              <div className="mb-1 flex items-center justify-between">
                粘贴你的小说 / 剧本原文（至少 50 字）
                <label className="cursor-pointer rounded-lg bg-panel2 border border-white/15 px-2.5 py-1 text-[11px] font-bold text-accent hover:bg-white/5">
                  📄 上传 .txt
                  <input type="file" accept=".txt,text/plain" onChange={handleFile} className="hidden" />
                </label>
              </div>
              <textarea value={text} onChange={(e) => setText(e.target.value)} rows={8}
                placeholder="把小说或剧本正文粘贴到这里，或点右上角「上传 .txt」读取本地文件。AI 会拆解出场景、角色卡与人物关系，并串联成剧情分支……"
                className={`${inputCls} mt-1`} />
            </label>
          )}

          {msg && <p className="mb-3 text-xs text-glow">{msg}</p>}

          <button
            onClick={start}
            disabled={busy}
            className="w-full rounded-xl bg-gradient-to-r from-[#ff2e76] to-[#ff7a59] py-3.5 text-base font-black text-white transition-transform hover:scale-[1.01] disabled:opacity-60"
          >
            {busy ? "AI 正在创建并拆解…" : "🚀 创建，进入工作台一键生成"}
          </button>
        </div>
      </main>
    </div>
  );
}