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
  video_url?: string; aspect_ratio?: string; provider?: string; error?: string;
};
type TNode = { node_id: string; title: string; kind: string; summary?: string };
type TTemplate = { shot_sizes: string[]; camera_movements: string[]; cost_per_second: number };

// 后端 poll 返回的终态用 "succeeded"/"failed"，这里统一归一化给前端用
const termMap: Record<string, "done" | "failed"> = {
  succeeded: "done", success: "done", done: "done", completed: "done", complete: "done",
  failed: "failed", error: "failed",
};
const normJob = (j: TJob): TJob => (termMap[j.status] ? { ...j, status: termMap[j.status] } : j);
const isJobDone = (j: TJob | null): boolean => !!j && j.status === "done";
const isJobFailed = (j: TJob | null): boolean => !!j && j.status === "failed";

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
  const [styles, setStyles] = useState<{ id: string; label: string; sample?: string }[]>([]);
  const [style, setStyle] = useState("cinematic");
  const [styleCustom, setStyleCustom] = useState(false);
  const [customStyle, setCustomStyle] = useState("");
  const [characters, setCharacters] = useState<{ character_id: string; name: string; role: string }[]>([]);
  const [charId, setCharId] = useState("");
  const [charRef, setCharRef] = useState<{ ref_image: string; has_portrait: boolean } | null>(null);
  const [charLoad, setCharLoad] = useState(false);

  // —— 成片参数：分辨率 / 时长 / 首尾帧 ——
  const [resolution, setResolution] = useState("768P");
  const [durationSec, setDurationSec] = useState(5);
  const [firstFrame, setFirstFrame] = useState("");
  const [lastFrame, setLastFrame] = useState("");

  // —— 逐镜头生成 + 剪辑 ——
  type TClip = { shot_no: number; status: string; task_id: string; provider: string; video_url: string; error: string; prompt?: string };
  type TClips = { node_id: string; status: string; aspect_ratio?: string; duration_per_clip?: number; clips: TClip[]; transition?: string };
  const [clips, setClips] = useState<TClips | null>(null);
  const [clipGenerating, setClipGenerating] = useState(false);
  const [clipOrder, setClipOrder] = useState<number[]>([]);
  const [transition, setTransition] = useState("hard");
  const [composing, setComposing] = useState(false);
  const [composeUrl, setComposeUrl] = useState("");
  const [dragIndex, setDragIndex] = useState<number | null>(null);

  useEffect(() => {
    setProjectId(new URLSearchParams(window.location.search).get("project") ?? "");
    authenticatedFetch("/api/meta/storyboard-template").then((r) => r.json()).then((t) => setTemplate(t)).catch(() => {});
    authenticatedFetch("/api/styles").then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((d: { styles?: { id: string; label: string; sample?: string }[] }) => {
        const list = d.styles ?? [];
        setStyles(list);
        if (list.some((s) => s.id === "cinematic")) setStyle("cinematic");
        else if (list.length) setStyle(list[0].id);
      }).catch(() => {});
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

  useEffect(() => {
    if (!projectId) return;
    authenticatedFetch(`/api/projects/${projectId}/characters`)
      .then((r) => (r.ok ? r.json() : []))
      .then((cs) => {
        const arr = Array.isArray(cs) ? cs : [];
        setCharacters(arr);
        if (arr.length) setCharId(arr[0].character_id);
      })
      .catch(() => setCharacters([]));
  }, [projectId]);

  // 选中的角色立绘 → 作为图生视频首帧（人物一致）
  useEffect(() => {
    if (!projectId || !charId) { setCharRef(null); return; }
    setCharLoad(true);
    authenticatedFetch(`/api/projects/${projectId}/characters/${charId}/portrait/video_ref`)
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => setCharRef(d?.has_portrait ? d : null))
      .catch(() => setCharRef(null))
      .finally(() => setCharLoad(false));
  }, [projectId, charId]);

  // 排队中自动轮询，渲染完成时无需手动刷新
  // 必须放在任何 early-return 之前，确保每次渲染 Hook 数量一致（否则整页白屏进不去）
  const pollVideo = async () => {
    if (!projectId || !nodeId) return;
    try {
      const r = await authenticatedFetch(`/api/projects/${projectId}/storyboard/${nodeId}/video`);
      const j = (await r.json()) as TJob;
      if (j?.job_id) setJob(normJob(j));
    } catch { /* 忽略瞬时错误，下一轮再查 */ }
  };
  useEffect(() => {
    if (!job || isJobDone(job) || isJobFailed(job)) return;
    const iv = setInterval(() => { void pollVideo(); }, 4000);
    return () => clearInterval(iv);
  }, [projectId, nodeId, job]);

  // —— 逐镜头生成：POST 创建每镜头一个 task；GET 轮询落定 ——
  const genClips = async () => {
    setClipGenerating(true);
    setMsg({ ok: true, text: `正在为每个分镜镜头提交 ${durationSec}s 视频任务…` });
    const body: Record<string, unknown> = { aspect_ratio: aspect, resolution, duration_sec: durationSec };
    const ff = firstFrame.trim() || (charRef?.has_portrait && charRef.ref_image ? charRef.ref_image : "");
    if (ff) body.ref_image = ff;
    if (lastFrame.trim()) body.ref_image_last = lastFrame.trim();
    try {
      const r = await authenticatedFetch(`/api/projects/${projectId}/storyboard/${nodeId}/video/clips`, {
        method: "POST", body: JSON.stringify(body),
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) { setMsg({ ok: false, text: d?.error?.message || `HTTP ${r.status}` }); return; }
      const c = d as TClips;
      setClips(c);
      setClipOrder(c.clips.map((x) => x.shot_no));
      setMsg({ ok: true, text: `已提交 ${c.clips.length} 个镜头，正在逐个真实渲染，完成后自动出现。` });
    } catch (e) {
      setMsg({ ok: false, text: (e as Error).message || "逐镜头生成失败" });
    } finally {
      setClipGenerating(false);
    }
  };

  const pollClips = async () => {
    if (!projectId || !nodeId) return;
    try {
      const r = await authenticatedFetch(`/api/projects/${projectId}/storyboard/${nodeId}/video/clips`);
      if (r.ok) {
        const d = (await r.json()) as TClips;
        if (d.clips?.length) setClips(d);
      }
    } catch { /* 忽略瞬时错误 */ }
  };
  const clipsBusy = !!clips && clips.status !== "done" && clips.status !== "none";
  useEffect(() => {
    if (!clipsBusy) return;
    const iv = setInterval(() => { void pollClips(); }, 4000);
    return () => clearInterval(iv);
  }, [projectId, nodeId, clips]);

  // 排序辅助（←/→ 交换位置即调整时间轴顺序）
  const moveClip = (shot_no: number, dir: -1 | 1) => {
    setClipOrder((prev) => {
      const i = prev.indexOf(shot_no);
      const j = i + dir;
      if (i < 0 || j < 0 || j >= prev.length) return prev;
      const next = [...prev];
      [next[i], next[j]] = [next[j], next[i]];
      return next;
    });
  };
  const orderedClips = () =>
    (clipOrder.length ? clipOrder : (clips?.clips ?? []).map((c) => c.shot_no))
      .map((no) => (clips?.clips ?? []).find((c) => c.shot_no === no))
      .filter(Boolean) as TClip[];

  const composeFilm = async () => {
    setComposing(true); setComposeUrl("");
    setMsg({ ok: true, text: "正在用 ffmpeg 合成完整成片（本地离线），请稍候…" });
    try {
      const order = clipOrder.length ? clipOrder : (clips?.clips ?? []).map((c) => c.shot_no);
      const r = await authenticatedFetch(`/api/projects/${projectId}/storyboard/${nodeId}/video/clips/compose`, {
        method: "POST", body: JSON.stringify({ order, transition, filename: "成片" }),
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) { setMsg({ ok: false, text: d?.error?.message || `HTTP ${r.status}` }); return; }
      setComposeUrl(d.url);
      setMsg({ ok: true, text: "成片合成完成，可点击下载完整视频。" });
    } catch (e) {
      setMsg({ ok: false, text: `合成失败：${(e as Error).message}` });
    } finally {
      setComposing(false);
    }
  };

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
    const effStyle = styleCustom ? customStyle.trim() : style;
    const body: Record<string, unknown> = { aspect_ratio: aspect, style: effStyle, resolution, duration_sec: durationSec };
    const ff = firstFrame.trim() || (charRef?.has_portrait && charRef.ref_image ? charRef.ref_image : "");
    if (ff) body.ref_image = ff;
    if (lastFrame.trim()) body.ref_image_last = lastFrame.trim();
    const r = await authenticatedFetch(`/api/projects/${projectId}/storyboard/${nodeId}/video`, {
      method: "POST", body: JSON.stringify(body),
    });
    const d = await r.json().catch(() => ({}));
    const styleLabel = styleCustom ? (`自定义：${effStyle || "(空)"}`)
      : (styles.find((s) => s.id === style)?.label ?? style);
    if (!r.ok) {
      setMsg({ ok: false, text: d?.error?.message || `HTTP ${r.status}` });
      return;
    }
    const j = normJob(d as TJob);
    setJob(j);
    const aspectLabel = (j.aspect_ratio ?? aspect) === "9:16" ? "竖屏" : "横屏";
    if (isJobDone(j)) {
      // 真实 mock（确定性计价）走到这里；真实渲染不会立刻 done。
      setMsg({ ok: true, text: `视频已完成：${j.total_cost} 积分 / ${j.duration_sec}s · ${aspectLabel} · 风格「${styleLabel}」` });
    } else if (isJobFailed(j)) {
      setMsg({ ok: false, text: "视频生成失败，请尝试降低时长或更换画面尺寸后重试。" });
    } else {
      // 真实渲染进入排队：绝不能误报成“已 mock 完成”
      const prov = j.provider && j.provider !== "mock" ? `（${j.provider} 真实渲染）` : "（mock 真实渲染不可等待）";
      setMsg({ ok: true, text: `视频已提交，正在排队真实渲染中… ${j.total_cost} 积分 / ${j.duration_sec}s · ${aspectLabel} · 风格「${styleLabel}」${prov}。完成后会自动刷新出来。` });
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
        <label className="flex items-center gap-1 text-sm text-slate-300" title="首帧：选一个角色，其立绘将作视频第一帧（人物一致）">
          立绘首帧
          <select value={charId} onChange={(e) => setCharId(e.target.value)} className="rounded bg-slate-800 px-2 py-1 text-sm">
            <option value="">不使用</option>
            {characters.map((c) => <option key={c.character_id} value={c.character_id}>{c.name}</option>)}
          </select>
        </label>
        {charRef?.has_portrait
          ? <span className="text-[11px] text-mint" title="该角色已保存立绘，将作为视频首帧">✓ 立绘首帧</span>
          : (charLoad ? <span className="text-[11px] text-slate-500">读取立绘…</span> : null)}
        <label className="flex items-center gap-1 text-sm text-slate-300">
          画面风格
          <select
            value={styleCustom ? "__custom__" : style}
            onChange={(e) => {
              if (e.target.value === "__custom__") { setStyleCustom(true); }
              else { setStyleCustom(false); setStyle(e.target.value); }
            }}
            className="rounded bg-slate-800 px-2 py-1 text-sm"
            title="这一节点视频/画面的整体渲染风格：选预设，或用「自定义」写自己的渲染关键词"
          >
            {styles.length === 0 && <option value="cinematic">史诗电影感</option>}
            {styles.map((s) => <option key={s.id} value={s.id}>{s.label ?? s.id}</option>)}
            <option value="__custom__">✍️ 自定义风格…</option>
          </select>
        </label>
        {styleCustom && (
          <input
            value={customStyle}
            onChange={(e) => setCustomStyle(e.target.value)}
            placeholder="写你自己的渲染关键词，如：赛璐璐，赛伟霓虹，微距特写"
            className="w-64 rounded bg-slate-800 px-2 py-1 text-sm text-slate-100"
          />
        )}
        <label className="flex items-center gap-1 text-sm text-slate-300">
          画面
          <select value={aspect} onChange={(e) => setAspect(e.target.value)} className="rounded bg-slate-800 px-2 py-1 text-sm">
            <option value="16:9">横屏 16:9</option>
            <option value="9:16">竖屏 9:16</option>
          </select>
        </label>
        <label className="flex items-center gap-1 text-sm text-slate-300">
          分辨率
          <select value={resolution} onChange={(e) => setResolution(e.target.value)} className="rounded bg-slate-800 px-2 py-1 text-sm">
            <option value="768P">768P</option>
            <option value="1080P">1080P</option>
            <option value="2K">2K</option>
            <option value="4K">4K</option>
          </select>
        </label>
        <label className="flex items-center gap-1 text-sm text-slate-300">
          时长
          <input type="number" min={4} max={15} value={durationSec}
            onChange={(e) => setDurationSec(Math.max(4, Math.min(15, Number(e.target.value) || 5)))}
            className="w-14 rounded bg-slate-800 px-2 py-1 text-sm" />s
        </label>
        <label className="flex items-center gap-1 text-sm text-slate-300">
          首帧图
          <input value={firstFrame} onChange={(e) => setFirstFrame(e.target.value)} placeholder="(可选) 标题图/立绘 URL，控制开头画面"
            className="w-52 rounded bg-slate-800 px-2 py-1 text-sm text-slate-100" />
        </label>
        <label className="flex items-center gap-1 text-sm text-slate-300">
          尾帧图
          <input value={lastFrame} onChange={(e) => setLastFrame(e.target.value)} placeholder="(可选) 结束画面 URL，与首帧一起控制首尾"
            className="w-52 rounded bg-slate-800 px-2 py-1 text-sm text-slate-100" />
        </label>
        <button onClick={genVideo} className="rounded bg-amber-600 px-3 py-1.5 text-sm hover:bg-amber-500">生成视频</button>
        <button onClick={genClips} disabled={clipGenerating}
          className="rounded bg-violet-700 px-3 py-1.5 text-sm hover:bg-violet-600 disabled:opacity-50">
          {clipGenerating ? "提交中…" : "生成逐个镜头"}
        </button>
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
              <span className={`rounded px-2 py-0.5 text-xs ${isJobDone(job) ? "bg-emerald-600/30 text-emerald-300" : isJobFailed(job) ? "bg-rose-600/30 text-rose-300" : "bg-slate-700 text-slate-300"}`}>{isJobDone(job) ? "已生成" : isJobFailed(job) ? "失败" : "排队中"}</span>
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
            ) : isJobFailed(job) ? (
              <p className="text-xs text-rose-400">
                视频生成失败{job.error ? `：${job.error}` : "，请尝试降低时长或更换画面尺寸后重试。"}
              </p>
            ) : isJobDone(job) ? (
              <p className="text-xs text-slate-400">任务完成但尚未返回视频地址，点「生成视频」重试。</p>
            ) : (
              <p className="text-xs text-amber-300/80">视频仍在真实渲染中，正在自动轮询，完成后自动出现在这里。</p>
            )}
          </section>
        )}
      </div>

      {/* —— 逐镜头剪辑成片 —— */}
      {clips && (
        <section className="mx-6 mb-6 space-y-3 rounded-xl border border-violet-600/40 bg-violet-500/5 p-4">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-violet-200">剪辑成片（{clips.clips?.length ?? 0} 个镜头 × 5s）</h2>
            <div className="flex items-center gap-2 text-xs">
              <label className="flex items-center gap-1 text-slate-300">转场
                <select value={transition} onChange={(e) => setTransition(e.target.value)}
                  className="rounded bg-slate-800 px-1 py-0.5 text-slate-100">
                  <option value="hard">硬切</option>
                  <option value="fade">淡入淡出</option>
                </select>
              </label>
              <button onClick={composeFilm} disabled={composing || clips?.status !== "done"}
                className="rounded bg-emerald-700 px-3 py-1 text-xs text-white hover:bg-emerald-600 disabled:opacity-40">
                {composing ? "合成中…" : "导出完整成片"}
              </button>
            </div>
          </div>
          {clips.status === "none" && <p className="text-xs text-slate-400">尚无需生成的镜头，先点「生成逐个镜头」。</p>}
          <div className="flex flex-wrap gap-3">
            {orderedClips().map((c, idx) => {
              const done = c.status === "done";
              const failed = c.status === "failed";
              const running = !done && !failed;
              return (
                <div key={c.shot_no}
                  className={`w-44 rounded-lg border p-2 ${done ? "border-emerald-600/50" : failed ? "border-rose-600/50" : "border-slate-700"}`}>
                  <div className="mb-1 flex items-center justify-between text-[11px]">
                    <span className="font-bold text-violet-300">镜 {c.shot_no}</span>
                    <span className={`rounded px-1 ${done ? "bg-emerald-600/30 text-emerald-300" : failed ? "bg-rose-600/30 text-rose-300" : "bg-slate-700 text-slate-300"}`}>
                      {done ? "已生成" : failed ? "失败" : "渲染中"}
                    </span>
                  </div>
                  {done && c.video_url ? (
                    <video src={c.video_url} controls className="mb-1 h-20 w-full rounded bg-black object-cover" />
                  ) : (
                    <div className="mb-1 flex h-20 w-full items-center justify-center rounded bg-slate-950 text-[11px] text-slate-500">{failed ? "生成失败" : "…"}</div>
                  )}
                  <div className="flex items-center gap-1">
                    <button onClick={() => moveClip(c.shot_no, -1)} disabled={idx === 0}
                      className="rounded bg-slate-800 px-1.5 py-0.5 text-xs disabled:opacity-30">←</button>
                    <button onClick={() => moveClip(c.shot_no, 1)} disabled={idx === orderedClips().length - 1}
                      className="rounded bg-slate-800 px-1.5 py-0.5 text-xs disabled:opacity-30">→</button>
                    <span className="ml-auto text-[10px] text-slate-500">{idx + 1}/{clips.clips?.length ?? 0}</span>
                  </div>
                  {failed && c.error && <p className="mt-1 text-[10px] text-rose-400">{c.error.slice(0, 60)}</p>}
                </div>
              );
            })}
          </div>
          {clips.status === "running" &&
            <p className="text-xs text-amber-300/80">正在真实渲染逐镜头视频，会自动轮询，全部完成后可导出成片。</p>}
          {composeUrl && (
            <a href={composeUrl} target="_blank" rel="noreferrer"
              className="inline-block rounded bg-emerald-600/20 px-3 py-1.5 text-emerald-300 hover:bg-emerald-600/30">▶ 下载完整成片 MP4</a>
          )}
        </section>
      )}

      {msg && <div className="px-6 pb-6 text-sm"><span className={msg.ok ? "text-emerald-400" : "text-rose-400"}>{msg.text}</span></div>}
    </main>
  );
}