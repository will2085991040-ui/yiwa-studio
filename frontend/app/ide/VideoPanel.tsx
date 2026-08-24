"use client";

// AI 互动影视编辑器核心：分镜拆镜头（整列拆镜）+ 生成视频 + 选项插入时间线 + 互动试播。
// 全部调用真实后端 API：storyboard breakdown/保存/生成视频；选项的出现时机(video_at_sec)随图持久化。
import { useCallback, useEffect, useRef, useState } from "react";
import {
  authenticatedFetch,
  generateStoryboardVideo,
  getStoryboardVideo,
  storyboardBreakdown,
} from "@/lib/api";
import { KIND_COLOR, KIND_LABEL } from "./workspace";

type Shot = {
  shot_no: number; duration_sec: number; scene_id: string; character_ids: string[];
  visual_description: string; shot_size: string; camera_movement: string;
  character_action: string; emotion: string; lighting: string; sound_effect: string;
  dialogue: string; generate_audio: boolean; storyboard_prompt: string;
  motion_prompt: string; link_from_previous: string; status: string;
};
type Storyboard = { node_id: string; synopsis: string; shots: Shot[]; metadata: Record<string, unknown> };
type Template = { shot_sizes: string[]; camera_movements: string[]; cost_per_second: number };
type Choice = { choice_id: string; text: string; next_node: string | null; video_at_sec?: number | null };
type Job = {
  job_id: string; node_id: string; status: string; duration_sec: number;
  cost_per_second: number; total_cost: number; seedance_director_prompt: string;
  video_url?: string; aspect_ratio?: string; provider?: string;
};

