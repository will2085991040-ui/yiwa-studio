"use client";

// C 剧情小画布 · 独立全屏页面：专注为一个剧情节点 文生图 → 图生视频 → 产物入资产。
// 用法：/node-canvas?project={projectId}&node={nodeId}
// 数据源复用分节点小画布接口（与 IDE 弹窗一致），另支持更宽松的布局与去生成视频。
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  authenticatedFetch,
  createNodeImage,
  generateStoryboardVideo,
  getNodeCanvas,
  portraitVideoRef,
  storyboardBreakdown,
  type NodeCanvasOut,
} from "@/lib/api";

const ASPECTS = ["9:16", "16:9", "1:1"] as const;

function useQuery() {
  const [q, setQ] = useState<{ project: string; node: string }>({ project: "", node: "" });
  useEffect(() => {
    const p = new URLSearchParams(window.location.search);
    setQ({ project: p.get("project") ?? "", node: p.get("node") ?? "" });
  }, []);
  return q;
}

// 给节点生成图命名（写入当前 storyboard 梗概，用户可改），并在导出时允许自定义文件名
function slug(s: string) {
  return s.trim().replace(/[\\/:*?"<>|]+/g, "_").replace(/\s+/g, "-").slice(0, 40) || "node";
}

export default function NodeCanvasPage() {
  const { project: projectId, node: nodeId } = useQuery();
  const [data, setData] = useState<NodeCanvasOut | null>(null);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [prompt, setPrompt] = useState("");
  const [style, setStyle] = useState("");
  const [styleCustom, setStyleCustom] = useState(false);
  const [customStyle, setCustomStyle] = useState("");
  const [aspect, setAspect] = useState<(typeof ASPECTS)[number]>("9:16");
  const [videoBusy, setVideoBusy] = useState(false);
  const [videoMsg, setVideoMsg] = useState("");
  const [nodeTitle, setNodeTitle] = useState(nodeId);

  const effStyle = () => (styleCustom ? customStyle.trim() : style);

  const load = useCallback(async () => {
    if (!projectId || !nodeId) return;
    setLoading(true);
    setErr("");
    try {
      const d = await getNodeCanvas(projectId, nodeId);
      setData(d);
      setStyle(d.styles?.[0]?.key ?? "");
    } catch (e) {
      setErr(String((e as Error).message ?? e));
    } finally {
      setLoading(false);
    }
  }, [projectId, nodeId]);

  const open = !!projectId && !!nodeId;

  useEffect(() => {
    if (!open) return;
    setData(null);
    setPrompt("");
    void load();
  }, [open, load]);

  const generate = async () => {
    if (busy || !prompt.trim()) return;
    setBusy(true);
    setErr("");
    try {
      await createNodeImage(projectId, nodeId, { prompt: prompt.trim(), style: effStyle(), aspect });
      await load();
    } catch (e) {
      setErr(String((e as Error).message ?? e));
    } finally {
      setBusy(false);
    }
  };

  const makeVideo = async (refImage: string) => {
    if (videoBusy) return;
    setVideoBusy(true);
    setVideoMsg("");
    setErr("");
    const hasShots = ((data?.storyboard as { shots?: unknown[] } | undefined)?.shots?.length ?? 0) > 0;
    try {
      if (!hasShots) {
        setVideoMsg("自动拆镜中…");
        await storyboardBreakdown(projectId, nodeId, 4);
        setVideoMsg("拆镜完成，正在用这张图生成视频…");
      }
      await generateStoryboardVideo(projectId, nodeId, { aspect_ratio: aspect, ref_image: refImage, style: effStyle() });
      setVideoMsg("视频任务已提交（首帧已锁定，人物/画面一致）。产物已存入资产。");
      await load();
    } catch (e) {
      setErr(String((e as Error).message ?? e));
    } finally {
      setVideoBusy(false);
    }
  };

  const oneShot = async () => {
    if (busy || videoBusy) return;
    setErr("");
    const usePrompt =
      prompt.trim() ||
      (((data?.storyboard as { synopsis?: string } | undefined)?.synopsis)?.slice(0, 80)) ||
      "该剧情节点的关键画面";
    setBusy(true);
    setVideoMsg("一键成片：先文生图，再锁定它做首帧生成视频…");
    try {
      const img = await createNodeImage(projectId, nodeId, { prompt: usePrompt, style: effStyle(), aspect });
      setPrompt(usePrompt);
      await load();
      setBusy(false);
      await makeVideo(img?.url || "");
    } catch (e) {
      setErr(String((e as Error).message ?? e));
      setBusy(false);
      setVideoMsg("");
    }
  };

  const download = (url: string, base: string) => {
    const a = document.createElement("a");
    a.href = url;
    a.download = `${slug(base || nodeId)}.png`;
    a.target = "_blank";
    a.rel = "noreferrer";
    document.body.appendChild(a);
    a.click();
    a.remove();
  };

  if (!nodeId) {
    return (
      <main className="min-h-screen bg-[#0c0a22] px-6 py-10 text-slate-100">
        <div className="mx-auto max-w-xl text-center">
          <h1 className="text-xl font-bold">节点小画布（独立全屏）</h1>
          <p className="mt-3 text-sm text-slate-400">缺少 node 参数。请从剧情画布上方「🎨 小画布（全屏）」进入。</p>
          <Link href="/" className="mt-6 inline-block rounded-lg bg-violet-600 px-4 py-2 text-sm hover:bg-violet-500">回首页</Link>
        </div>
      </main>
    );
  }

  const styles = data?.styles ?? [];
  const shots = ((data?.storyboard as { shots?: unknown[] } | undefined)?.shots) ?? [];
  const images = data?.images ?? [];
  const video = data?.video as { status?: string; video_url?: string } | null | undefined;

  return (
    <main className="min-h-screen bg-[#0c0a22] text-slate-100">
      <header className="sticky top-0 z-20 flex flex-wrap items-center gap-3 border-b border-white/10 bg-[#0c0a22]/95 px-5 py-3 backdrop-blur">
        <Link href="/" className="text-sm text-slate-500 hover:text-white">← 首页</Link>
        {projectId && <Link href={`/storyboard?project=${encodeURIComponent(projectId)}`} className="text-sm text-slate-500 hover:text-white">↗ 分镜/视频</Link>}
        <div>
          <div className="text-[10px] uppercase tracking-widest text-slate-500">节点小画布 · 独立全屏</div>
          <div className="text-sm font-bold">{nodeTitle || nodeId} <span className="text-slate-500">({nodeId})</span></div>
        </div>
        <input
          value={nodeTitle}
          onChange={(e) => setNodeTitle(e.target.value)}
          placeholder="给这个节点画面起个名字"
          className="ml-2 w-56 rounded-lg border border-white/10 bg-white/5 px-2 py-1.5 text-xs"
          title="画面名称（生成时作为资产命名前缀）"
        />
        <button onClick={() => { void load(); }} className="ml-auto rounded-lg border border-white/10 bg-white/5 px-2.5 py-1.5 text-xs hover:bg-white/10">⟳ 刷新</button>
      </header>

      <div className="mx-auto grid max-w-6xl grid-cols-1 gap-5 p-5 lg:grid-cols-[1fr_340px]">
        {/* 左：制作区 */}
        <div className="space-y-4">
          {err && <div className="rounded-lg border border-rose-400/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">{err}</div>}
          {loading && <div className="py-16 text-center text-sm text-slate-400">加载节点画布…</div>}

          {!loading && (<>
            {/* 制作面板 */}
            <section className="rounded-2xl border border-white/10 bg-white/[0.02] p-4">
              <div className="mb-2 text-[10px] font-bold uppercase tracking-widest text-slate-500">画面制作（文生图 → 图生视频）</div>
              <div className="flex flex-wrap items-center gap-2">
                <select
                  value={styleCustom ? "__custom__" : style}
                  onChange={(e) => {
                    if (e.target.value === "__custom__") setStyleCustom(true);
                    else { setStyleCustom(false); setStyle(e.target.value); }
                  }}
                  className="rounded-lg border border-white/10 bg-white/5 px-2 py-1.5 text-xs"
                  title="画面风格：预设或自定义渲染关键词"
                >
                  {styles.map((s) => <option key={s.key} value={s.key}>{s.label ?? s.key}</option>)}
                  <option value="__custom__">✍️ 自定义…</option>
                </select>
                {styleCustom && (
                  <input
                    value={customStyle}
                    onChange={(e) => setCustomStyle(e.target.value)}
                    placeholder="赛璐璐，赛伟霓虹，微距特写…"
                    className="w-56 rounded-lg border border-white/10 bg-white/5 px-2 py-1.5 text-xs"
                  />
                )}
                <select
                  value={aspect}
                  onChange={(e) => setAspect(e.target.value as (typeof ASPECTS)[number])}
                  className="rounded-lg border border-white/10 bg-white/5 px-2 py-1.5 text-xs"
                >
                  {ASPECTS.map((a) => <option key={a} value={a}>{a}</option>)}
                </select>
              </div>
              <textarea
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                placeholder="描述这一节点该出什么画面，如：背对镜头的少女站在雨中的霓虹街头…"
                className="mt-2 h-20 w-full resize-none rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-xs outline-none focus:border-violet-400/60"
              />
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <button onClick={generate} disabled={busy || !prompt.trim()}
                  className="rounded-lg bg-violet-500/20 px-3 py-1.5 text-xs font-bold text-violet-300 hover:bg-violet-500/30 disabled:opacity-40">
                  {busy ? "● 生成中…" : "🎨 生成画面"}
                </button>
                <button onClick={() => { void oneShot(); }} disabled={busy || videoBusy}
                  className="rounded-lg bg-emerald-500/20 px-3 py-1.5 text-xs font-bold text-emerald-300 hover:bg-emerald-500/30 disabled:opacity-40"
                  title="一键：文生图 → 图生视频">
                  {videoBusy || busy ? "● 制作中…" : "⚡ 一键成片"}
                </button>
                <Link href={`/storyboard?project=${encodeURIComponent(projectId)}`}
                  className="rounded-lg border border-white/10 bg-white/5 px-3 py-1.5 text-xs text-slate-300 hover:bg-white/10">
                  ↗ 去分镜/全部视频
                </Link>
              </div>
            </section>

            {/* 节点图片 */}
            <section className="rounded-2xl border border-white/10 bg-white/[0.02] p-4">
              <div className="mb-2 text-[10px] font-bold uppercase tracking-widest text-slate-500">节点图片（{images.length}）· 存入资产</div>
              {images.length === 0 ? (
                <p className="text-[11px] text-slate-500">还没有为该节点生成的画面。</p>
              ) : (
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 md:grid-cols-4">
                  {images.map((im, i) => (
                    <div key={i} className="overflow-hidden rounded-lg border border-white/10">
                      <img src={im.url} alt={im.prompt} className="aspect-[9/16] w-full object-cover" loading="lazy" />
                      <div className="px-1.5 py-1 text-[9px] text-slate-400">{im.style || "默认"} · {im.aspect || "9:16"}</div>
                      <div className="flex">
                        <button
                          onClick={() => { void makeVideo(im.url); }} disabled={videoBusy}
                          className="flex-1 border-t border-white/10 bg-violet-500/15 py-1 text-center text-[10px] font-bold text-violet-300 hover:bg-violet-500/25 disabled:opacity-40"
                          title="用这张图作为首帧，为该节点生成视频（人物与画面一致）">🎬 做视频</button>
                        <button
                          onClick={() => download(im.url, slug(`${nodeTitle}`))}
                          className="border-t border-l border-white/10 bg-white/5 py-1 px-2 text-[10px] text-slate-300 hover:bg-white/10"
                          title="下载这张图">⬇</button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </section>

            {/* 视频任务 */}
            <section className="rounded-2xl border border-white/10 bg-white/[0.02] p-4">
              <div className="mb-1 text-[10px] font-bold uppercase tracking-widest text-slate-500">视频任务</div>
              {videoMsg && !videoBusy && <div className="mb-1 rounded-lg border border-violet-400/30 bg-violet-500/10 px-2 py-1 text-[10px] text-violet-300">{videoMsg}</div>}
              {videoBusy && <div className="mb-1 rounded-lg border border-violet-400/30 bg-violet-500/10 px-2 py-1 text-[10px] text-violet-300">视频生成中…（可在「分镜/视频」跟进）</div>}
              {video ? (
                <div className="flex items-center gap-2 text-[11px] text-slate-300">
                  <span className={`rounded px-1.5 py-0.5 text-[10px] ${video.status === "done" ? "bg-emerald-500/20 text-emerald-300" : "bg-amber-500/20 text-amber-300"}`}>{video.status ?? "queued"}</span>
                  {video.video_url ? <a href={video.video_url} target="_blank" rel="noreferrer" className="text-violet-300 underline">查看视频</a> : <span>该节点暂无完成的视频</span>}
                </div>
              ) : (
                <p className="text-[11px] text-slate-500">该节点暂无视频任务。</p>
              )}
            </section>
          </>)}
        </div>

        {/* 右栏：分镜 + 立绘首帧 */}
        <aside className="space-y-4">
          <section className="rounded-2xl border border-white/10 bg-white/[0.02] p-4">
            <div className="mb-1 text-[10px] font-bold uppercase tracking-widest text-slate-500">分镜镜头（{shots.length}）</div>
            {shots.length === 0 ? (
              <p className="text-[11px] text-slate-500">暂无镜头，可在「一键成片」时自动拆镜。</p>
            ) : (
              <div className="space-y-1.5">
                {shots.map((s, i) => (
                  <div key={i} className="rounded-md border border-white/10 bg-white/5 px-2 py-1 text-[10px] text-slate-300">
                    #{i + 1} {(s as { description?: string })?.description ?? (s as { prompt?: string })?.prompt ?? ""}
                  </div>
                ))}
              </div>
            )}
          </section>
          <CharacterFirstFrame projectId={projectId} nodeId={nodeId} aspect={aspect} effStyle={effStyle} onMessage={(m) => setVideoMsg(m)} />
        </aside>
      </div>
    </main>
  );
}

// 右栏：选一个角色，用其立绘直接去做图生视频（人物一致性）
function CharacterFirstFrame({ projectId, nodeId, aspect, effStyle, onMessage }: {
  projectId: string; nodeId: string; aspect: (typeof ASPECTS)[number]; effStyle: () => string; onMessage: (m: string) => void;
}) {
  const [chars, setChars] = useState<{ character_id: string; name: string }[]>([]);
  const [charId, setCharId] = useState("");
  const [ref, setRef] = useState<{ ref_image: string } | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!projectId) return;
    authenticatedFetch(`/api/projects/${projectId}/characters`).then((r) => (r.ok ? r.json() : [])).then((cs) => {
      const arr = Array.isArray(cs) ? cs : [];
      setChars(arr);
      if (arr.length) setCharId(arr[0].character_id);
    }).catch(() => setChars([]));
  }, [projectId]);

  useEffect(() => {
    if (!projectId || !charId) { setRef(null); return; }
    portraitVideoRef(projectId, charId).then((d) => setRef(d && d.has_portrait ? d : null)).catch(() => setRef(null));
  }, [projectId, charId]);

  const go = async () => {
    if (busy || !ref?.ref_image) return;
    setBusy(true);
    try {
      await generateStoryboardVideo(projectId, nodeId, { aspect_ratio: aspect, ref_image: ref.ref_image, style: effStyle() });
      onMessage("已用角色立绘作首帧生成视频（人物一致）。请在「分镜/视频」跟进结果。");
    } catch (e) {
      onMessage(String((e as Error).message ?? e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="rounded-2xl border border-white/10 bg-white/[0.02] p-4">
      <div className="mb-1 text-[10px] font-bold uppercase tracking-widest text-slate-500">角色立绘做首帧（人物不变）</div>
      <select value={charId} onChange={(e) => setCharId(e.target.value)} className="w-full rounded-lg border border-white/10 bg-white/5 px-2 py-1.5 text-xs">
        <option value="">不使用</option>
        {chars.map((c) => <option key={c.character_id} value={c.character_id}>{c.name}</option>)}
      </select>
      <button
        onClick={() => { void go(); }}
        disabled={busy || !ref?.ref_image}
        className="mt-2 w-full rounded-lg bg-violet-500/20 px-3 py-1.5 text-xs font-bold text-violet-300 hover:bg-violet-500/30 disabled:opacity-40"
        title="以该角色立绘为首帧，为该节点生成视频（保证人物与画面一致）"
      >
        {busy ? "● 生成中…" : (ref ? "🎬 用立绘做视频" : "（该角色暂无立绘）")}
      </button>
    </section>
  );
}