"use client";

// C 分节点小画布：选中剧情节点后，在独立小画布里为该节点做画面制作。
// 数据源 = GET  /api/projects/{id}/nodes/{nodeId}/canvas
//           POST /api/projects/{id}/nodes/{nodeId}/images
import { useCallback, useEffect, useState } from "react";
import {
  createNodeImage,
  generateStoryboardVideo,
  getNodeCanvas,
  storyboardBreakdown,
  type NodeCanvasOut,
} from "@/lib/api";

type Props = {
  open: boolean;
  projectId: string;
  nodeId: string;
  nodeTitle: string;
  onClose: () => void;
};
const ASPECTS = ["9:16", "16:9", "1:1"] as const;

export default function NodeCanvasModal({ open, projectId, nodeId, nodeTitle, onClose }: Props) {
  const [data, setData] = useState<NodeCanvasOut | null>(null);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [prompt, setPrompt] = useState("");
  const [style, setStyle] = useState("");
  const [aspect, setAspect] = useState<(typeof ASPECTS)[number]>("9:16");
  const [videoBusy, setVideoBusy] = useState(false);
  const [videoMsg, setVideoMsg] = useState("");

  const load = useCallback(async () => {
    if (!open || !projectId || !nodeId) return;
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
  }, [open, projectId, nodeId]);

  useEffect(() => {
    setData(null);
    setPrompt("");
    void load();
  }, [load]);

  const generate = async () => {
    if (busy || !prompt.trim()) return;
    setBusy(true);
    setErr("");
    try {
      await createNodeImage(projectId, nodeId, { prompt: prompt.trim(), style, aspect });
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
      await generateStoryboardVideo(projectId, nodeId, { aspect_ratio: aspect, ref_image: refImage, style });
      setVideoMsg("视频任务已提交（首帧已锁定，人物/画面一致）。请刷新查看结果。");
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
      const img = await createNodeImage(projectId, nodeId, { prompt: usePrompt, style, aspect });
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

  if (!open) return null;

  const styles = data?.styles ?? [];
  const shots = ((data?.storyboard as { shots?: unknown[] } | undefined)?.shots) ?? [];
  const images = data?.images ?? [];
  const video = data?.video as { status?: string; video_url?: string } | null | undefined;

  return (
    <div
      className="fixed inset-0 z-[80] flex items-center justify-center bg-black/60 p-6"
      onClick={(ev) => { if (ev.target === ev.currentTarget) onClose(); }}
    >
      <div className="flex max-h-[86vh] w-[780px] flex-col rounded-2xl border border-white/10 bg-[#151730] text-slate-100 shadow-2xl">
        <div className="flex items-center justify-between border-b border-white/10 px-4 py-3">
          <div>
            <div className="text-[10px] uppercase tracking-widest text-slate-500">分节点小画布</div>
            <div className="text-sm font-bold">{nodeTitle} <span className="text-slate-500">({nodeId})</span></div>
          </div>
          <button onClick={onClose} className="rounded-lg border border-white/10 bg-panel2 px-2.5 py-1.5 text-xs hover:bg-white/5">✕ 关闭</button>
        </div>

        <div className="border-b border-white/5 bg-white/[0.02] px-4 py-1.5 text-[11px] leading-relaxed text-slate-400">
          制作流程：选风格 → 填画面 → 🎨 生成画面 → 点每张图「🎬 用此图做视频」自动以它为<span  className="text-accent">首帧</span>（人物/画面一致）→ 无分镜时<span className="text-accent">自动拆镜</span> → 刷新区查看视频。
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto p-4">
          {err && <div className="mb-3 rounded-lg border border-rose-400/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">{err}</div>}
          {loading && <div className="py-10 text-center text-sm text-slate-400">加载节点画布…</div>}

          {!loading && (
            <div className="space-y-4">
              {shots.length > 0 && (
                <section>
                  <div className="mb-1 text-[10px] font-bold uppercase tracking-widest text-slate-500">分镜镜头（{shots.length}）</div>
                  <div className="flex flex-wrap gap-2">
                    {shots.map((s: unknown, i: number) => (
                      <span key={i} className="rounded-md border border-white/10 bg-panel2 px-2 py-1 text-[11px] text-slate-300">
                        #{i + 1} {(s as { description?: string })?.description ?? (s as { prompt?: string })?.prompt ?? ""}
                      </span>
                    ))}
                  </div>
                </section>
              )}

              <section>
                <div className="mb-1 text-[10px] font-bold uppercase tracking-widest text-slate-500">画面制作（文生图 → 图生视频）</div>
                <div className="flex flex-wrap items-center gap-2">
                  <select
                    value={style}
                    onChange={(e) => setStyle(e.target.value)}
                    className="rounded-lg border border-white/10 bg-panel2 px-2 py-1.5 text-xs"
                    title="画面风格"
                  >
                    {styles.map((s) => (
                      <option key={s.key} value={s.key}>{s.label ?? s.key}</option>
                    ))}
                  </select>
                  <select
                    value={aspect}
                    onChange={(e) => setAspect(e.target.value as (typeof ASPECTS)[number])}
                    className="rounded-lg border border-white/10 bg-panel2 px-2 py-1.5 text-xs"
                    title="画布比例"
                  >
                    {ASPECTS.map((a) => <option key={a} value={a}>{a}</option>)}
                  </select>
                </div>
                <textarea
                  value={prompt}
                  onChange={(e) => setPrompt(e.target.value)}
                  placeholder="描述这一节点该出什么画面，如：背对镜头的少女站在雨中的霓虹街头…"
                  className="mt-2 h-16 w-full resize-none rounded-lg border border-white/10 bg-panel2 px-3 py-2 text-xs outline-none focus:border-accent/60"
                />
                <div className="mt-2 flex items-center gap-2">
                  <button
                    onClick={generate}
                    disabled={busy || !prompt.trim()}
                    className="rounded-lg bg-accent/20 px-3 py-1.5 text-xs font-bold text-accent hover:bg-accent/30 disabled:opacity-40"
                  >
                    {busy ? "● 生成中…" : "🎨 为该节点生成画面"}
                  </button>
                  <button
                    onClick={() => { void oneShot(); }}
                    disabled={busy || videoBusy}
                    className="rounded-lg bg-emerald-500/20 px-3 py-1.5 text-xs font-bold text-emerald-300 hover:bg-emerald-500/30 disabled:opacity-40"
                    title="一键：文生图 → 锁定首帧 → 自动拆镜 → 生成视频"
                  >
                    {videoBusy || busy ? "● 制作中…" : "⚡ 一键成片"}
                  </button>
                </div>
              </section>

              <section>
                <div className="mb-1 text-[10px] font-bold uppercase tracking-widest text-slate-500">节点图片（{images.length}）</div>
                {images.length === 0 ? (
                  <p className="text-[11px] text-slate-500">还没有为该节点生成的画面。</p>
                ) : (
                  <div className="grid grid-cols-3 gap-2">
                    {images.map((im, i) => (
                      <div key={i} className="overflow-hidden rounded-lg border border-white/10">
                        <img src={im.url} alt={im.prompt} className="aspect-[9/16] w-full object-cover" />
                        <div className="px-1.5 py-1 text-[9px] text-slate-400">{im.style || "默认"} · {im.aspect || "9:16"}</div>
                        <button
                          onClick={() => { void makeVideo(im.url); }}
                          disabled={videoBusy}
                          className="block w-full border-t border-white/10 bg-accent/15 py-1 text-center text-[10px] font-bold text-accent hover:bg-accent/25 disabled:opacity-40"
                          title="用这张图作为首帧，为该节点生成视频（保证人物/画面一致）"
                        >{videoBusy ? "● 生成中…" : "🎬 用此图做视频"}</button>
                      </div>
                    ))}
                  </div>
                )}
              </section>

              <section>
                <div className="mb-1 flex items-center justify-between text-[10px] font-bold uppercase tracking-widest text-slate-500">
                  视频任务
                  <button onClick={() => { void load(); }} className="rounded border border-white/10 bg-panel2 px-1.5 py-0.5 text-[10px] font-normal normal-case text-slate-300 hover:bg-white/5">⟳ 刷新</button>
                </div>
                {videoMsg && !videoBusy && (
                  <div className="mb-1 rounded-lg border border-accent/30 bg-accent/10 px-2 py-1 text-[10px] text-accent">{videoMsg}</div>
                )}
                {videoBusy && (
                  <div className="mb-1 rounded-lg border border-accent/30 bg-accent/10 px-2 py-1 text-[10px] text-accent">视频生成中…（可在主画布「分镜视频」跟进）</div>
                )}
                {video ? (
                  <div className="flex items-center gap-2 text-[11px] text-slate-300">
                    <span className={`rounded px-1.5 py-0.5 text-[10px] ${video.status === "done" ? "bg-emerald-500/20 text-emerald-300" : "bg-amber-500/20 text-amber-300"}`}>
                      {video.status ?? "queued"}
                    </span>
                    {video.video_url ? <a href={video.video_url} target="_blank" rel="noreferrer" className="text-accent underline">查视频</a> : <span>该节点暂无完成的视频</span>}
                  </div>
                ) : (
                  <p className="text-[11px] text-slate-500">该节点暂无视频任务（可在主画布「分镜视频」生成）。</p>
                )}
              </section>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}