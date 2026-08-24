"use client";

// 可视化运行（胶片化）：把互动剧情图「完整复现」成可交互影视播放器。
// - 若节点生成了真实视频（video_url 是真 http(s)），直接用 <video> 播真实成品画面；
//   否则回退到「分镜镜表帧条」——每个镜头用一张通过镜表数据绘制的胶片帧（visual_description/景别/运镜）。
// - 底部为可拖拽胶片时间线：拖动/点按镜头缩略帧即可跳转进度（真视频时同步 seek）。
// - 镜头切换加淡入淡出；选项按其 video_at_sec 在画面第 N 秒弹层；点击后应用 effect 并跳下一节点。
// 全部数据来自真实后端（storygraph / storyboard / video），不造假。
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { IdeNode } from "./workspace";
import { KIND_COLOR, KIND_LABEL } from "./workspace";
import { authenticatedFetch } from "@/lib/api";

type Variable = { name: string; initial?: unknown };
type Shot = {
  shot_no: number; duration_sec: number; shot_size: string; camera_movement: string;
  visual_description: string; dialogue: string; emotion: string;
};

const NODE_FALLBACK_SEC = 12;

type Film = {
  shots: Shot[];
  realVideoUrl: string | null; // 真实可播视频（http(s)）
  duration: number;
};

