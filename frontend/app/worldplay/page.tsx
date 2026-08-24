"use client";

import { useEffect, useState } from "react";
import TopNav from "@/components/TopNav";
import { authenticatedFetch } from "@/lib/api";

type WorldEntity = { id: string; type: string; label: string; summary?: string; status?: string };
type WorldEdge = {
  id: string; from_id: string; type: string; to_id: string;
  value?: Record<string, unknown>; valid_from_event_id?: string; valid_until_event_id?: string;
};
type WorldSlot = {
  id: string; owner_entity_id: string; kind: string; label: string;
  value?: Record<string, unknown>;
};
type WorldEvent = {
  event_id: string; turn: number; action_kind?: string;
  outcome_summary?: string; blocked?: boolean; time_advance?: { elapsed: number };
};
type World = {
  kind: string; title: string; turn: number;
  entities: WorldEntity[]; edges: WorldEdge[]; state_slots: WorldSlot[]; events: WorldEvent[];
};
type Session = { play_id: string; kind: string; title: string; turn: number; version: number };

const ENTITY_TYPE_ZH: Record<string, string> = {
  actor: "角色", location: "地点", item: "物品", evidence: "证据", clue: "线索",
  claim: "证词", proof_chain: "证据链", organization: "组织", rule: "规则", scene: "场景", event: "事件",
};
const SLOT_KIND_ZH: Record<string, string> = {
  resource: "资源", relation: "关系", pressure: "压力", clue: "线索",
  evidence: "证据", flag: "旗标", timer: "计时",
};
const EVIDENCE_RANK = ["unknown", "hinted", "seen", "collected", "verified", "weaponized", "exposed", "exhausted"];

const DEFAULT_MUTATION = JSON.stringify(
  {
    event_id: "e-1",
    turn: 1,
    action_kind: "look",
    entities: { upsert: [{ id: "room_1", type: "location", label: "档案室" }] },
    edges: { upsert: [], expire: [] },
    state_slots: { upsert: [] },
    evidence: { transitions: [] },
  },
  null,
  2,
);

