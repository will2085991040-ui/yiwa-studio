"use client";

// 角色关系图：可视化编辑 + AI 一键根据角色卡生成 + 基于关系新增角色。
// 全部走真实后端（relations 端点 / characters 端点），不造假数据。
import { useEffect, useState } from "react";
import TopNav from "@/components/TopNav";
import { listRelations, saveRelations, genRelations, newCharacterFromRelation, type RelGraph } from "@/lib/api";
import { listCharacters } from "@/lib/api";

export default function RelationsPage() {
  const [projectId, setProjectId] = useState("");
  const [pidInput, setPidInput] = useState("");
  const [graph, setGraph] = useState<RelGraph>({ graph_id: "", characters: [], edges: [] });
  const [chars, setChars] = useState<{ character_id: string; name: string; role: string; description: string }[]>([]);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");

  // 新建边表单
  const [nSrc, setNSrc] = useState("");
  const [nTgt, setNTgt] = useState("");
  const [nType, setNType] = useState("相识");
  // 新增角色（基于关系）
  const [cName, setCName] = useState("");
  const [cRole, setCRole] = useState("");
  const [cDesc, setCDesc] = useState("");
  const [cRelSrc, setCRelSrc] = useState("");
  const [cRelType, setCRelType] = useState("相识");

  useEffect(() => {
    const pid = new URLSearchParams(window.location.search).get("project") ?? "";
    setProjectId(pid);
  }, []);

  useEffect(() => {
    if (!projectId) return;
    Promise.all([listRelations(projectId).catch(() => null), listCharacters(projectId).catch(() => [])])
      .then(([g, c]) => {
        if (g) setGraph(g);
        setChars(c as { character_id: string; name: string; role: string; description: string }[]);
      })
      .catch(() => setMsg("读取关系图失败"));
  }, [projectId]);

  const nameOf = (id: string) => chars.find((c) => c.character_id === id)?.name || id;

  const aiGene = async () => {
    setBusy(true);
    setMsg("");
    try {
      const g = await genRelations(projectId);
      setGraph(g);
      setMsg("✅ AI 已按角色卡一键生成关系图");
    } catch (e) {
      setMsg(`生成失败：${String((e as Error).message ?? e)}`);
    } finally {
      setBusy(false);
    }
  };

  const addEdge = async () => {
    if (!nSrc || !nTgt || nSrc === nTgt) { setMsg("请选择两个不同角色"); return; }
    const eid = `rel-${nSrc}->${nTgt}-${Date.now()}`;
    const next: RelGraph = {
      ...graph,
      edges: [...graph.edges, {
        edge_id: eid, source_character: nSrc, target_character: nTgt, relationship_type: nType,
        initial_value: 0, affection: 0, trust: 0, hostility: 0,
        secrets: [], rules: [], triggers: [], possible_changes: [], relationship_arc: [],
      }],
    };
    setBusy(true);
    try {
      setGraph(await saveRelations(projectId, next));
      setNSrc(""); setNTgt(""); setNType("相识");
      setMsg("✅ 已新增关系");
    } catch (e) { setMsg(`保存失败：${String((e as Error).message ?? e)}`); }
    finally { setBusy(false); }
  };

  const delEdge = async (edgeId: string) => {
    const next = { ...graph, edges: graph.edges.filter((e) => e.edge_id !== edgeId) };
    setBusy(true);
    try { setGraph(await saveRelations(projectId, next)); setMsg("已删除该关系"); }
    catch (e) { setMsg(`保存失败：${String((e as Error).message ?? e)}`); }
    finally { setBusy(false); }
  };

  const newChar = async () => {
    if (!cName.trim()) { setMsg("请填写新角色名"); return; }
    setBusy(true);
    try {
      const r = await newCharacterFromRelation(projectId, {
        name: cName.trim(), role: cRole.trim() || "角色", description: cDesc.trim(),
        relations: cRelSrc ? [{ source_character: cRelSrc, relationship_type: cRelType }] : [],
      });
      setGraph(r.graph);
      setCName(""); setCRole(""); setCDesc(""); setCRelSrc("");
      setMsg(`✅ 已创建角色「${r.character.name}」并连到关系源`);
      listCharacters(projectId).then((c) => setChars(c as never)).catch(() => {});
    } catch (e) { setMsg(`创建失败：${String((e as Error).message ?? e)}`); }
    finally { setBusy(false); }
  };

  const inputCls = "rounded-md bg-panel border border-white/10 px-2 py-1.5 text-sm text-slate-200 outline-none focus:border-accent";

  return (
    <div className="min-h-screen bg-[#0b0d1f] text-slate-100">
      <TopNav active="minigame" projectId={projectId}>
        <input
          value={pidInput}
          onChange={(e) => setPidInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && pidInput.trim()) setProjectId(pidInput.trim()); }}
          placeholder="项目 ID"
          className="w-40 rounded-md bg-panel2 px-2 py-1 text-xs text-slate-200 outline-none placeholder:text-slate-500"
        />
      </TopNav>
      <main className="mx-auto max-w-6xl p-5">
        <div className="flex items-center justify-between">
          <h1 className="text-lg font-bold">角色关系图 {projectId ? `· ${projectId.slice(0, 8)}` : ""}</h1>
          <div className="flex gap-2">
            <button onClick={aiGene} disabled={busy || !projectId}
              className="rounded-md bg-accent/20 px-3 py-1.5 text-xs font-bold text-accent disabled:opacity-50">✨ AI 一键生成关系图</button>
          </div>
        </div>
        {msg && <p className="mt-2 text-xs text-glow">{msg}</p>}

        {/* 角色与关系 */}
        <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
          {/* 角色 */}
          <div className="rounded-xl border border-white/10 bg-panel/40 p-3">
            <div className="text-sm font-bold">角色 {chars.length}</div>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {chars.map((c) => (
                <span key={c.character_id} className="rounded-full border border-white/10 bg-panel2 px-2 py-1 text-xs">
                  {c.name}<span className="ml-1 text-slate-500">{c.role}</span>
                </span>
              ))}
              {!chars.length && <span className="text-xs text-slate-500">暂无角色，请先在「IDE 角色」里创建。</span>}
            </div>
          </div>

          {/* 关系列表 */}
          <div className="rounded-xl border border-white/10 bg-panel/40 p-4">
            <div className="flex items-center justify-between">
              <div className="text-sm font-bold">关系边 {graph.edges.length}</div>
              <div className="flex gap-1 text-[10px]">
                <select value={nSrc} onChange={(e) => setNSrc(e.target.value)} className={inputCls}>
                  <option value="">来源角色…</option>
                  {chars.map((c) => <option key={c.character_id} value={c.character_id}>{c.name}</option>)}
                </select>
                <select value={nTgt} onChange={(e) => setNTgt(e.target.value)} className={inputCls}>
                  <option value="">目标角色…</option>
                  {chars.map((c) => <option key={c.character_id} value={c.character_id}>{c.name}</option>)}
                </select>
                <input value={nType} onChange={(e) => setNType(e.target.value)} className={`${inputCls} w-24`} placeholder="关系类型" />
                <button onClick={addEdge} disabled={busy} className="rounded bg-accent/20 px-2 py-1 text-accent">＋ 边</button>
              </div>
            </div>
            <div className="mt-2 space-y-1">
              {graph.edges.map((e) => (
                <div key={e.edge_id} className="flex items-center justify-between rounded bg-panel2/60 px-2 py-1 text-xs">
                  <span>
                    <b>{nameOf(e.source_character)}</b>
                    <span className="mx-1 text-slate-500">--[{e.relationship_type}]--&gt;</span>
                    <b>{nameOf(e.target_character)}</b>
                  </span>
                  <button onClick={() => delEdge(e.edge_id)} className="text-rose-300 hover:text-rose-400">✕</button>
                </div>
              ))}
              {!graph.edges.length && <span className="text-xs text-slate-500">还没有关系，点「AI 一键生成」或手动加边。</span>}
            </div>
          </div>
        </div>

        {/* 基于关系新增角色 */}
        <div className="mt-4 rounded-xl border border-white/10 bg-panel/40 p-4">
          <div className="text-sm font-bold">新增角色（基于设定关系）</div>
          <div className="mt-2 flex flex-wrap items-end gap-2 text-xs">
            <label className="flex flex-col gap-1"><span className="text-slate-500">名字</span>
              <input value={cName} onChange={(e) => setCName(e.target.value)} className={`${inputCls} w-36`} /></label>
            <label className="flex flex-col gap-1"><span className="text-slate-500">角色</span>
              <input value={cRole} onChange={(e) => setCRole(e.target.value)} className={`${inputCls} w-28`} /></label>
            <label className="flex flex-col gap-1"><span className="text-slate-500">关联到（已有角色）</span>
              <select value={cRelSrc} onChange={(e) => setCRelSrc(e.target.value)} className={inputCls}>
                <option value="">（无）</option>
                {chars.map((c) => <option key={c.character_id} value={c.character_id}>{c.name}</option>)}
              </select></label>
            <label className="flex flex-col gap-1"><span className="text-slate-500">关系类型</span>
              <input value={cRelType} onChange={(e) => setCRelType(e.target.value)} className={`${inputCls} w-24`} /></label>
            <label className="flex flex-1 flex-col gap-1"><span className="text-slate-500">简介</span>
              <input value={cDesc} onChange={(e) => setCDesc(e.target.value)} className={inputCls} /></label>
            <button onClick={newChar} disabled={busy}
              className="rounded-md bg-mint/20 px-3 py-2 text-xs font-bold text-mint disabled:opacity-50">创建角色</button>
          </div>
        </div>
      </main>
    </div>
  );
}