"use client";

// YIWA · AI 互动影视创作 OS —— 电影感登录页（单文件落地页）
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { createProjectViaDirector, getOrchestration, listProjects, orchestrateProject } from "@/lib/api";
import { appendAiProgress, clearAiProgress, setAiProgress } from "@/lib/aiProgress";

/* ---------------------------------- 数据 ---------------------------------- */
const SHOWCASES = [
  {
    emoji: "🤖",
    title: "Detroit: Become Human",
    desc: "仿生人觉醒于底特律街头，每一次选择都改写叙事的脚手架。",
    tags: ["互动电影", "选择分支"],
    accent: "text-glow",
    border: "from-sky-500/60 via-accent/40 to-cyan-400/50",
  },
  {
    emoji: "🔮",
    title: "Life is Strange",
    desc: "以时光回溯的超能力拨动命运的琴弦，青春的每一个回眸都藏着代价。",
    tags: ["AVG", "超能力"],
    accent: "text-mint",
    border: "from-mint/60 via-teal-400/40 to-glow/40",
  },
  {
    emoji: "🧟",
    title: "The Walking Dead — Telltale",
    desc: "末日辐射下的伦理抉择与幸存书写，点击即承担后果的互动剧情。",
    tags: ["互动剧情", "末日生存"],
    accent: "text-glow",
    border: "from-gold/60 via-orange-400/40 to-mint/40",
  },
  {
    emoji: "🎞️",
    title: "428 ～被封锁的涩谷～",
    desc: "真人实拍多线叙事，四段命运在涩谷封锁的十小时里彼此交缠。",
    tags: ["真人互动", "多线并行"],
    accent: "text-gold",
    border: "from-gold/60 via-amber-400/40 to-sky-400/40",
  },
  {
    emoji: "😵‍💫",
    title: "Needy Streamer Overload 电波奴",
    desc: "少女主播在数字与自我之间挣扎，成长与崩坏的边缘步步惊心。",
    tags: ["电波", "成长"],
    accent: "text-glow",
    border: "from-accent/60 via-fuchsia-400/40 to-glow/40",
  },
  {
    emoji: "🌸",
    title: "CLANNAD",
    desc: "小镇物语，光玉流转，一部让无数人泪流满面的青春叙事诗。",
    tags: ["Galgame", "催泪"],
    accent: "text-mint",
    border: "from-mint/60 via-emerald-400/40 to-glow/40",
  },
  {
    emoji: "⏳",
    title: "Steins;Gate",
    desc: "电话微波炉（暂定）穿越时间线，科学 ADV 中撬动世界的齿轮。",
    tags: ["科学ADV", "时间旅行"],
    accent: "text-accent",
    border: "from-accent/60 via-sky-400/40 to-glow/40",
  },
  {
    emoji: "🎻",
    title: "白色相簿2",
    desc: "终章雪色飘摇，复杂的恋爱关系在每一次告白里走向不同终局。",
    tags: ["Galgame", "恋爱"],
    accent: "text-gold",
    border: "from-gold/60 via-rose-400/40 to-accent/40",
  },
];

const SCROLLER: number[] = [0, 1, 2, 3, 4, 5, 6, 7];