export default function WorldPlayPage() {
  const [project, setProject] = useState("");
  const [sessions, setSessions] = useState<Session[]>([]);
  const [playId, setPlayId] = useState("");
  const [world, setWorld] = useState<World | null>(null);
  const [version, setVersion] = useState(0);
  const [lastEvent, setLastEvent] = useState<WorldEvent | null>(null);
  const [blocked, setBlocked] = useState<boolean | null>(null);
  const [rawInput, setRawInput] = useState("");
  const [mutation, setMutation] = useState(DEFAULT_MUTATION);
  const [newKind, setNewKind] = useState("open_world");
  const [newTitle, setNewTitle] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const id = new URLSearchParams(window.location.search).get("project") ?? "";
    setProject(id);
    if (id) loadSessions(id);
  }, []);

  const loadSessions = (pid: string) => {
    authenticatedFetch(`/api/projects/${pid}/worldplay`)
      .then((r) => r.json().then((d) => ({ ok: r.ok, d })))
      .then(({ ok, d }) => {
        if (!ok) throw new Error(d?.error?.message || "列表失败");
        setSessions(d as Session[]);
        if (d.length) select(pid, (d as Session[])[0].play_id);
      })
      .catch((e) => setError(e.message));
  };

  const select = (pid: string, pid2: string) => {
    setPlayId(pid2);
    authenticatedFetch(`/api/projects/${pid}/worldplay/${pid2}`)
      .then((r) => r.json().then((d) => ({ ok: r.ok, d })))
      .then(({ ok, d }) => {
        if (!ok) throw new Error(d?.error?.message || "读取失败");
        setWorld(d.world as World);
        setVersion(d.version as number);
        setLastEvent(null);
        setBlocked(null);
      })
      .catch((e) => setError(e.message));
  };

  const start = () => {
    if (!project || busy) return;
    setBusy(true);
    setError("");
    authenticatedFetch(`/api/projects/${project}/worldplay/start`, {
      method: "POST",
      body: JSON.stringify({ kind: newKind, title: newTitle || "未命名试玩" }),
    })
      .then((r) => r.json().then((d) => ({ ok: r.ok, d })))
      .then(({ ok, d }) => {
        if (!ok) throw new Error(d?.error?.message || "创建失败");
        setNewTitle("");
        loadSessions(project);
        return d;
      })
      .catch((e) => setError(e.message))
      .finally(() => setBusy(false));
  };

  const step = () => {
    if (!project || !playId || busy) return;
    let m: unknown;
    try {
      m = JSON.parse(mutation);
    } catch {
      setError("Mutation JSON 解析失败");
      return;
    }
    setBusy(true);
    setError("");
    authenticatedFetch(`/api/projects/${project}/worldplay/${playId}/step`, {
      method: "POST",
      body: JSON.stringify({ mutation: m, raw_input: rawInput }),
    })
      .then((r) => r.json().then((d) => ({ ok: r.ok, d })))
      .then(({ ok, d }) => {
        if (!ok) throw new Error(d?.error?.message || "回合失败");
        setWorld(d.world as World);
        setVersion(d.version as number);
        setLastEvent(d.event as WorldEvent);
        setBlocked(d.blocked as boolean);
      })
      .catch((e) => setError(e.message))
      .finally(() => setBusy(false));
  };

  return (
    <>
      <TopNav projectId={project} />
      <main className="min-h-screen px-6 py-8">
      <div className="max-w-6xl mx-auto">
        <div className="flex items-center gap-3 mb-6">
          <a href={`/agent?project=${project}`} className="text-slate-500 hover:text-white text-sm">← 返回工作台</a>
          <h1 className="text-2xl font-bold">世界图试玩</h1>
          <span className="text-xs text-slate-500">剧本杀 / 开放世界 · 实体 · 关系 · 证据</span>
        </div>

        {error && <p className="mb-4 text-sm text-accent">{error}</p>}

        <div className="grid grid-cols-1 lg:grid-cols-[240px_1fr] gap-5">
          {/* 左：会话列表 + 新建 */}
          <aside className="rounded-2xl bg-panel border border-white/10 p-4 h-fit">
            <h2 className="text-sm font-bold mb-3">试玩会话</h2>
            <div className="space-y-1">
              {sessions.map((s) => (
                <button
                  key={s.play_id}
                  onClick={() => select(project, s.play_id)}
                  className={`w-full text-left rounded-lg px-3 py-2 text-sm border ${
                    s.play_id === playId ? "border-accent/60 bg-panel2" : "border-white/5 hover:bg-panel2"
                  }`}
                >
                  <div className="truncate">{s.title || "未命名"}</div>
                  <div className="text-xs text-slate-500">{s.kind} · 回合 {s.turn} · v{s.version}</div>
                </button>
              ))}
              {!sessions.length && <p className="text-xs text-slate-500">还没有会话，先新建一个</p>}
            </div>

            <div className="mt-5 border-t border-white/10 pt-4">
              <h3 className="text-xs font-bold text-slate-400 mb-2">新建会话</h3>
              <select
                value={newKind}
                onChange={(e) => setNewKind(e.target.value)}
                className="w-full rounded-lg bg-panel2 border border-white/10 px-2 py-1.5 text-sm mb-2"
              >
                <option value="open_world">开放世界 freeplay</option>
                <option value="branching">分支剧情</option>
              </select>
              <input
                value={newTitle}
                onChange={(e) => setNewTitle(e.target.value)}
                placeholder="标题（可选）"
                className="w-full rounded-lg bg-panel2 border border-white/10 px-2 py-1.5 text-sm mb-2"
              />
              <button
                onClick={start}
                disabled={busy}
                className="w-full rounded-lg bg-gradient-to-r from-[#d90b46] to-accent px-3 py-2 text-sm font-bold text-white disabled:opacity-40"
              >
                新建
              </button>
            </div>
          </aside>

          {/* 右：世界视图 + 回合输入 */}
          <section className="space-y-5">
            {world ? (
              <>
                <div className="rounded-2xl bg-panel border border-white/10 p-6">
                  <div className="flex items-center gap-3 mb-4">
                    <h2 className="font-bold">{world.title || "未命名"}</h2>
                    <span className="text-xs rounded-full bg-panel2 border border-white/10 px-3 py-1 text-slate-300">
                      {world.kind}
                    </span>
                    <span className="text-xs text-slate-500">回合 {world.turn} · 版本 v{version}</span>
                  </div>

                  <h3 className="text-xs font-bold text-slate-400 mb-2">实体（{world.entities.length}）</h3>
                  <div className="flex flex-wrap gap-2 mb-5">
                    {world.entities.map((e) => (
                      <span key={e.id} className="text-xs rounded-lg bg-panel2 border border-white/10 px-2 py-1">
                        <span className="text-glow">{ENTITY_TYPE_ZH[e.type] ?? e.type}</span> {e.label}
                        {e.status ? <span className="text-slate-500"> · {e.status}</span> : null}
                      </span>
                    ))}
                    {!world.entities.length && <span className="text-xs text-slate-500">空</span>}
                  </div>

                  <h3 className="text-xs font-bold text-slate-400 mb-2">关系边（{world.edges.length}）</h3>
                  <div className="space-y-1 mb-5">
                    {world.edges.map((e) => (
                      <div key={e.id} className="text-xs text-slate-300">
                        <span className="text-sky-300">{e.from_id}</span>
                        <span className="mx-1 text-slate-500">—[{e.type}
                          {e.value?.role ? `:${String(e.value.role)}` : ""}]→</span>
                        <span className="text-sky-300">{e.to_id}</span>
                        {e.valid_until_event_id && <span className="text-slate-500">（至 {e.valid_until_event_id}）</span>}
                      </div>
                    ))}
                    {!world.edges.length && <span className="text-xs text-slate-500">空</span>}
                  </div>

                  <h3 className="text-xs font-bold text-slate-400 mb-2">状态槽 / 证据</h3>
                  <div className="space-y-1 mb-5">
                    {world.state_slots.map((s) => {
                      const st = s.value?.status as string | undefined;
                      return (
                        <div key={s.id} className="text-xs flex items-center gap-2">
                          <span className="rounded px-1.5 py-0.5 bg-panel2 text-slate-400">
                            {SLOT_KIND_ZH[s.kind] ?? s.kind}
                          </span>
                          <span className="text-slate-300">{s.label || s.id}</span>
                          <span className="text-slate-500">{s.owner_entity_id}</span>
                          {st && (
                            <span className="text-amber-300">
                              证据：{st}（{EVIDENCE_RANK.indexOf(st)}/{EVIDENCE_RANK.length - 1}）
                            </span>
                          )}
                        </div>
                      );
                    })}
                    {!world.state_slots.length && <span className="text-xs text-slate-500">空</span>}
                  </div>

                  <h3 className="text-xs font-bold text-slate-400 mb-2">事件流（最近 8）</h3>
                  <div className="space-y-1">
                    {world.events.slice(-8).reverse().map((ev) => (
                      <div key={ev.event_id} className="text-xs text-slate-400">
                        <span className="text-slate-600">#{ev.turn}</span>{" "}
                        <span className="text-glow">{ev.action_kind ?? "?"}</span> {ev.outcome_summary ?? ""}
                        {ev.blocked ? <span className="text-accent ml-1">[被拦截]</span> : null}
                        {ev.time_advance ? <span className="text-slate-600"> · +{ev.time_advance.elapsed}s</span> : null}
                      </div>
                    ))}
                    {!world.events.length && <span className="text-xs text-slate-500">空</span>}
                  </div>
                </div>

                <div className="rounded-2xl bg-panel border border-white/10 p-6">
                  <h3 className="text-sm font-bold mb-3">执行回合</h3>
                  <input
                    value={rawInput}
                    onChange={(e) => setRawInput(e.target.value)}
                    placeholder="行动意图，如：查看档案、质询林烬、标记血衣为已收集"
                    className="w-full rounded-lg bg-panel2 border border-white/10 px-3 py-2 text-sm mb-2"
                  />
                  <textarea
                    value={mutation}
                    onChange={(e) => setMutation(e.target.value)}
                    rows={10}
                    spellCheck={false}
                    className="w-full rounded-lg bg-panel2 border border-white/10 px-3 py-2 text-xs font-mono outline-none focus:border-accent"
                  />
                  <div className="mt-2 flex items-center gap-3">
                    <button
                      onClick={step}
                      disabled={busy}
                      className="rounded-lg bg-emerald-600 px-5 py-2 text-sm font-bold text-white disabled:opacity-40"
                    >
                      {busy ? "执行中…" : "执行"}
                    </button>
                    {blocked !== null && (
                      <span className={`text-sm ${blocked ? "text-accent" : "text-mint"}`}>
                        {blocked ? "回合被拦截" : "已应用"}
                      </span>
                    )}
                    {lastEvent && <span className="text-xs text-slate-400">事件 {lastEvent.event_id}</span>}
                  </div>
                </div>
              </>
            ) : (
              <div className="rounded-2xl bg-panel border border-white/10 p-10 text-center text-slate-400">
                新建或选择一个试玩会话
              </div>
            )}
          </section>
        </div>
      </div>
      </main>
    </>
  );
}