export default function VideoPanel({
  projectId,
  nodeId,
  nodeTitle,
  nodeKind,
  choices = [],
  nodeNameOf,
  onPickNode,
  onUpdateChoice,
}: {
  projectId: string;
  nodeId: string;
  nodeTitle: string;
  nodeKind: string;
  choices?: Choice[];
  nodeNameOf: (id: string) => string;
  onPickNode?: (id: string) => void;
  onUpdateChoice?: (nodeId: string, choiceId: string, patch: Partial<Choice>) => void;
}) {
  const [template, setTemplate] = useState<Template>({ shot_sizes: [], camera_movements: [], cost_per_second: 10 });
  const [sb, setSb] = useState<Storyboard | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [aspect, setAspect] = useState("16:9");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [sec, setSec] = useState(0);
  const raf = useRef<ReturnType<typeof setInterval> | null>(null);

  const totalSec = sb ? sb.shots.reduce((a, s) => a + (s.duration_sec || 0), 0) : 0;

  // 打开分镜的“自动载入”：即使该节点尚无 AI 分镜产物，也用剧情节点本身＋其选项
  // 生成一块可预览的分镜板（synopsis=场景名，每选项一块小短段），不让画面空白。
  const choicesRef = useRef<Choice[]>(choices);
  choicesRef.current = choices;
  const buildFallbackBoard = useCallback((): Storyboard => {
    const _choices = choicesRef.current;
    return {
      node_id: nodeId,
      synopsis: nodeTitle || nodeId || "（本场景）",
      shots: (_choices && _choices.length
        ? _choices
        : [{ choice_id: "c_continue", text: "继续播放本段剧情", next_node: null, video_at_sec: 6 }]
      ).map((c, i) => ({
        shot_no: i + 1,
        duration_sec: 6,
        scene_id: nodeId,
        character_ids: [],
        visual_description: `${nodeTitle} —— 镜头对白/剧情片段 ${i + 1}（选项：${c.text}）`,
        shot_size: "中景",
        camera_movement: "固定",
        character_action: "",
        emotion: "",
        lighting: "",
        sound_effect: "",
        dialogue: c.text,
        generate_audio: false,
        storyboard_prompt: `关键帧：${nodeTitle}，选项「${c.text}」后的画面`,
        motion_prompt: "",
        link_from_previous: i === 0 ? "—" : `镜 ${i + 1} 承接`,
        status: "draft",
      })),
      metadata: { auto_import_from_scene: true },
    };
  }, [nodeId, nodeTitle]);

  useEffect(() => {
    authenticatedFetch("/api/meta/storyboard-template").then((r) => r.json()).then(setTemplate).catch(() => {});
  }, []);

  const loadAll = useCallback(() => {
    if (!projectId || !nodeId) return;
    authenticatedFetch(`/api/projects/${projectId}/storyboard/${nodeId}`)
      .then((r) => (r.ok ? r.json() : { shots: [] }))
      .then((d: Storyboard | { shots?: never }) => {
        if (d && d.shots && d.shots.length) {
          setSb({ node_id: d.node_id, synopsis: d.synopsis, shots: d.shots, metadata: d.metadata ?? {} });
          setMsg((m) => (m && m.text.startsWith("已自动") ? m : m));
        } else {
          // 没有 AI 分镜产物 → 自动用剧情节点/选项拼一块可预览分镜板（不空白）
          const fb = buildFallbackBoard();
          setSb(fb);
          setMsg({ ok: true, text: "自动载入本节点剧情与选项，生成了可预览分镜板（未做 AI 拆镜）→ 点「一键拆镜」生成专业镜版" });
        }
      })
      .catch(() => {});
    getStoryboardVideo(projectId, nodeId).then((j) => setJob((j as Job).job_id ? (j as Job) : null)).catch(() => {});
  }, [projectId, nodeId, buildFallbackBoard]);

  useEffect(() => {
    loadAll();
    setPlaying(false);
    setSec(0);
  }, [loadAll]);

  useEffect(() => () => { if (raf.current) clearInterval(raf.current); }, []);

  const togglePlay = () => {
    if (!playing) {
      setSec(0);
      setPlaying(true);
      raf.current = setInterval(() => {
        setSec((s) => {
          const next = s + 0.5;
          if (next >= totalSec) { setPlaying(false); if (raf.current) clearInterval(raf.current); return totalSec; }
          return next;
        });
      }, 500);
    } else {
      setPlaying(false);
      if (raf.current) clearInterval(raf.current);
    }
  };

  const seg = (atSec: number) => Math.min(sb?.shots.length ?? 1, Math.max(1, Math.floor(atSec / Math.max(0.001, totalSec) * (sb?.shots.length ?? 1)) + 1));
  const activeShotNo = totalSec ? seg(sec) : 1;
  const visibleChoices = choices.filter((c) => (c.video_at_sec ?? null) !== null && c.video_at_sec! <= sec);

  const inputCls = "rounded-md bg-panel border border-white/10 px-2 py-1.5 text-sm text-slate-200 outline-none focus:border-accent";

  const doBreakdown = async () => {
    setBusy(true);
    setMsg(null);
    try {
      const d = (await storyboardBreakdown(projectId, nodeId, 4)) as unknown as Storyboard & { version: number };
      setSb({ node_id: d.node_id, synopsis: d.synopsis, shots: d.shots, metadata: d.metadata ?? {} });
      setMsg({ ok: true, text: "已在当前节点完成整列拆镜" });
    } catch (e) { setMsg({ ok: false, text: String((e as Error).message) }); }
    setBusy(false);
  };

  const setShot = (i: number, patch: Partial<Shot>) =>
    setSb((p) => (p ? { ...p, shots: p.shots.map((s, j) => (j === i ? { ...s, ...patch } : s)) } : p));

  const saveShots = async () => {
    if (!sb) return;
    const r = await authenticatedFetch(`/api/projects/${projectId}/storyboard/${nodeId}`, {
      method: "PUT",
      body: JSON.stringify({ storyboard: sb, change_reason: "IDE 分镜编辑" }),
    });
    const d = await r.json().catch(() => ({}));
    setMsg(r.ok ? { ok: true, text: `分镜已保存 v${d.version}` } : { ok: false, text: `保存失败 HTTP ${r.status}` });
  };

  const genVideo = async () => {
    setBusy(true);
    setMsg(null);
    try {
      const j = (await generateStoryboardVideo(projectId, nodeId, { aspect_ratio: aspect })) as unknown as Job;
      setJob(j);
      setMsg({ ok: true, text: `视频任务${(j.status === "done") ? "完成" : "已提交"}：${j.total_cost} 积分 / ${j.duration_sec}s · ${j.aspect_ratio === "9:16" ? "竖屏" : "横屏"}` });
    } catch (e) {
      const m = (e as Error).message || String(e);
      setMsg({ ok: false, text: `生成视频失败：${m}` });
      setJob(null);
    }
    setBusy(false);
  };

  return (
    <div className="flex h-full flex-col overflow-y-auto p-4 text-slate-200">
      {/* 当前节点 + 拆镜/视频动作 */}
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <span style={{ width: 10, height: 10, borderRadius: 3, background: KIND_COLOR[nodeKind] ?? "#64748b" }} />
        <span className="font-bold">{nodeTitle || nodeId}</span>
        <span className="rounded-full border border-white/10 bg-panel2 px-2 py-0.5 text-[10px] text-slate-400">{KIND_LABEL[nodeKind] ?? nodeKind}</span>
        <span className="ml-auto text-xs text-slate-400">{sb ? `v·${sb.shots.length} 镜头 · ${totalSec}s · ≈${Math.round(totalSec * (template.cost_per_second ?? 10))} 积分` : ""}</span>
        <button onClick={doBreakdown} disabled={busy} className="rounded-lg bg-violet-600/80 px-3 py-1 text-xs font-semibold hover:bg-violet-500 disabled:opacity-50">整列拆镜</button>
        <button onClick={saveShots} disabled={!sb} className="rounded-lg border border-white/10 bg-panel2 px-3 py-1 text-xs hover:bg-white/5">保存镜表</button>
        <label className="flex items-center gap-1 text-xs">
          画面
          <select value={aspect} onChange={(e) => setAspect(e.target.value)} className="rounded-lg bg-panel2 border border-white/10 px-1.5 py-1 text-xs">
            <option value="16:9">横 16:9</option><option value="9:16">竖 9:16</option>
          </select>
        </label>
        <button onClick={genVideo} disabled={busy || !sb} className="rounded-lg bg-amber-600/80 px-3 py-1 text-xs font-semibold hover:bg-amber-500 disabled:opacity-50">生成视频</button>
      </div>

      {msg && <p className={`mb-2 text-xs ${msg.ok ? "text-mint" : "text-rose-400"}`}>{msg.text}</p>}

      {/* 互动试播：分镜时间线 + 选项弹出 */}
      <div className="mb-3 rounded-xl border border-accent/30 bg-panel/40 p-3">
        <div className="mb-2 flex items-center justify-between">
          <span className="text-xs font-bold text-accent">互动试播（选项随视频在第 N 秒弹层，玩家点击后跳转）</span>
          <button onClick={togglePlay} className="rounded-md bg-accent/25 px-3 py-1 text-xs font-bold text-accent hover:bg-accent/35">
            {playing ? "⏸ 暂停" : "▶ 播放"}
          </button>
        </div>
        {/* 分镜画面导轨 */}
        <div className="relative mb-1 h-16 overflow-hidden rounded-lg border border-white/10 bg-[#14162a]">
          <div className="flex h-full">
            {(sb?.shots ?? []).map((s, i) => {
              const w = totalSec ? (s.duration_sec / totalSec) * 100 : 0;
              return (
                <div key={s.shot_no} className={`flex items-center justify-center overflow-hidden border-r border-white/10 px-1 text-center text-[9px] ${(i + 1) === activeShotNo ? "bg-accent/25" : ""}`} style={{ width: `${w}%` }}>
                  <div className="line-clamp-3">{s.visual_description || `镜 ${s.shot_no}`}</div>
                </div>
              );
            })}
          </div>
          {/* 播放进度头 */}
          {totalSec > 0 && (
            <div className="pointer-events-none absolute top-0 bottom-0 w-px bg-glow" style={{ left: `${(sec / totalSec) * 100}%` }} />
          )}
          <div className="absolute right-1 bottom-1 rounded bg-black/60 px-1.5 py-0.5 text-[10px] text-glow">{sec.toFixed(1)}s / {totalSec}s</div>
        </div>
        {/* 选项弹出层 */}
        <div className="relative min-h-[54px] rounded-lg border border-white/10 bg-black/40 p-2">
          {visibleChoices.length > 0 ? (
            <div className="space-y-1.5">
              <div className="text-[10px] text-amber-300">⏰ 选项在 {sec.toFixed(1)}s 出现——请玩家选择：</div>
              {visibleChoices.map((c) => (
                <button key={c.choice_id} onClick={() => { onPickNode?.(c.next_node ?? ""); }}
                  className="block w-full rounded-lg border border-accent/40 bg-accent/15 px-2 py-1.5 text-left text-xs text-accent hover:bg-accent/25">
                  {c.text} <span className="text-[10px] text-slate-400">→ {c.next_node ? nodeNameOf(c.next_node) : "?"}</span>
                </button>
              ))}
            </div>
          ) : (
            <div className="pt-2 text-center text-[11px] text-slate-500">
              {playing ? "播放中…" : "点击上方 ▶ 播放，按镜头顺序重现；设置选项的出现时机后将在该秒弹出。"}
            </div>
          )}
        </div>
      </div>

      {/* 选项插入时间线 */}
      <div className="mb-3 rounded-xl border border-white/10 bg-panel/40 p-3">
        <div className="mb-1 text-xs font-bold text-slate-300">选项插入影视画面（本节点 {choices.length} 个）</div>
        <p className="mb-2 text-[10px] text-slate-500">给每个选项填「出现时机」秒：播到该秒时弹层，玩家点击后沿该分支继续。留空 = 整个镜头播完再选。</p>
        {choices.length === 0 && <p className="text-[11px] text-slate-500">该节点还没有选项。在右侧检查器「选择/分支」里添加，再回来设置出现时机。</p>}
        <ul className="space-y-1">
          {choices.map((c) => (
            <li key={c.choice_id} className="flex items-center gap-2 rounded-md bg-black/30 border border-white/5 px-2 py-1 text-xs">
              <span className="flex-1 truncate">{c.text}</span>
              {c.next_node ? <span className="text-[10px] text-slate-500">→ {nodeNameOf(c.next_node)}</span> : null}
              <input
                type="number" min={0} step={0.5} placeholder="秒"
                value={c.video_at_sec ?? ""}
                onChange={(e) => onUpdateChoice?.(nodeId, c.choice_id, { video_at_sec: e.target.value === "" ? null : Math.max(0, Number(e.target.value)) })}
                className="w-16 rounded bg-panel border border-white/10 px-1 py-0.5 text-xs"
              />
              <span className="text-[10px] text-slate-500">秒出现</span>
            </li>
          ))}
        </ul>
      </div>

      {/* 分镜镜表（可编辑） */}
      <div className="mb-3">
        <div className="mb-1 flex items-center gap-2 text-xs font-bold text-slate-300">
          分镜镜表
          <input value={sb?.synopsis ?? ""} onChange={(e) => setSb((p) => (p ? { ...p, synopsis: e.target.value } : p))} placeholder="分镜梗概 synopsis" className={`${inputCls} flex-1 text-xs`} />
        </div>
        {(sb?.shots ?? []).length === 0 && <p className="py-3 text-center text-xs text-slate-500">尚未拆镜。点「整片拆镜」为整段剧情节点自动生成镜头。</p>}
        <div className="space-y-2">
          {(sb?.shots ?? []).map((s, i) => (
            <div key={s.shot_no} className="rounded-lg border border-white/10 bg-panel/50 p-2">
              <div className="mb-1 flex flex-wrap items-center gap-1.5 text-xs">
                <span className="font-bold text-violet-300">镜 {s.shot_no}</span>
                <select value={s.shot_size} onChange={(e) => setShot(i, { shot_size: e.target.value })} className="rounded bg-panel2 border border-white/10 px-1 py-0.5 text-xs">
                  {template.shot_sizes.map((x) => <option key={x} value={x}>{x}</option>)}
                </select>
                <select value={s.camera_movement} onChange={(e) => setShot(i, { camera_movement: e.target.value })} className="rounded bg-panel2 border border-white/10 px-1 py-0.5 text-xs">
                  {template.camera_movements.map((x) => <option key={x} value={x}>{x}</option>)}
                </select>
                <label className="text-[10px] text-slate-500">时长
                  <input type="number" min={1} max={30} value={s.duration_sec} onChange={(e) => setShot(i, { duration_sec: Math.max(1, Number(e.target.value) || 1) })} className="w-14 rounded bg-panel2 border border-white/10 px-1 py-0.5 text-xs" />s
                </label>
                <span className="text-[10px] text-slate-600">衔接 {s.link_from_previous}</span>
              </div>
              <div className="grid grid-cols-1 gap-1.5 md:grid-cols-2">
                <textarea value={s.visual_description} onChange={(e) => setShot(i, { visual_description: e.target.value })} rows={2} placeholder="画面描述" className={`${inputCls} text-xs`} />
                <textarea value={s.dialogue} onChange={(e) => setShot(i, { dialogue: e.target.value })} rows={2} placeholder="逐字对白（口型对齐）" className={`${inputCls} text-xs`} />
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* 生成的视频任务 */}
      {job && (
        <div className="rounded-xl border border-amber-600/40 bg-amber-500/5 p-3 text-xs">
          <div className="mb-1 flex items-center gap-2">
            <span className={`rounded px-2 py-0.5 text-[10px] ${job.status === "done" ? "bg-emerald-600/30 text-emerald-300" : job.status === "failed" ? "bg-rose-600/30 text-rose-300" : "bg-slate-700 text-slate-300"}`}>
              {job.status === "done" ? "已生成" : job.status === "failed" ? "失败" : "排队中"}
            </span>
            <span>{job.duration_sec}s</span><span>× {job.cost_per_second} 积分/s</span>
            <span className="font-bold text-amber-300">={job.total_cost} 积分</span>
            <span className="text-slate-500">{job.provider && job.provider !== "mock" ? "（真实渲染）" : "（mock：确定性计价）"}</span>
          </div>
          {job.video_url ? (
            <a href={job.video_url} target="_blank" rel="noreferrer" className="inline-block max-w-full truncate rounded bg-emerald-600/20 px-3 py-1.5 text-emerald-300 hover:bg-emerald-600/30">▶ 查看视频</a>
          ) : job.status === "queued" ? (
            <p className="text-amber-300/80">视频仍在渲染中，可稍后再看或回到画布做别的。</p>
          ) : (
            <p className="text-slate-500">未配置真实视频供应商时按 mock 计价占位（不真实渲染）。可到「设置」填 Key 后重新生成。</p>
          )}
        </div>
      )}
    </div>
  );
}