/* ---------------------------------- 组件 ---------------------------------- */
function ShowcaseCard({
  item,
  className = "",
}: {
  item: (typeof SHOWCASES)[number];
  className?: string;
}) {
  return (
    <div
      className={`group relative min-w-[300px] flex-shrink-0 rounded-2xl p-px bg-gradient-to-br ${item.border} transition-transform duration-500 hover:-translate-y-2 hover:shadow-[0_20px_60px_-15px_rgba(255,77,120,0.45)] ${className}`}
    >
      <div className="relative h-full rounded-2xl bg-[#0e1020]/95 p-6 overflow-hidden">
        <div className="absolute -right-8 -top-8 h-24 w-24 rounded-full bg-gradient-to-br from-accent/30 to-glow/10 blur-2xl opacity-0 group-hover:opacity-100 transition-opacity duration-700" />
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0 opacity-0 group-hover:opacity-100 transition-opacity"
          style={{ background: "linear-gradient(135deg, rgba(255,77,120,0.12), transparent 55%)" }}
        />
        <div className="relative">
          <div className="text-4xl drop-shadow-[0_0_18px_rgba(255,179,200,0.35)]">{item.emoji}</div>
          <h3 className={`mt-4 text-lg font-black tracking-wide ${item.accent}`}>{item.title}</h3>
          <p className="mt-2 text-sm leading-relaxed text-slate-300">{item.desc}</p>
          <div className="mt-4 flex flex-wrap gap-2">
            {item.tags.map((t) => (
              <span
                key={t}
                className="rounded-full border border-white/10 bg-panel2 px-2.5 py-0.5 text-xs text-slate-300"
              >
                {t}
              </span>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

/* ---------------------------------- 页面 ---------------------------------- */
export default function Landing() {
  // ---- 我的作品：真实后端 列表 + 新建 ----
  type ProjectRow = {
    id: string; goal: string; template: string; title: string;
    description: string | null; current_version: number; status: string; created_at: string;
  };
  const [projects, setProjects] = useState<ProjectRow[]>([]);
  const [projectsLoading, setProjectsLoading] = useState(true);
  const [goal, setGoal] = useState("");
  const [creating, setCreating] = useState(false);
  const [createMsg, setCreateMsg] = useState("");
  const [worksKey, setWorksKey] = useState(0);

  const refreshProjects = useCallback(() => {
    setProjectsLoading(true);
    listProjects()
      .then(setProjects)
      .catch(() => setProjects([]))
      .finally(() => setProjectsLoading(false));
  }, []);

  useEffect(() => {
    refreshProjects();
  }, [refreshProjects]);

  const createProject = async () => {
    if (!goal.trim()) { setCreateMsg("请先写下一句创意目标"); return; }
    if (creating) return;
    setCreating(true);
    setCreateMsg("");
    try {
      // Director 垂直切片：真实生成一个项目
      const r = await createProjectViaDirector(goal.trim());
      const pid = (r as { project_id?: string } | null)?.project_id;
      if (!pid) throw new Error("创建成功但未返回项目编号，请到项目列表进入 IDE");
      setGoal("");
      refreshProjects();
      // 自动跑完整流水线：世界观/角色/关系 → 剧情图 → 场景/对白/分镜 → 立绘
      // 让剧情画布、分镜分解、角色立绘在“一键”之后都自动填充，无需再手动点“一键生成”。
      setCreateMsg(`✅ 已创建「${goal.trim().slice(0, 20)}」，正在一键生成全部内容…`);
      setAiProgress({ label: "AI 一键生成全部内容", detail: "Director → 世界观/角色/关系 → 剧情图 → 场景/对白/分镜 → 立绘…", pct: 0 });
      const st = window.setInterval(() => {
        getOrchestration(pid).then((o) => {
          const st2 = o?.steps ?? [];
          const DONE = ["ok", "done", "succeeded", "success"];
          const done = st2.filter((s) => DONE.includes(s.status)).length;
          const pct = st2.length ? Math.round((done / st2.length) * 100) : 0;
          const cur = st2.find((s) => s.status === "running");
          appendAiProgress({ pct, detail: cur ? `正在生成：${cur.label || cur.key}` : `${done}/${st2.length} 个步骤完成` });
        }).catch(() => {});
      }, 900);
      try {
        await orchestrateProject(pid);
        await getOrchestration(pid).then((o) => {
          const st2 = o?.steps ?? [];
          appendAiProgress({ pct: 100, detail: st2.length ? `全部 ${st2.length} 个步骤完成` : "完成" });
        });
        setCreateMsg("✅ 已自动生成全部内容（世界观/角色/剧情图/对白/分镜/立绘均可点击查看）");
      } finally {
        window.clearInterval(st);
        clearAiProgress();
      }
      await refreshProjects();
    } catch (e) {
      setCreateMsg(`新建失败：${String((e as Error).message ?? e)}`);
      clearAiProgress();
    } finally {
      setCreating(false);
    }
  };

  return (
    <>
      <style>{`
        @keyframes floatUp {
          0%   { transform: translateY(0) translateX(0) scale(1); opacity: 0; }
          10%  { opacity: 1; }
          90%  { opacity: .7; }
          100% { transform: translateY(-90vh) translateX(40px) scale(1.35); opacity: 0; }
        }
        @keyframes blobDrift {
          0%   { transform: translate(0,0) scale(1); }
          33%  { transform: translate(60px,-40px) scale(1.2); }
          66%  { transform: translate(-40px,30px) scale(0.9); }
          100% { transform: translate(0,0) scale(1); }
        }
        @keyframes gradShift {
          0%   { background-position: 0% 50%; }
          50%  { background-position: 100% 50%; }
          100% { background-position: 0% 50%; }
        }
        @keyframes shimmer {
          0%   { background-position: -200% 0; }
          100% { background-position: 200% 0; }
        }
        @keyframes marquee {
          0%   { transform: translateX(0); }
          100% { transform: translateX(calc(-50% - 1.25rem)); }
        }
        @keyframes flicker {
          0%,100% { opacity: 1; }
          50% { opacity: .55; }
        }
        @keyframes pulseGlow {
          0%,100% { box-shadow: 0 0 30px rgba(139,92,246,.42), 0 0 60px rgba(34,211,238,.18); }
          50%  { box-shadow: 0 0 55px rgba(139,92,246,.68), 0 0 90px rgba(34,211,238,.32); }
        }
        .ywa-gradient {
          background-image: linear-gradient(120deg, #8b5cf6, #22d3ee, #38bdf8, #f472b6, #8b5cf6, #22d3ee);
          background-size: 400% 400%;
          animation: gradShift 14s ease-in-out infinite;
        }
        .ywa-grad-text {
          background: linear-gradient(115deg, #a78bfa, #22d3ee, #38bdf8, #f472b6, #a78bfa, #22d3ee);
          background-size: 300% 300%;
          -webkit-background-clip: text;
          background-clip: text;
          color: transparent;
          animation: gradShift 12s ease-in-out infinite;
        }
        .ywa-marquee-track {
          width: max-content;
          animation: marquee 42s linear infinite;
        }
        .ywa-marquee-track:hover { animation-play-state: paused; }
      `}</style>

      {/* ===================== HERO ===================== */}
      <header className="relative flex min-h-[92vh] flex-col items-center justify-center overflow-hidden px-6 text-center">
        {/* 动态渐变背景 */}
        <div className="absolute inset-0 -z-20 bg-night" />
        <div className="ywa-gradient ywa absolute inset-0 -z-10 opacity-[0.14] blur-2xl" />

        {/* 漂浮光斑 */}
        <div
          aria-hidden
          className="absolute inset-0 -z-10 overflow-hidden"
        >
          {[...Array(14)].map((_, i) => (
            <span
              key={i}
              className="absolute rounded-full"
              style={{
                left: `${(i * 7.1) % 100}%`,
                bottom: `${(i * 3.7) % 18}%`,
                width: `${4 + (i % 5) * 3}px`,
                height: `${4 + (i % 5) * 3}px`,
                background: i % 3 === 0 ? "rgba(139,92,246,.72)" : i % 3 === 1 ? "rgba(34,211,238,.6)" : "rgba(167,139,250,.6)",
                boxShadow: "0 0 12px currentColor",
                color: "rgba(255,120,160,.8)",
                animation: `floatUp ${9 + (i % 6) * 2}s linear ${i * 1.4}s infinite`,
              }}
            />
          ))}
          <div
            className="absolute left-[12%] top-[22%] h-72 w-72 rounded-full bg-accent/25 blur-3xl"
            style={{ animation: "blobDrift 16s ease-in-out infinite" }}
          />
          <div
            className="absolute right-[10%] top-[30%] h-80 w-80 rounded-full bg-gold/15 blur-3xl"
            style={{ animation: "blobDrift 20s ease-in-out infinite reverse" }}
          />
          <div
            className="absolute left-[40%] bottom-[8%] h-64 w-64 rounded-full bg-mint/15 blur-3xl"
            style={{ animation: "blobDrift 24s ease-in-out infinite" }}
          />
        </div>

        {/* 顶部迷你导航（内联） */}
        <nav className="absolute top-0 left-0 right-0 z-10 flex items-center justify-between px-8 py-6">
          <div className="flex items-center gap-2 text-xl font-black tracking-widest">
            <span className="inline-block h-3 w-3 rounded-full bg-accent" style={{ animation: "flicker 2.6s ease-in-out infinite" }} />
            <span className="text-white">YIWA</span>
          </div>
          <div className="flex items-center gap-5 text-sm text-slate-300">
            <a href="#works" className="transition-colors hover:text-accent">我的作品</a>
            <a href="#showcases" className="transition-colors hover:text-accent">作品灵感</a>
            <a href="#features" className="transition-colors hover:text-accent">能力</a>
          </div>
        </nav>

        {/* 标题区 */}
        <div className="relative z-0 max-w-4xl">
          <div className="mb-6 inline-flex items-center gap-2 rounded-full border border-accent/40 bg-accent/10 px-4 py-1.5 text-xs font-semibold tracking-[0.3em] text-accent">
            ✦ AI 互动影视创作 OS ✦
          </div>

          <h1 className="text-5xl font-black leading-tight sm:text-6xl md:text-7xl">
            <span className="ywa-grad-text block">
              YIWA
            </span>
            <span className="mt-3 block text-2xl font-bold text-white sm:text-3xl md:text-4xl">
              你的 AI 互动影视创作 OS
            </span>
          </h1>

          <p className="mx-auto mt-7 max-w-2xl text-base leading-relaxed text-slate-300 sm:text-lg">
            一句话创意，从导演蓝图、角色卡、剧情图到试玩与互动影视一键生成。
            让每个人都能在帧与帧之间，导演属于自己的互动世界。
          </p>

          <div className="mt-10 flex flex-col items-center gap-4 sm:flex-row sm:justify-center">
            <Link
              href="/create"
              className="group inline-flex items-center gap-2 rounded-2xl bg-gradient-to-r from-[#8b5cf6] to-[#22d3ee] px-9 py-4 text-lg font-black text-white transition-transform duration-300 hover:scale-[1.04]"
              style={{ animation: "pulseGlow 3.2s ease-in-out infinite" }}
            >
              <span className="transition-transform duration-300 group-hover:-translate-y-0.5">🎬</span>
              开始创作
            </Link>
            <a
              href="#works"
              className="inline-flex items-center gap-2 rounded-2xl border border-white/25 bg-panel/50 px-9 py-4 text-lg font-bold text-white backdrop-blur transition-all duration-300 hover:border-accent/60 hover:text-accent"
            >
              🗂️ 我的作品
            </a>
          </div>

          <p className="mt-12 text-xs tracking-widest text-slate-500">
            ⌘ 无需代码 · 中文创作 · 实时试玩 · 一键导出互动影游
          </p>
        </div>
      </header>

      {/* ===================== 滚动作品走马灯 ===================== */}
      <section id="showcases" className="relative overflow-hidden border-y border-white/10 bg-panel/40 py-16">
        <div className="mx-auto mb-10 max-w-6xl px-6 text-center">
          <h2 className="text-3xl font-black text-white sm:text-4xl">互动叙事 · 经典共鸣</h2>
          <p className="mt-4 text-slate-400">
            从互动电影到 Galgame，向那些让无数玩家深夜屏息的作品致敬——这些，正是 YIWA 想让你亲手缔造的类型。
          </p>
        </div>

        <div
          className="relative overflow-hidden"
          style={{
            WebkitMaskImage: "linear-gradient(90deg, transparent, #000 8%, #000 92%, transparent)",
            maskImage: "linear-gradient(90deg, transparent, #000 8%, #000 92%, transparent)",
          }}
        >
          <div className="ywa-marquee-track flex gap-5 py-4">
            {SCROLLER.map((n) => (
              <ShowcaseCard key={n} item={SHOWCASES[n % SHOWCASES.length]} />
            ))}
            {/* 复制一份实现无缝循环 */}
            {SCROLLER.map((n) => (
              <ShowcaseCard key={`dup-${n}`} item={SHOWCASES[n % SHOWCASES.length]} />
            ))}
          </div>
        </div>
      </section>

      {/* ===================== 我的作品（真实后端：新建 + 列表） ===================== */}
      <section id="works" className="relative overflow-hidden border-t border-white/10 bg-night py-20">
        <div className="mx-auto max-w-6xl px-6">
          <div className="flex flex-col items-center justify-between gap-6 sm:flex-row sm:items-end">
            <div>
              <h2 className="text-3xl font-black text-white sm:text-4xl">我的作品</h2>
              <p className="mt-3 max-w-xl text-slate-400">一句创意即可开新项目；已有项目直接进入 IDE / 剧情图继续创作。</p>
            </div>
            <span className="rounded-full border border-accent/40 bg-accent/10 px-4 py-1.5 text-xs font-semibold text-accent">
              {projectsLoading ? "载入中…" : `${projects.length} 个项目`}
            </span>
          </div>

          {/* 新建作品 */}
          <div className="mt-8 rounded-2xl border border-white/10 bg-panel/70 p-6">
            <div className="text-sm font-bold text-white">新建作品</div>
            <div className="mt-3 flex flex-col gap-2 sm:flex-row">
              <input
                value={goal}
                onChange={(e) => setGoal(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") createProject(); }}
                placeholder="一句话创意，例如：赛博朋克侦探在废弃都市追查连环失踪案……"
                className="flex-1 rounded-xl border border-white/10 bg-panel2 px-4 py-3 text-sm text-slate-200 outline-none placeholder:text-slate-500 focus:border-accent"
              />
              <button
                onClick={createProject}
                disabled={creating}
                className="shrink-0 rounded-xl bg-gradient-to-r from-[#8b5cf6] to-[#22d3ee] px-6 py-3 text-sm font-black text-white transition-transform hover:scale-[1.02] disabled:opacity-60"
              >
                {creating ? "生成中…" : "🎬 新建作品"}
              </button>
            </div>
            {createMsg && <p className="mt-2 text-xs text-glow">{createMsg}</p>}
          </div>

          {/* 作品列表 */}
          <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {projects.map((p) => (
              <div key={p.id} className="group rounded-2xl border border-white/10 bg-panel/60 p-5 transition-all hover:-translate-y-1 hover:border-accent/40">
                <div className="flex items-center gap-2">
                  <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-gradient-to-br from-accent via-sky to-rose text-xs text-white">∞</span>
                  <div className="min-w-0">
                    <div className="truncate text-sm font-bold text-white">{p.title || p.goal || "未命名作品"}</div>
                    <div className="text-[11px] text-slate-500">
                      {p.template} · v{p.current_version} · {p.status || "draft"}
                    </div>
                  </div>
                </div>
                {p.description && <p className="mt-2 line-clamp-2 text-xs text-slate-400">{p.description}</p>}
                <div className="mt-3 flex flex-wrap gap-2">
                  <a href={`/agent?project=${p.id}`} className="rounded-md bg-accent/20 px-3 py-1 text-xs font-bold text-accent hover:bg-accent/30">进入工作台</a>
                  <a href={`/storygraph?project=${p.id}`} className="rounded-md bg-panel2 px-3 py-1 text-xs text-slate-300 hover:bg-white/5">剧情图</a>
                  <a href={`/worldplay?project=${p.id}`} className="rounded-md bg-panel2 px-3 py-1 text-xs text-slate-300 hover:bg-white/5">试玩</a>
                </div>
              </div>
            ))}
            {!projectsLoading && projects.length === 0 && (
              <div className="col-span-full rounded-2xl border border-dashed border-white/15 p-8 text-center text-sm text-slate-500">
                还没有作品，在上方输入一句创意点「🎬 新建作品」即可开始。
              </div>
            )}
          </div>
        </div>
      </section>

      {/* ===================== 能力 ===================== */}
      <section id="features" className="relative overflow-hidden py-20">
        <div className="absolute inset-0 -z-10 bg-night" />
        <div className="mx-auto max-w-6xl px-6">
          <div className="text-center">
            <h2 className="text-3xl font-black text-white sm:text-4xl">
              创作，驾驭于<span className="text-accent">一整个 OS</span>
            </h2>
            <p className="mx-auto mt-4 max-w-2xl text-slate-400">
              不只是单一工具，而是集合规划、生成、协作、试玩于一体的互动影视创作操作系统。
            </p>
          </div>

          <div className="mt-14 grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
            {[
              { icon: "🧠", t: "导演蓝图", d: "一句创意自动编排角色、关系与分数值节奏" },
              { icon: "🎨", t: "角色立绘", d: "差分头像与立绘生成，行为实时定制" },
              { icon: "🧩", t: "剧情图谱", d: "可视化剧情画布，分支触达观察" },
              { icon: "🕹️", t: "即时试玩", d: "选择即得反馈，验证可玩性与多结局闭环" },
            ].map((f) => (
              <div
                key={f.t}
                className="rounded-2xl border border-white/10 bg-panel p-6 transition-all duration-300 hover:-translate-y-1.5 hover:border-accent/40"
              >
                <div className="text-3xl">{f.icon}</div>
                <h3 className="mt-4 text-lg font-bold text-white">{f.t}</h3>
                <p className="mt-2 text-sm text-slate-400">{f.d}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ===================== 页脚 ===================== */}
      <footer className="border-t border-white/10 py-10 text-center text-sm text-slate-500">
        <div className="mx-auto flex max-w-6xl flex-col items-center justify-between gap-4 px-6 sm:flex-row">
          <span className="font-black tracking-widest text-white/80">
            <span className="text-accent">◆</span> YIWA · AI 互动影视创作 OS
          </span>
          <span>© {new Date().getFullYear()} YIWA Studio —— 让每个脑内故事都能被写进帧里</span>
        </div>
      </footer>
    </>
  );
}