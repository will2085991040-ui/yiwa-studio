"use client";

import { useEffect, useState } from "react";
import { authenticatedFetch } from "@/lib/api";

type TShot = {
  shot_no: number;
  duration_sec: number;
  scene_id: string;
  character_ids: string[];
  visual_description: string;
  shot_size: string;
  camera_movement: string;
  character_action: string;
  emotion: string;
  lighting: string;
  sound_effect: string;
  dialogue: string;
  generate_audio: boolean;
  storyboard_prompt: string;
  motion_prompt: string;
  link_from_previous: string;
  status: string;
};
type TStoryboard = { node_id: string; synopsis: string; shots: TShot[]; metadata: Record<string, unknown> };
type TView = { version: number; shot_prompts: Record<string, string>; seedance_prompt: string };
type TJob = {
  job_id: string; node_id: string; status: string; duration_sec: number;
  cost_per_second: number; total_cost: number; seedance_director_prompt: string;
  video_url?: string; aspect_ratio?: string; provider?: string;
};
type TNode = { node_id: string; title: string; kind: string; summary?: string };
type TTemplate = { shot_sizes: string[]; camera_movements: string[]; cost_per_second: number };

export default function StoryboardPage() {
  const [projectId, setProjectId] = useState("");
  const [nodes, setNodes] = useState<TNode[]>([]);
  const [nodeId, setNodeId] = useState("");
  const [template, setTemplate] = useState<TTemplate>({ shot_sizes: [], camera_movements: [], cost_per_second: 10 });
  const [sb, setSb] = useState<TStoryboard | null>(null);
  const [view, setView] = useState<TView | null>(null);
  const [job, setJob] = useState<TJob | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [aspect, setAspect] = useState("16:9");
  const [batching, setBatching] = useState(false);

  useEffect(() => {
    setProjectId(new URLSearchParams(window.location.search).get("project") ?? "");
    authenticatedFetch("/api/meta/storyboard-template").then((r) => r.json()).then((t) => setTemplate(t)).catch(() => {});
  }, []);

  useEffect(() => {
    if (!projectId) return;
    authenticatedFetch(`/api/projects/${projectId}/storygraph`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((g: { graph?: { nodes?: TNode[] }; nodes?: TNode[] }) => {
        const list = (g.graph?.nodes ?? g.nodes ?? []).filter((n) => n.kind !== "ending");
        setNodes(list);
        if (list.length) setNodeId(list[0].node_id);
      })
      .catch(() => setNodes([]));
  }, [projectId]);

  useEffect(() => {
    if (!projectId || !nodeId) return;
    authenticatedFetch(`/api/projects/${projectId}/storyboard/${nodeId}`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((d: TStoryboard & TView) => {
        setSb({ node_id: d.node_id, synopsis: d.synopsis, shots: d.shots, metadata: d.metadata ?? {} });
        setView({ version: d.version, shot_prompts: d.shot_prompts, seedance_prompt: d.seedance_prompt });
      })
      .catch(() => {});
    authenticatedFetch(`/api/projects/${projectId}/storyboard/${nodeId}/video`)
      .then((r) => r.json())
      .then((j: TJob) => setJob(j.job_id ? j : null))
      .catch(() => {});
  }, [projectId, nodeId]);

  if (!sb) {
    return (
      <main className="min-h-screen bg-slate-950 px-6 py-10 text-slate-100">
        <div className="mx-auto max-w-4xl">
          <a href="/" className="text-sm text-slate-500 hover:text-white">← 首页</a>
          <h1 className="mt-4 text-2xl font-bold">分镜 / 视频</h1>
          <p className="mt-4 text-slate-400">{projectId ? (nodes.length ? "请选择剧情节点。" : "该项目还没有剧情图，请先在剧情画布建节点。") : "缺少 project 参数。"}</p>
          <div className="mt-6 space-x-2">
            {nodes.map((n) => (
              <button key={n.node_id} onClick={() => setNodeId(n.node_id)} className="rounded border border-slate-700 px-3 py-1.5 text-sm hover:bg-slate-800">
                {n.title || n.node_id}
              </button>
            ))}
          </div>
        </div>
      </main>
    );
  }

  const setShot = (i: number, patch: Partial<TShot>) =>
    setSb((p) => (p ? { ...p, shots: p.shots.map((s, j) => (j === i ? { ...s, ...patch } : s)) } : p));

  const breakdown = async () => {
    const r = await authenticatedFetch(`/api/projects/${projectId}/storyboard/${nodeId}/breakdown`, {
      method: "POST", body: JSON.stringify({ requested_shots: 4 }),
    });
    const d = await r.json();
    setSb({ node_id: d.node_id, synopsis: d.synopsis, shots: d.shots, metadata: d.metadata ?? {} });
    setView({ version: d.version, shot_prompts: d.shot_prompts, seedance_prompt: d.seedance_prompt });
    setMsg({ ok: true, text: "已自动拆镜（mock）" });
  };

  const save = async () => {
    const r = await authenticatedFetch(`/api/projects/${projectId}/storyboard/${nodeId}`, {
      method: "PUT",
      body: JSON.stringify({ storyboard: sb, change_reason: "分镜手动编辑" }),
    });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) setMsg({ ok: false, text: d?.error?.message || `HTTP ${r.status}` });
    else {
      setView({ version: d.version, shot_prompts: d.shot_prompts, seedance_prompt: d.seedance_prompt });
      setMsg({ ok: true, text: `已保存 v${d.version}` });
    }
  };

  const genVideo = async () => {
    const r = await authenticatedFetch(`/api/projects/${projectId}/storyboard/${nodeId}/video`, {
      method: "POST", body: JSON.stringify({ aspect_ratio: aspect }),
    });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) setMsg({ ok: false, text: d?.error?.message || `HTTP ${r.status}` });
    else {
      setJob(d);
      setMsg({ ok: true, text: `视频任务完成（mock）：${d.total_cost} 积分 / ${d.duration_sec}s · ${aspect === "9:16" ? "竖屏" : "横屏"}` });
    }
  };

  // 整条剧情链批量拆镜：对每个非 ending 节点跑一遍 AI 拆镜（当前为确定性 mock）
  const batchBreakdown = async () => {
    setBatching(true);
    setMsg({ ok: true, text: "正在为整条剧情链拆镜…" });
    let ok = 0;
    let fail = 0;
    for (const n of nodes) {
      try {
        const r = await authenticatedFetch(`/api/projects/${projectId}/storyboard/${n.node_id}/breakdown`, {
          method: "POST", body: JSON.stringify({ requested_shots: 4 }),
        });
        if (r.ok) ok += 1;
        else fail += 1;
      } catch {
        fail += 1;
      }
    }
    setBatching(false);
    setMsg({ ok: fail === 0, text: `整链拆镜完成：成功 ${ok} 个节点${fail ? `，失败 ${fail} 个` : ""}` });
  };

  const totalSec = sb.shots.reduce((acc, s) => acc + (s.duration_sec || 0), 0);

  return (
    <main className="min-h-screen bg-slate-950 text-slate-100">
      <header className="flex items-center gap-3 border-b border-slate-800 px-6 py-3">
        <a href="/" className="text-sm text-slate-500 hover:text-white">← 首页</a>
        {projectId && <a href={`/agent?project=${projectId}`} className="text-sm text-slate-500 hover:text-white">← 工作台</a>}
        <h1 className="text-lg font-semibold">分镜 / 视频</h1>
        <select value={nodeId} onChange={(e) => setNodeId(e.target.value)} className="ml-2 rounded bg-slate-800 px-2 py-1 text-sm">
          {nodes.map((n) => <option key={n.node_id} value={n.node_id}>{n.title || n.node_id}</option>)}
        </select>
        <button onClick={breakdown} className="rounded bg-violet-600 px-3 py-1.5 text-sm hover:bg-violet-500">AI 拆镜</button>
        <button onClick={batchBreakdown} disabled={batching} className="rounded bg-violet-600/50 px-3 py-1.5 text-sm hover:bg-violet-500 disabled:opacity-50">
          {batching ? "整链拆镜中…" : "整链拆镜"}
        </button>
        <button onClick={save} className="rounded bg-emerald-600 px-3 py-1.5 text-sm hover:bg-emerald-500">保存</button>
        <span className="ml-auto text-sm text-slate-400">{view ? `v${view.version}` : ""} · 总时长 {totalSec}s · 预估 {Math.round(totalSec) * template.cost_per_second} 积分</span>
        <label className="flex items-center gap-1 text-sm text-slate-300">
          画面
          <select value={aspect} onChange={(e) => setAspect(e.target.value)} className="rounded bg-slate-800 px-2 py-1 text-sm">
            <option value="16:9">横屏 16:9</option>
            <option value="9:16">竖屏 9:16</option>
          </select>
        </label>
        <button onClick={genVideo} className="rounded bg-amber-600 px-3 py-1.5 text-sm hover:bg-amber-500">生成视频</button>
      </header>

      <div className="space-y-3 px-6 py-5">
        <input value={sb.synopsis} onChange={(e) => setSb((p) => (p ? { ...p, synopsis: e.target.value } : p))}
          className="w-full rounded bg-slate-900 px-3 py-2 text-sm outline-none" placeholder="分镜梗概 synopsis" />

        {sb.shots.map((s, i) => (
          <div key={s.shot_no} className="rounded-xl border border-slate-800 bg-slate-900 p-3">
            <div className="mb-2 flex flex-wrap items-center gap-2 text-xs">
              <span className="font-bold text-violet-300">镜 {s.shot_no}</span>
              <label className="text-slate-500">景别
                <select value={s.shot_size} onChange={(e) => setShot(i, { shot_size: e.target.value })} className="ml-1 rounded bg-slate-800 px-1 py-0.5">
                  {template.shot_sizes.map((x) => <option key={x} value={x}>{x}</option>)}
                </select>
              </label>
              <label className="text-slate-500">运镜
                <select value={s.camera_movement} onChange={(e) => setShot(i, { camera_movement: e.target.value })} className="ml-1 rounded bg-slate-800 px-1 py-0.5">
                  {template.camera_movements.map((x) => <option key={x} value={x}>{x}</option>)}
                </select>
              </label>
              <label className="text-slate-500">时长
                <input type="number" min={1} max={30} value={s.duration_sec} onChange={(e) => setShot(i, { duration_sec: Number(e.target.value) || 1 })} className="ml-1 w-16 rounded bg-slate-800 px-1 py-0.5" />
              </label>
              <span className="text-slate-600">衔接 {s.link_from_previous}</span>
            </div>
            <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
              <textarea value={s.visual_description} onChange={(e) => setShot(i, { visual_description: e.target.value })} rows={2}
                className="w-full rounded bg-slate-800 px-2 py-1 text-sm" placeholder="画面描述" />
              <textarea value={s.dialogue} onChange={(e) => setShot(i, { dialogue: e.target.value })} rows={2}
                className="w-full rounded bg-slate-800 px-2 py-1 text-sm" placeholder="逐字对白（口型对齐）" />
            </div>
            <details className="mt-2">
              <summary className="cursor-pointer text-xs text-slate-500">动作/情绪/光照/音效</summary>
              <div className="mt-1 grid grid-cols-2 gap-2">
                <input value={s.character_action} onChange={(e) => setShot(i, { character_action: e.target.value })} className="rounded bg-slate-800 px-2 py-1 text-xs" placeholder="动作" />
                <input value={s.emotion} onChange={(e) => setShot(i, { emotion: e.target.value })} className="rounded bg-slate-800 px-2 py-1 text-xs" placeholder="情绪" />
                <input value={s.lighting} onChange={(e) => setShot(i, { lighting: e.target.value })} className="rounded bg-slate-800 px-2 py-1 text-xs" placeholder="光照" />
                <input value={s.sound_effect} onChange={(e) => setShot(i, { sound_effect: e.target.value })} className="rounded bg-slate-800 px-2 py-1 text-xs" placeholder="音效" />
              </div>
            </details>
          </div>
        ))}

        {/* Seedance 导演提示词 */}
        <section className="rounded-xl border border-slate-800 bg-slate-900 p-4">
          <h2 className="mb-2 text-sm font-semibold">Seedance 导演提示词</h2>
          <pre className="whitespace-pre-wrap rounded bg-slate-950 p-3 text-xs text-slate-400">{view?.seedance_prompt ?? ""}</pre>
        </section>

        {/* 视频任务 */}
        {job && (
          <section className="rounded-xl border border-amber-600/40 bg-amber-500/5 p-4 text-sm">
            <div className="mb-2 flex items-center gap-3">
              <span className={`rounded px-2 py-0.5 text-xs ${job.status === "done" ? "bg-emerald-600/30 text-emerald-300" : job.status === "failed" ? "bg-rose-600/30 text-rose-300" : "bg-slate-700 text-slate-300"}`}>{job.status === "done" ? "已生成" : job.status === "failed" ? "失败" : "排队中"}</span>
              <span className="rounded bg-slate-800 px-2 py-0.5 text-xs text-slate-300">{job.aspect_ratio === "9:16" ? "竖屏 9:16" : "横屏 16:9"}</span>
              <span>{job.duration_sec}s</span>
              <span>× {job.cost_per_second} 积分/s</span>
              <span className="font-bold text-amber-300">= {job.total_cost} 积分</span>
              <span className="text-slate-500">{job.provider && job.provider !== "mock" ? `（${job.provider} 真实渲染）` : "（mock：确定性计价，未真实渲染）"}</span>
            </div>
            {job.video_url ? (
              <a href={job.video_url} target="_blank" rel="noreferrer"
                className="inline-block max-w-full truncate rounded bg-emerald-600/20 px-3 py-1.5 text-emerald-300 hover:bg-emerald-600/30">
                ▶ 查看视频
              </a>
            ) : job.status === "queued" ? (
              <p className="text-xs text-amber-300/80">视频仍在渲染中，请稍后刷新。</p>
            ) : null}
          </section>
        )}
      </div>

      {msg && <div className="px-6 pb-6 text-sm"><span className={msg.ok ? "text-emerald-400" : "text-rose-400"}>{msg.text}</span></div>}
    </main>
  );
}