async function loadFilm(
  projectId: string,
  nodeId: string,
): Promise<Film | null> {
  try {
    const [sbRes, vjRes] = await Promise.all([
      authenticatedFetch(`/api/projects/${projectId}/storyboard/${nodeId}`),
      authenticatedFetch(`/api/projects/${projectId}/storyboard/${nodeId}/video`),
    ]);
    const sb = sbRes.ok ? await sbRes.json() : null;
    const vj = vjRes.ok ? await vjRes.json().catch(() => null) : null;
    let realVideoUrl: string | null = null;
    if (vj) {
      const u = vj?.video_url as string | undefined;
      if (u && /^https?:\/\//i.test(u)) realVideoUrl = u;
    }
    const shots: Shot[] =
      (sb?.shots ?? []).map((s: Record<string, unknown>) => ({
        shot_no: Number(s.shot_no) || 1,
        duration_sec: Number(s.duration_sec) || 4,
        shot_size: String(s.shot_size ?? ""),
        camera_movement: String(s.camera_movement ?? ""),
        visual_description: String(s.visual_description ?? ""),
        dialogue: String(s.dialogue ?? ""),
        emotion: String(s.emotion ?? ""),
      }));
    const duration =
      shots.reduce((a, b) => a + (b.duration_sec || 0), 0) ||
      Number(vj?.duration_sec || 0) ||
      NODE_FALLBACK_SEC;
    return { shots: (shots as Shot[]), realVideoUrl, duration };
  } catch {
    return { shots: [], realVideoUrl: null, duration: NODE_FALLBACK_SEC };
  }
}

export default function Playthrough({
  open,
  projectId,
  nodes,
  entryNodeId,
  variables,
  onClose,
  nodeTitleOf,
  onOpenBranch,
  onEditChoices,
  posters,
}: {
  open: boolean;
  projectId: string;
  nodes: IdeNode[];
  entryNodeId: string | null;
  variables: Variable[];
  onClose: () => void;
  nodeTitleOf: (id: string) => string;
  onOpenBranch?: (instruction: string, anchorNodeId: string) => Promise<string | null>;
  onEditChoices?: (nodeId: string, nodeTitle: string, choices: IdeNode["choices"]) => Promise<boolean>;
  posters?: Record<string, string>;
}) {
  const [currentId, setCurrentId] = useState<string | null>(entryNodeId);
  const [state, setState] = useState<Record<string, number>>({});
  const [sec, setSec] = useState(0);
  const [ended, setEnded] = useState(false);
  const [choicePicked, setChoicePicked] = useState(false);
  const [history, setHistory] = useState<string[]>([]);
  const [film, setFilm] = useState<Film | null>(null);
  const [seeking, setSeeking] = useState(false);
  const [branchOpen, setBranchOpen] = useState(false);
  const [branchText, setBranchText] = useState("");
  const [branchBusy, setBranchBusy] = useState(false);
  const [branchMsg, setBranchMsg] = useState("");
  const [fadeIn, setFadeIn] = useState(false);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const stripRef = useRef<HTMLDivElement | null>(null);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);
  // 自由输入“不影响剧情走向”的花絮选项：只抛出你写的一句话当氛围旁白，不改变任何分支去向
  const [flavorOpen, setFlavorOpen] = useState(false);
  const [flavorText, setFlavorText] = useState("");
  const [flavorMsg, setFlavorMsg] = useState("");
  const flavorTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  // 创作者在“可视化运行”中直接增删/改当前节点的选项 + 每个选项的出现时间（可插到任意播放位置）
  const [editOpen, setEditOpen] = useState(false);
  const [editChoices, setEditChoices] = useState<IdeNode["choices"]>([]);
  const [editMsg, setEditMsg] = useState("");
  const [editBusy, setEditBusy] = useState(false);
  const openEditor = (cs: IdeNode["choices"]) => { setEditChoices(cs.map((c) => ({ ...c }))); setEditMsg(""); setEditOpen(true); };
  const saveEdits = async () => {
    if (!current || !editChoices || !onEditChoices) { setEditOpen(false); return; }
    setEditBusy(true); setEditMsg("");
    try {
      const ok = await onEditChoices(current.node_id, current.title || current.node_id, editChoices);
      setEditMsg(ok ? "已保存到剧情图" : "保存失败");
      if (ok) setEditOpen(false);
    } catch (e) {
      setEditMsg(String((e as Error).message ?? e));
    }
    setEditBusy(false);
  };

  const nodeMap = useMemo(() => {
    const m = new Map<string, IdeNode>();
    nodes.forEach((n) => m.set(n.node_id, n));
    return m;
  }, [nodes]);

  const current = nodes.find((n) => n.node_id === currentId);
  const totalSec = film?.duration || 12;

  // 打开 / 切换节点时重置并载入该节点的胶片
  useEffect(() => {
    if (!open) return;
    setCurrentId(entryNodeId);
    setSec(0);
    setEnded(false);
    setChoicePicked(false);
    setHistory([]);
    const init: Record<string, number> = {};
    variables.forEach((v) => { const ini = v.initial; init[v.name] = typeof ini === "number" ? ini : 0; });
    setState(init);
  }, [open, entryNodeId, variables]);

  useEffect(() => {
    if (!open || !projectId || !currentId) return;
    setFilm(null);
    setFadeIn(true);
    const t = setTimeout(() => setFadeIn(false), 650);
    loadFilm(projectId, currentId).then(setFilm).catch(() => setFilm(null));
    return () => clearTimeout(t);
  }, [open, projectId, currentId]);

  useEffect(() => () => { if (timer.current) clearInterval(timer.current); }, []);

  // 播放推进（不播放时暂停）
  useEffect(() => {
    if (!open || !current || current.kind === "ending") return;
    if (timer.current) clearInterval(timer.current);
    timer.current = setInterval(() => {
      if (!seeking && !flavorMsg.startsWith("🧂")) setSec((s) => Math.min(s + 0.25, totalSec));
    }, 250);
    return () => { if (timer.current) clearInterval(timer.current); };
  }, [open, currentId, totalSec, current?.kind, seeking, flavorMsg]); // eslint-disable-line react-hooks/exhaustive-deps

  // 真视频：秒→currentTime
  useEffect(() => {
    const v = videoRef.current;
    if (v && film?.realVideoUrl && Math.abs(v.currentTime - sec) > 0.3) {
      if (!seeking) v.currentTime = sec;
    }
  }, [sec, film?.realVideoUrl, seeking]);

  const timedChoices = (current?.choices ?? []).filter((c) => c.video_at_sec != null && sec >= c.video_at_sec!);
  const tailChoices = (current?.choices ?? []).filter((c) => c.video_at_sec == null);
  const showLayer =
    current && current.kind !== "ending" && current.choices.length > 0 &&
    !choicePicked &&
    (timedChoices.length > 0 || (tailChoices.length > 0 && sec >= totalSec));
  const choicesLayer = timedChoices.length > 0 ? timedChoices : (showLayer ? tailChoices : []);

  const activeShotIndex = useMemo(() => {
    if (!film?.shots.length) return -1;
    let acc = 0;
    for (let i = 0; i < film.shots.length; i++) {
      acc += film.shots[i].duration_sec;
      if (acc >= sec) return i;
    }
    if (sec >= totalSec) return film.shots.length - 1;
    return film.shots.length - 1;
  }, [film, sec, totalSec]);
  const activeShot = film?.shots[activeShotIndex];

  const applyEffects = (choices: IdeNode["choices"]) => {
    if (!choices) return;
    setState((st) => {
      const next = { ...st };
      (choices || []).forEach((c) => {
        (c.effects ?? []).forEach((e) => {
          if (!e.variable) return;
          const cur = next[e.variable] ?? 0;
          const val = typeof e.value === "number" ? e.value : 0;
          const op = e.op ?? "add";
          next[e.variable] = op === "set" ? val : op === "sub" ? cur - val : cur + val;
        });
      });
      return next;
    });
  };

  const choose = (c: IdeNode["choices"][number]) => {
    setChoicePicked(true);
    applyEffects([c]);
    if (c.next_node) {
      const n = nodeMap.get(c.next_node);
      setHistory((h) => [...h, currentId as string]);
      setSec(0);
      setCurrentId(c.next_node);
      if (n && n.kind === "ending") setEnded(true);
    } else {
      setEnded(true);
    }
  };

  // 写一个完全开放的共创分支：AI 会为这段自由走向生图 + 生成文本，创作后该分支锁定不可改
  const submitOpenBranch = async () => {
    if (!onOpenBranch || !currentId || branchBusy) return;
    const text = branchText.trim();
    if (!text) { setBranchMsg("请先写出这段走向"); return; }
    setBranchBusy(true);
    setBranchMsg("");
    try {
      const newId = await onOpenBranch(text, currentId);
      if (newId) {
        setBranchMsg("✓ 已生成新分支，AI 正在完整展开（该分支锁定、AI 管理）");
        setHistory((h) => [...h, currentId as string]);
        setSec(0);
        setChoicePicked(false);
        setCurrentId(newId);
        setBranchOpen(false);
        setBranchText("");
      } else {
        setBranchMsg("⚠ 未找到新分支节点，请重试");
      }
    } catch (e) {
      setBranchMsg(`✗ 生成失败：${String((e as Error).message ?? e)}`);
    } finally {
      setBranchBusy(false);
    }
  };

  // 自由花絮选项：用户自己写一句话，仅作为氛围旁白弹出，不改变剧情走向（不调用 choose）
  const submitFreeform = () => {
    const t = flavorText.trim();
    if (!t) { setFlavorMsg("请先写下这句话"); return; }
    setFlavorMsg(`🧂 你写道：「${t}」`);
    setFlavorText("");
    setFlavorOpen(false);
    if (flavorTimer.current) clearTimeout(flavorTimer.current);
    flavorTimer.current = setTimeout(() => {
      setFlavorMsg("");
    }, 7000);
  };

  // 拖拽 / 点击胶片时间线 → 定位秒数
  const setFromPointer = useCallback(
    (clientX: number) => {
      const el = stripRef.current;
      if (!el) return;
      const rect = el.getBoundingClientRect();
      const ratio = Math.min(1, Math.max(0, (clientX - rect.left) / rect.width));
      setSec(ratio * totalSec);
    },
    [totalSec],
  );
  const onPointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    e.currentTarget.setPointerCapture?.(e.pointerId);
    setSeeking(true);
    setFromPointer(e.clientX);
  };
  const onPointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    if (seeking) setFromPointer(e.clientX);
  };
  const endSeek = () => setSeeking(false);

  if (!open) return null;

  const isEnding = current?.kind === "ending";
  const kindColor = KIND_COLOR[current?.kind ?? "scene"] ?? "#64748b";
  const gradient = isEnding ? "linear-gradient(135deg,#1a1033,#2b0f3a)" : `linear-gradient(135deg,${kindColor}55,${kindColor}22)`;

  return (
    <div className="fixed inset-0 z-[90] flex items-center justify-center bg-black/80 p-4 backdrop-blur-sm" onClick={onClose}>
      <div className="relative w-full max-w-4xl rounded-2xl border border-white/15 bg-[#0a0a18] p-4 shadow-2xl" onClick={(e) => e.stopPropagation()}>
        {/* 顶部 HUD */}
        <div className="mb-2 flex items-center justify-between text-xs text-slate-400">
          <span className="rounded-full border border-white/10 bg-panel2 px-2 py-0.5">🎬 {nodeTitleOf(current?.node_id ?? "")}</span>
          <span className="font-bold text-gold">{KIND_LABEL[current?.kind ?? "scene"]}</span>
          <span className="text-slate-500">场景 {history.length + 1}{film?.realVideoUrl ? " · 真实视频" : film?.shots.length ? " · 分镜" : ""}</span>
          <button onClick={onClose} className="rounded bg-white/5 px-2 py-1 hover:bg-white/10">✕ 关闭</button>
        </div>

        {/* 画面 / 胶片窗口 */}
        <div className="relative h-64 overflow-hidden rounded-xl border border-white/10 bg-black">
          {/* 跨镜头 black场 / 片头 crossfade 转场（随节点切换淡入淡出） */}
          <div
            key={`fade-${currentId}`}
            className={`pointer-events-none absolute inset-0 z-[5] bg-black transition-opacity duration-500 ${fadeIn ? "opacity-100" : "opacity-0"}`}
          />
          {/* 真实视频 */}
          {film?.realVideoUrl ? (
            <video
              ref={videoRef}
              key={film.realVideoUrl}
              src={film.realVideoUrl}
              className="absolute inset-0 h-full w-full object-cover"
              playsInline
              preload="metadata"
              onLoadedMetadata={() => {}}
              onDoubleClick={(e) => e.stopPropagation()}
            />
          ) : (
            <div key={`shot-${currentId}-${activeShot?.shot_no ?? 0}`} className="absolute inset-0 flex items-center justify-center transition-opacity duration-500"
              style={{ background: gradient }}>
              <div className="px-6 text-center">
                {activeShot ? (
                  <>
                    <div className="mb-2 flex items-center justify-center gap-2 text-[10px] text-white/70">
                      <span className="rounded-full bg-black/50 px-2 py-0.5">镜 {activeShot.shot_no}</span>
                      <span>{activeShot.shot_size || "景别"} · {activeShot.camera_movement || "运镜"}</span>
                    </div>
                    <div className="max-h-24 overflow-auto text-sm text-white/90">{activeShot.visual_description || "（该帧无画面描述）"}</div>
                    {activeShot.dialogue ? (
                      <div className="mt-3 rounded bg-black/60 px-3 py-1 text-sm italic text-glow">“{activeShot.dialogue}”</div>
                    ) : null}
                  </>
                ) : (
                  <div className="text-sm text-white/80">{current?.summary || current?.title || "（无分镜帧）"}</div>
                )}
              </div>
            </div>
          )}

          {/* 画面底部的进度/转场条（真视频时仍显示） */}
          <div className="absolute bottom-10 left-3 right-3 h-0.5 rounded bg-white/15">
            <div className="h-full rounded bg-accent" style={{ width: `${(sec / Math.max(1, totalSec)) * 100}%` }} />
          </div>
          <div className="absolute top-3 left-3 rounded bg-black/50 px-1.5 py-0.5 text-[10px] text-white/70">{sec.toFixed(1)}s / {totalSec.toFixed(1)}s</div>
          {/* 自由花絮旁白（用户自填，不影响剧情走向） */}
          {flavorMsg.startsWith("🧂") && (
            <div className="absolute inset-x-6 top-16 z-[16] rounded-xl border border-mint/40 bg-black/80 p-3 text-center text-sm text-mint backdrop-blur">
              {flavorMsg.slice(flavorMsg.indexOf("：") + 1)}
              <div className="mt-1 text-[10px] text-slate-500">（仅氛围旁白，不影响剧情走向 · 几秒后自动继续）</div>
            </div>
          )}

          {/* 选项弹层 */}
          {showLayer && !ended && (
            <div className="absolute inset-x-0 bottom-0 z-10 flex flex-col gap-1.5 bg-black/60 p-3 backdrop-blur" onDoubleClick={(e) => e.stopPropagation()}>
              <span className="text-[10px] text-amber-300">请在画面中做出选择：</span>
              {choicesLayer.map((c) => {
                  const cPoster = c.next_node ? posters?.[c.next_node] : undefined;
                  return (
                    <button key={c.choice_id} onClick={() => choose(c)}
                      className="flex items-center gap-2 rounded-lg border border-accent/50 bg-accent/20 px-3 py-1.5 text-left text-sm text-glow hover:bg-accent/30">
                      {cPoster ? (
                        <img src={cPoster} alt="" className="h-9 w-14 shrink-0 rounded object-cover" />
                      ) : null}
                      <span>{c.text}<span className="ml-1 text-[10px] text-slate-400">→ {c.next_node ? nodeTitleOf(c.next_node) : "结局"}</span></span>
                    </button>
                  );
                })}
              {onOpenBranch && (
                <div className="border-t border-white/10 pt-1.5">
                  {!branchOpen ? (
                    <button onClick={() => setBranchOpen(true)} className="rounded border border-dashed border-gold/40 px-2 py-1 text-[11px] text-glow hover:bg-gold/10">
                      ✍️ 自己写一个开放分支（AI 将自由生图 + 生成文本，此分支不可再编辑）
                    </button>
                  ) : (
                    <div className="flex flex-col gap-1">
                      <span className="text-[10px] text-slate-400">随意描述这段走向（完全开放，AI 自由发挥）：</span>
                      <textarea
                        value={branchText}
                        onChange={(e) => setBranchText(e.target.value)}
                        rows={2}
                        placeholder="例：主角突然觉醒记忆，召唤天界舰队，同时也引来了深渊的注视……"
                        className="w-full rounded-lg border border-white/15 bg-black/40 px-2 py-1 text-xs text-glow outline-none focus:border-gold"
                      />
                      <div className="flex items-center gap-2">
                        <button onClick={submitOpenBranch} disabled={branchBusy}
                          className="rounded-md bg-gold/25 px-2 py-1 text-[11px] text-gold disabled:opacity-50">
                          {branchBusy ? "AI 生成中…" : "确定，创建开放分支"}
                        </button>
                        <button onClick={() => { setBranchOpen(false); setBranchMsg(""); }} className="text-[10px] text-slate-400">取消</button>
                      </div>
                      {branchMsg && <span className="text-[10px] text-glow">{branchMsg}</span>}
                    </div>
                  )}
                </div>
              )}
              {/* ✍ 自由输入：不影响剧情走向（只抛出氛围旁白，不跳转、不改分支） */}
              <div className="border-t border-white/10 pt-1.5">
                {!flavorOpen ? (
                  <button onClick={() => setFlavorOpen(true)} className="rounded border border-dashed border-mint/50 px-2 py-1 text-[11px] text-mint hover:bg-mint/10">
                    🧂 自由输入一句话（不影响剧情走向）
                  </button>
                ) : (
                  <div className="flex flex-col gap-1">
                    <span className="text-[10px] text-slate-400">写一句你想插进来的话（旁白/吐槽/氛围，不改变分支，播放暂停片刻后继续）：</span>
                    <textarea
                      value={flavorText}
                      onChange={(e) => setFlavorText(e.target.value)}
                      rows={2}
                      placeholder="例：主角握了握拳，感觉这一章的气氛有点不对劲。"
                      className="w-full rounded-lg border border-white/15 bg-black/40 px-2 py-1 text-xs text-glow outline-none focus:border-mint"
                    />
                    <div className="flex items-center gap-2">
                      <button onClick={submitFreeform} className="rounded-md bg-mint/25 px-2 py-1 text-[11px] text-mint hover:bg-mint/35">插入这句，继续</button>
                      <button onClick={() => { setFlavorOpen(false); setFlavorMsg(""); }} className="text-[10px] text-slate-400">取消</button>
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}
          {/* ✏ 创作者：在运行中增删/改本节点选项、设每个选项出现时间（可插到任意播放位置） */}
          <div className="mx-1 mb-1 border-t border-white/10 pt-1.5">
            {!editOpen ? (
              <button onClick={() => openEditor(current?.choices ?? [])} disabled={!current} className="rounded border border-dashed border-accent/60 px-2 py-1 text-[11px] text-accent hover:bg-accent/10 disabled:opacity-40">
                ✏️ 编辑本节点选项（增删改 + 出现时间）
              </button>
            ) : (
              <div className="flex flex-col gap-1">
                <div className="flex items-center justify-between">
                  <span className="text-[10px] text-slate-400">编辑「{current?.title || current?.node_id}」的选项（可随意增删、改文字/出现时间）：</span>
                  <button onClick={() => setEditOpen(false)} className="text-[10px] text-slate-500 hover:text-white">收起</button>
                </div>
                <div className="space-y-1">
                  {editChoices.map((c, i) => (
                    <div key={c.choice_id} className="flex items-center gap-1">
                      <input
                        value={c.text}
                        onChange={(e) => setEditChoices((arr) => arr.map((x, j) => (j === i ? { ...x, text: e.target.value } : x)))}
                        className="min-w-0 flex-1 rounded border border-white/15 bg-black/40 px-1.5 py-1 text-[11px] text-glow outline-none focus:border-accent"
                      />
                      <input
                        type="number" min={0} step={0.5} placeholder="秒"
                        value={c.video_at_sec ?? ""}
                        onChange={(e) => setEditChoices((arr) => arr.map((x, j) => (j === i ? { ...x, video_at_sec: e.target.value === "" ? null : Math.max(0, Number(e.target.value)) } : x)))}
                        className="w-14 rounded bg-black/40 border border-white/10 px-1 py-1 text-[11px] text-center"
                        title="出现时间（秒）：播放到该秒时弹层——可插到任意位置"
                      />s
                      <button onClick={() => setEditChoices((arr) => arr.filter((_, j) => j !== i))} className="rounded bg-rose-900/40 px-1.5 py-1 text-[10px] text-rose-300 hover:bg-rose-800">✕</button>
                    </div>
                  ))}
                  {editChoices.length === 0 && <span className="text-[10px] text-slate-500">暂无选项，点下方「＋ 添加一个」</span>}
                </div>
                <div className="flex items-center gap-2">
                  <button onClick={() => setEditChoices((arr) => [...arr, { choice_id: `c-${Date.now()}`, text: "新选项", next_node: null }])} className="rounded-md bg-white/5 px-2 py-1 text-[11px] text-slate-300 hover:bg-white/10">＋ 添加一个</button>
                  <button onClick={saveEdits} disabled={editBusy} className="ml-auto rounded-md bg-accent/25 px-3 py-1 text-[11px] font-bold text-accent hover:bg-accent/35 disabled:opacity-50">{editBusy ? "保存中…" : "保存到剧情图"}</button>
                </div>
                {editMsg && <span className={`text-[10px] ${editMsg === "已保存到剧情图" ? "text-mint" : "text-rose-400"}`}>{editMsg}</span>}
              </div>
            )}
          </div>
          {ended && (
            <div className="absolute inset-x-0 bottom-0 z-10 flex items-center justify-between bg-black/60 p-3">
              <span className="text-sm font-bold text-gold">🎉 {current?.title || "结局"}</span>
              <button onClick={() => { setCurrentId(entryNodeId); setSec(0); setEnded(false); setChoicePicked(false); setHistory([]); }}
                className="rounded bg-accent/40 px-3 py-1 text-xs text-white hover:bg-accent/50">重新开始</button>
            </div>
          )}
        </div>

        {/* 底部的变量/路径 */}
        <div className="mt-2 flex items-center justify-between text-xs text-slate-400">
          <span className="truncate">{history.map((h) => nodeTitleOf(h)).join(" → ")}{history.length ? " → " : ""}{nodeTitleOf(current?.node_id ?? "")}</span>
          {Object.entries(state).length > 0 && (
            <span className="flex gap-1">
              {Object.entries(state).map(([k, v]) => (
                <span key={k} className="rounded-full bg-black/40 px-2 py-0.5 text-[10px] text-glow">{k}: {String(v)}</span>
              ))}
            </span>
          )}
        </div>

        {/* 可拖拽胶片时间线（含镜头缩略跳转） */}
        <div
          ref={stripRef}
          className="mt-3 flex h-16 cursor-pointer select-none overflow-hidden rounded-lg border border-white/10 bg-[#10102a]"
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={endSeek}
          onPointerLeave={endSeek}
        >
          {film?.shots.length ? (
            film.shots.map((s, i) => {
              const w = totalSec ? (s.duration_sec / totalSec) * 100 : 0;
              const isActive = i === activeShotIndex;
              return (
                <div key={s.shot_no}
                  className={`relative flex items-center justify-center overflow-hidden border-r border-white/10 px-1 text-[8px] ${isActive ? "bg-accent/25" : ""}`}
                  style={{ width: `${w}%` }}>
                  <div className="flex h-full w-full flex-col items-center justify-center gap-0.5 p-0.5 text-center text-white/70">
                    <span className="rounded-sm bg-black/60 px-1 text-[7px]">({s.shot_no}) {s.shot_size || ""} {s.camera_movement || ""}</span>
                    <span className="line-clamp-2">{s.visual_description || s.dialogue || ""}</span>
                  </div>
                </div>
              );
            })
          ) : (
            <div className="flex w-full items-center justify-center text-[10px] text-slate-500">（无分镜 → 按剧情时长计时）</div>
          )}
          {/* 进度头 */}
          <div className="pointer-events-none absolute inset-y-0 w-1 bg-glow" style={{ left: `${(sec / Math.max(1, totalSec)) * 100}%` }} />
        </div>
        <div className="mt-1 flex justify-between text-[9px] text-slate-500">
          <span>{film?.realVideoUrl ? "真实视频（可拖拽 seek）" : film?.shots.length ? "分镜胶片 · 拖动跳转 / 点击镜头缩略图" : "无真实视频，按剧情计时"}</span>
          <span>{film?.shots.length} 镜头</span>
        </div>
      </div>
    </div>
  );
}