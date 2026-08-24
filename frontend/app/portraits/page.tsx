"use client";

import { useEffect, useState } from "react";
import { authenticatedFetch, batchGeneratePortraits } from "@/lib/api";

type TVariant = {
  variant_id: string;
  name: string;
  category: string | null;
  value: string;
  description: string;
  style: string;
  aspect: string;
  image: Record<string, unknown> | null;
  status: string;
  source: string;
  created_at: string;
};
type TPortrait = {
  character_id: string;
  name: string;
  appearance: Record<string, string>;
  style: string;
  aspect: string;
  base_variant_id: string | null;
  variants: TVariant[];
};
type TSection = { key: string; label: string; hint: string };
type TCharacter = { character_id: string; name: string; role: string };

const EMPTY_APPEARANCE: Record<string, string> = {
  basic: "", face: "", hair: "", clothing: "", props: "", demeanor: "", pose: "", lighting: "",
};

function variantUid() {
  return `v-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
}

export default function PortraitsPage() {
  const [projectId, setProjectId] = useState("");
  const [characters, setCharacters] = useState<TCharacter[]>([]);
  const [activeId, setActiveId] = useState("");
  const [sections, setSections] = useState<TSection[]>([]);
  const [styles, setStyles] = useState<string[]>([]);
  const [ratios, setRatios] = useState<string[]>([]);
  const [portrait, setPortrait] = useState<TPortrait | null>(null);
  const [view, setView] = useState<{ version: number; base_prompt: string; variant_prompts: Record<string, string> } | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [batchBusy, setBatchBusy] = useState(false);

  useEffect(() => {
    setProjectId(new URLSearchParams(window.location.search).get("project") ?? "");
    authenticatedFetch("/api/portraits/template")
      .then((r) => r.json())
      .then((t) => {
        setSections(t.sections ?? []);
        setStyles(t.styles ?? []);
        setRatios(t.aspect_ratios ?? []);
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (!projectId) return;
    authenticatedFetch(`/api/projects/${projectId}/characters`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((cs: TCharacter[]) => {
        setCharacters(cs);
        if (cs.length) setActiveId(cs[0].character_id);
      })
      .catch(() => setCharacters([]));
  }, [projectId]);

  useEffect(() => {
    if (!projectId || !activeId) return;
    authenticatedFetch(`/api/projects/${projectId}/characters/${activeId}/portrait`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((d: TPortrait & { version: number; base_prompt: string; variant_prompts: Record<string, string> }) => {
        setPortrait({ ...d, appearance: { ...EMPTY_APPEARANCE, ...(d.appearance ?? {}) } });
        setView({ version: d.version, base_prompt: d.base_prompt, variant_prompts: d.variant_prompts });
      })
      .catch(() => {});
  }, [projectId, activeId]);

  if (!portrait) {
    return (
      <main className="min-h-screen bg-slate-950 px-6 py-10 text-slate-100">
        <div className="mx-auto max-w-4xl">
          <a href="/" className="text-sm text-slate-500 hover:text-white">← 首页</a>
          <h1 className="mt-4 text-2xl font-bold">角色立绘 · 差分</h1>
          <p className="mt-4 text-slate-400">
            {projectId ? (characters.length ? "请选择角色。" : "该项目还没有角色卡，请先在工作台生成角色。") : "缺少 project 参数。"}
          </p>
          {characters.length > 0 && (
            <div className="mt-6 space-y-2">
              {characters.map((c) => (
                <button key={c.character_id} onClick={() => setActiveId(c.character_id)} className="mr-2 rounded border border-slate-700 px-3 py-1.5 text-sm hover:bg-slate-800">
                  {c.name} · {c.role || c.character_id}
                </button>
              ))}
            </div>
          )}
        </div>
      </main>
    );
  }

  const setAppearance = (key: string, value: string) =>
    setPortrait((p) => (p ? { ...p, appearance: { ...p.appearance, [key]: value } } : p));

  const setVariant = (i: number, patch: Partial<TVariant>) =>
    setPortrait((p) => (p ? { ...p, variants: p.variants.map((v, j) => (j === i ? { ...v, ...patch } : v)) } : p));

  const addVariant = () =>
    setPortrait((p) =>
      p
        ? {
            ...p,
            variants: [...p.variants, {
              variant_id: variantUid(), name: "新差分", category: "expression", value: "",
              description: "", style: p.style, aspect: p.aspect, image: null, status: "saved",
              source: "seed", created_at: new Date().toISOString(),
            }],
          }
        : p,
    );

  const removeVariant = (i: number) =>
    setPortrait((p) => (p ? { ...p, variants: p.variants.filter((_, j) => j !== i) } : p));

  const save = async () => {
    if (!portrait) return;
    const r = await authenticatedFetch(`/api/projects/${projectId}/characters/${activeId}/portrait`, {
      method: "PUT",
      body: JSON.stringify({ portrait, change_reason: "立绘差分手动编辑" }),
    });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) setMsg({ ok: false, text: d?.error?.message || `HTTP ${r.status}` });
    else {
      setMsg({ ok: true, text: `已保存 v${d.version}` });
      setView({ version: d.version, base_prompt: d.base_prompt, variant_prompts: d.variant_prompts });
    }
  };

  const promote = async (variantId: string) => {
    const r = await authenticatedFetch(`/api/projects/${projectId}/characters/${activeId}/portrait/promote`, {
      method: "POST",
      body: JSON.stringify({ variant_id: variantId }),
    });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) setMsg({ ok: false, text: d?.error?.message || `HTTP ${r.status}` });
    else {
      setPortrait((p) => (p ? { ...p, base_variant_id: d.base_variant_id, variants: d.variants } : p));
      setView({ version: d.version, base_prompt: d.base_prompt, variant_prompts: d.variant_prompts });
      setMsg({ ok: true, text: "已提升为基础立绘（原基础立绘已自动备份）" });
    }
  };

  const batchGenerate = async () => {
    if (!activeId || batchBusy) return;
    setBatchBusy(true);
    setMsg(null);
    try {
      const d = await batchGeneratePortraits(projectId, [activeId || ""]);
      setMsg({ ok: true, text: `批量差分完成：共生成 ${d.total_generated} 张` });
      const r = await authenticatedFetch(`/api/projects/${projectId}/characters/${activeId}/portrait`);
      if (r.ok) {
        const nd = await r.json();
        setPortrait({ ...nd, appearance: { ...EMPTY_APPEARANCE, ...(nd.appearance ?? {}) } });
        setView({ version: nd.version, base_prompt: nd.base_prompt, variant_prompts: nd.variant_prompts });
      }
    } catch (e) {
      setMsg({ ok: false, text: e instanceof Error ? e.message : "批量生成失败" });
    } finally {
      setBatchBusy(false);
    }
  };

  return (
    <main className="min-h-screen bg-slate-950 text-slate-100">
      <header className="flex items-center gap-3 border-b border-slate-800 px-6 py-3">
        <a href="/" className="text-sm text-slate-500 hover:text-white">← 首页</a>
        {projectId && <a href={`/agent?project=${projectId}`} className="text-sm text-slate-500 hover:text-white">← 工作台</a>}
        <h1 className="text-lg font-semibold">角色立绘 · 差分</h1>
        <select value={activeId} onChange={(e) => setActiveId(e.target.value)} className="ml-2 rounded bg-slate-800 px-2 py-1 text-sm">
          {characters.map((c) => <option key={c.character_id} value={c.character_id}>{c.name}</option>)}
        </select>
        <button onClick={save} className="ml-auto rounded bg-emerald-600 px-3 py-1.5 text-sm hover:bg-emerald-500">保存</button>
        <button
          onClick={batchGenerate}
          disabled={batchBusy || !activeId}
          className="rounded bg-fuchsia-600 px-3 py-1.5 text-sm hover:bg-fuchsia-500 disabled:opacity-40"
        >
          {batchBusy ? "生成中…" : "⚡ 批量生成差分"}
        </button>
      </header>

      <div className="grid grid-cols-1 gap-6 px-6 py-6 lg:grid-cols-2">
        {/* 8 段外貌 */}
        <section className="space-y-3 rounded-xl border border-slate-800 bg-slate-900 p-4">
          <div className="flex items-center justify-between">
            <h2 className="font-semibold">外貌（8 段）</h2>
            <div className="flex items-center gap-2 text-sm">
              <label className="text-xs text-slate-400">风格</label>
              <select value={portrait.style} onChange={(e) => setPortrait((p) => (p ? { ...p, style: e.target.value } : p))} className="rounded bg-slate-800 px-2 py-1 text-xs">
                {styles.map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
              <label className="text-xs text-slate-400">比例</label>
              <select value={portrait.aspect} onChange={(e) => setPortrait((p) => (p ? { ...p, aspect: e.target.value } : p))} className="rounded bg-slate-800 px-2 py-1 text-xs">
                {ratios.map((r) => <option key={r} value={r}>{r === "9:16" ? "竖屏 9:16" : r === "16:9" ? "横屏 16:9" : r === "1:1" ? "方形 1:1" : r}</option>)}
              </select>
            </div>
          </div>
          {sections.map((s) => (
            <label key={s.key} className="block text-xs">
              <span className="text-slate-400">{s.label} <span className="text-slate-600">· {s.hint}</span></span>
              <textarea
                value={portrait.appearance[s.key] ?? ""}
                onChange={(e) => setAppearance(s.key, e.target.value)}
                rows={2}
                className="mt-1 w-full rounded bg-slate-800 px-2 py-1 text-slate-100"
              />
            </label>
          ))}
        </section>

        {/* 差分 */}
        <section className="space-y-3 rounded-xl border border-slate-800 bg-slate-900 p-4">
          <div className="flex items-center justify-between">
            <h2 className="font-semibold">差分（{portrait.variants.length}）</h2>
            <button onClick={addVariant} className="rounded bg-slate-700 px-2 py-1 text-xs">+ 差分</button>
          </div>
          {portrait.variants.map((v, i) => (
            <div key={v.variant_id} className={`rounded-lg border p-3 ${portrait.base_variant_id === v.variant_id ? "border-amber-500 bg-amber-500/10" : "border-slate-700"}`}>
              <div className="mb-1 flex items-center gap-2">
                {portrait.base_variant_id === v.variant_id && <span className="text-xs font-bold text-amber-400">基础</span>}
                <input value={v.name} onChange={(e) => setVariant(i, { name: e.target.value })} className="w-24 rounded bg-slate-800 px-2 py-1 text-sm" />
                <input value={v.value} onChange={(e) => setVariant(i, { value: e.target.value })} className="w-24 rounded bg-slate-800 px-2 py-1 text-sm" placeholder="取值" />
                <input value={v.category ?? ""} onChange={(e) => setVariant(i, { category: e.target.value || null })} className="w-24 rounded bg-slate-800 px-2 py-1 text-sm" placeholder="类别" />
                <button onClick={() => removeVariant(i)} className="rounded bg-rose-700 px-2 py-1 text-xs">删</button>
                {portrait.base_variant_id !== v.variant_id && (
                  <button onClick={() => promote(v.variant_id)} className="rounded bg-amber-600 px-2 py-1 text-xs">提升为基础</button>
                )}
              </div>
              <textarea value={v.description} onChange={(e) => setVariant(i, { description: e.target.value })} rows={2} className="w-full rounded bg-slate-800 px-2 py-1 text-sm" placeholder="差分提示词" />
            </div>
          ))}
        </section>

        {/* 提示词预览 */}
        <section className="rounded-xl border border-slate-800 bg-slate-900 p-4 lg:col-span-2">
          <h2 className="mb-2 font-semibold">合成提示词预览 {view ? `(v${view.version})` : ""}</h2>
          <pre className="whitespace-pre-wrap rounded-lg bg-slate-950 p-3 text-xs text-slate-300">{view?.base_prompt ?? ""}</pre>
          {view && Object.entries(view.variant_prompts).map(([vid, p]) => (
            <details key={vid} className="mt-2">
              <summary className="cursor-pointer text-xs text-slate-400">
                差分 {vid} · {portrait.variants.find((v) => v.variant_id === vid)?.name ?? ""}
              </summary>
              <pre className="whitespace-pre-wrap rounded bg-slate-950 p-2 text-xs text-slate-400">{p}</pre>
            </details>
          ))}
        </section>
      </div>

      {msg && <div className="px-6 pb-6 text-sm"><span className={msg.ok ? "text-emerald-400" : "text-rose-400"}>{msg.text}</span></div>}
    </main>
  );
}