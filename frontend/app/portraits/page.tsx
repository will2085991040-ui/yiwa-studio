"use client";

import { useEffect, useState, type ReactNode } from "react";
import { authenticatedFetch, batchGeneratePortraits, generatePortrait, generateVariantImage, getCharacter, updateCharacter } from "@/lib/api";

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

type TCard = {
  character_id: string;
  name: string;
  role: string;
  age: string;
  gender: string;
  appearance: string;
  personality: string[];
  background: string;
  motivation: string;
  goal: string;
  conflict: string;
  fear: string;
  secret: string;
  relationship_rules: string[];
  likes: string[];
  dislikes: string[];
  hidden_information: string[];
  character_arc: string[];
  possible_endings: string[];
  speech_style: { tone: string; formality: string; catchphrases: string[]; quirks: string[] };
};

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
  const [genBusy, setGenBusy] = useState(false);
  const [variantBusy, setVariantBusy] = useState<string | "">("");
  const [cardOpen, setCardOpen] = useState(false);
  const [cardBusy, setCardBusy] = useState(false);
  const [card, setCard] = useState<TCard | null>(null);
  const [exportName, setExportName] = useState("");

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

  const relink = async () => {
    if (!activeId) return;
    const d = await (await authenticatedFetch(`/api/projects/${projectId}/characters/${activeId}/portrait`)).json();
    setPortrait({ ...d, appearance: { ...EMPTY_APPEARANCE, ...(d.appearance ?? {}) } });
    setView({ version: d.version, base_prompt: d.base_prompt, variant_prompts: d.variant_prompts });
  };

  // ---- 角色全部资料弹窗（编辑并保存到角色卡）----
  const openCard = async () => {
    if (!activeId || cardBusy) return;
    try {
      const d = await getCharacter(projectId, activeId);
      const c = d?.card as Partial<TCard> | null | undefined;
      const fields = (k: string): string[] => Array.isArray(c?.[k as keyof TCard]) ? (c?.[k as keyof TCard] as string[]) : [];
      const base: TCard = {
        character_id: c?.character_id || activeId,
        name: c?.name || "",
        role: c?.role || "",
        age: c?.age || "",
        gender: c?.gender || "",
        appearance: c?.appearance || "",
        personality: fields("personality"),
        background: c?.background || "",
        motivation: c?.motivation || "",
        goal: c?.goal || "",
        conflict: c?.conflict || "",
        fear: c?.fear || "",
        secret: c?.secret || "",
        relationship_rules: fields("relationship_rules"),
        likes: fields("likes"),
        dislikes: fields("dislikes"),
        hidden_information: fields("hidden_information"),
        character_arc: fields("character_arc"),
        possible_endings: fields("possible_endings"),
        speech_style: {
          tone: (c?.speech_style as { tone?: string })?.tone ?? "",
          formality: (c?.speech_style as { formality?: string })?.formality ?? "",
          catchphrases: Array.isArray((c?.speech_style as { catchphrases?: string[] })?.catchphrases) ? (c?.speech_style as { catchphrases: string[] }).catchphrases : [],
          quirks: Array.isArray((c?.speech_style as { quirks?: string[] })?.quirks) ? (c?.speech_style as { quirks: string[] }).quirks : [],
        },
      };
      setCard(base);
      setCardOpen(true);
    } catch (e) {
      // 角色卡不存在则给空表单
      setCard({
        character_id: activeId, name: "", role: "", age: "", gender: "", appearance: "",
        personality: [], background: "", motivation: "", goal: "", conflict: "", fear: "", secret: "",
        relationship_rules: [], likes: [], dislikes: [], hidden_information: [], character_arc: [], possible_endings: [],
        speech_style: { tone: "", formality: "", catchphrases: [], quirks: [] },
      });
      setCardOpen(true);
    }
  };

  const saveCard = async () => {
    if (!card || cardBusy) return;
    setCardBusy(true);
    setMsg(null);
    try {
      await updateCharacter(projectId, activeId, card, "立绘资料弹窗编辑角色卡");
      setMsg({ ok: true, text: `已保存角色「${card.name || activeId}」的全部资料` });
      // 同步角色列表与立绘名
      const cs = await (await authenticatedFetch(`/api/projects/${projectId}/characters`)).json();
      if (Array.isArray(cs)) setCharacters(cs);
      setPortrait((p) => (p ? { ...p, name: card.name || p.name } : p));
      setCardOpen(false);
    } catch (e) {
      setMsg({ ok: false, text: e instanceof Error ? e.message : "保存角色资料失败" });
    } finally {
      setCardBusy(false);
    }
  };

  const setCardField = (k: keyof TCard, v: string | string[]) =>
    setCard((c) => (c ? { ...c, [k]: v } : c));

  const setCardList = (k: keyof TCard, raw: string) =>
    setCard((c) => (c ? { ...c, [k]: raw.split("\n").map((x) => x.trim()).filter(Boolean) } : c));

  // 名称导出打码：用「导出命名（脱敏代称）」作为输出文件名前缀，隐藏真实角色名
  const safe = (s: string) => s.trim().replace(/[\\/:*?"<>|]+/g, "_").replace(/\s+/g, "-").slice(0, 40) || "untitled";
  const downloadFile = async (url: string, label: string) => {
    const mask = safe(exportName || portrait?.name || activeId);
    const name = `${mask}-${safe(label)}.png`;
    try {
      if (url.startsWith("data:")) {
        const a = document.createElement("a");
        a.href = url; a.download = name; a.target = "_blank"; a.rel = "noreferrer";
        document.body.appendChild(a); a.click(); a.remove();
        return;
      }
      const blob = await (await fetch(url)).blob();
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob); a.download = name;
      document.body.appendChild(a); a.click();
      setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
    } catch {
      window.open(url, "_blank");
    }
  };

  const oneClick = async (force = false) => {
    if (!activeId || genBusy) return;
    setGenBusy(true);
    setMsg(null);
    try {
      const d = await generatePortrait(projectId, activeId, portrait?.style ?? "二次元立绘", portrait?.aspect ?? "9:16", force);
      setMsg({ ok: true, text: `已一键生成立绘（读角色卡合成提示词）→ 已存入资产` });
      if (d.portrait) {
        setPortrait({ ...(d.portrait as unknown as TPortrait), appearance: { ...EMPTY_APPEARANCE, ...(d.portrait as { appearance?: Record<string, string> }).appearance ?? {} } });
      }
      setView({
        version: (d.portrait as { version?: number })?.version ?? 0,
        base_prompt: d.prompt, variant_prompts: {},
      });
      await relink();
    } catch (e) {
      setMsg({ ok: false, text: e instanceof Error ? e.message : "一键生成立绘失败" });
    } finally {
      setGenBusy(false);
    }
  };

  const genVariant = async (variantId: string) => {
    if (!activeId || variantBusy) return;
    setVariantBusy(variantId);
    setMsg(null);
    try {
      const d = await generateVariantImage(projectId, activeId, variantId, {});
      setMsg({ ok: true, text: `差分「${variantId}」已生成图片` });
      if (d.portrait) {
        setPortrait({ ...(d.portrait as unknown as TPortrait), appearance: { ...EMPTY_APPEARANCE, ...(d.portrait as { appearance?: Record<string, string> }).appearance ?? {} } });
        setView({ version: (d.portrait as { version?: number })?.version ?? 0, base_prompt: d.prompt, variant_prompts: {} });
      }
      await relink();
    } catch (e) {
      setMsg({ ok: false, text: e instanceof Error ? e.message : "生成本差分图失败" });
    } finally {
      setVariantBusy("");
    }
  };

  const imageUrl = (v: TVariant) => {
    const img = v.image as { url?: string; data_url?: string } | null | undefined;
    if (img?.url) return img.url;
    if (img?.data_url) return img.data_url;
    return "";
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
          onClick={() => { void oneClick(); }}
          disabled={genBusy || !activeId}
          title="一键：自动读取该角色角色卡的外貌 → 合成提示词 → 生成基础立绘并存入资产"
          className="rounded bg-sky-600 px-3 py-1.5 text-sm hover:bg-sky-500 disabled:opacity-40"
        >
          {genBusy ? "● 一键生成中…" : "⚡ 一键生成立绘（读角色卡）"}
        </button>
        <button
          onClick={() => { void openCard(); }}
          disabled={!activeId || cardBusy}
          title="弹出窗口填写/编辑该角色全部资料（姓名、身份、外貌、背景、对白风格等），保存到角色卡"
          className="rounded border border-sky-500/50 bg-sky-500/10 px-3 py-1.5 text-sm text-sky-100 hover:bg-sky-500/20 disabled:opacity-40"
        >
          {cardBusy ? "…" : "✏️ 角色资料"}
        </button>
        <button
          onClick={batchGenerate}
          disabled={batchBusy || !activeId}
          className="rounded bg-fuchsia-600 px-3 py-1.5 text-sm hover:bg-fuchsia-500 disabled:opacity-40"
        >
          {batchBusy ? "生成中…" : "⚡ 批量生成差分"}
        </button>
      </header>

      <div className="grid grid-cols-1 gap-6 px-6 py-6 lg:grid-cols-2">
        {/* 已生成立绘图 */}
        <section className="rounded-xl border border-slate-800 bg-slate-900 p-4 lg:col-span-2">
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
            <h2 className="font-semibold">已生成立绘（关联角色卡 · 可做视频/图生视频首帧）</h2>
            <div className="flex items-center gap-2">
              <label className="flex items-center gap-1 text-[11px] text-slate-400" title="导出时的脱敏代称，避免在文件名里暴露真实角色名">
                导出命名（脱敏）
                <input value={exportName} onChange={(e) => setExportName(e.target.value)} placeholder={portrait.name || activeId} className="w-40 rounded bg-slate-800 px-2 py-1 text-[11px] text-slate-100" />
              </label>
              <button onClick={() => { void relink(); }} className="rounded bg-slate-700 px-2 py-1 text-xs">↻ 刷新</button>
            </div>
          </div>
          {portrait.variants.filter((v) => imageUrl(v)).length === 0 ? (
            <p className="text-[11px] text-slate-500">
              还没有已生成的立绘图。点上方「⚡ 一键生成立绘（读角色卡）」或对下方每个差分点「🎨 生成」。
            </p>
          ) : (
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5">
              {portrait.variants.map((v) => {
                const url = imageUrl(v);
                if (!url) return null;
                return (
                  <div key={v.variant_id} className="overflow-hidden rounded-lg border border-slate-700">
                    <img src={url} alt={v.name} className="aspect-[9/16] w-full object-cover" loading="lazy" />
                    <div className="px-1.5 py-1 text-[9px] text-slate-400">
                      {v.name || v.variant_id}{v.variant_id === portrait.base_variant_id ? " · 基础" : ""} · {v.style || portrait.style}
                    </div>
                    <button
                      onClick={() => { void downloadFile(url, `${v.name || v.variant_id}-立绘`); }}
                      title={`用导出命名「${exportName || portrait.name || activeId}」作为脱敏文件名保存`}
                      className="block w-full border-t border-slate-700 bg-slate-800 py-1 text-center text-[10px] text-slate-300 hover:bg-slate-700"
                    >⬇ 下载（命名导出）</button>
                    <a
                      href={`/storyboard?project=${encodeURIComponent(projectId)}`}
                      target="_blank" rel="noreferrer"
                      className="block w-full border-t border-slate-700 bg-slate-800 py-1 text-center text-[10px] font-bold text-accent hover:bg-slate-700"
                      title="去分镜页为剧情节点用这张立绘作为首帧生成视频（人物一致）"
                    >🎬 去生成视频</a>
                  </div>
                );
              })}
            </div>
          )}
        </section>

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
              <div className="mt-2 flex items-center gap-2">
                {imageUrl(v) ? (
                  <img src={imageUrl(v)} alt={v.name} className="h-12 w-9 rounded border border-slate-700 object-cover" loading="lazy" />
                ) : (
                  <span className="h-12 w-9 grid place-items-center rounded border border-dashed border-slate-700 text-[10px] text-slate-600">无图</span>
                )}
                <button
                  onClick={() => { void genVariant(v.variant_id); }}
                  disabled={!!variantBusy}
                  className="rounded bg-sky-600/80 px-2 py-1 text-xs text-white hover:bg-sky-500 disabled:opacity-40"
                  title="用该差分提示词生成立绘图（人物一致性锁定），结果写回此差分并作为资产"
                >
                  {variantBusy === v.variant_id ? "● 生成中…" : "🎨 生成此差分图"}
                </button>
                <span className="text-[10px] text-slate-500">{v.status === "saved" && imageUrl(v) ? "已生成" : "未生成"}</span>
              </div>
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

      {/* 角色全部资料弹窗 */}
      {cardOpen && card && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" onClick={() => !cardBusy && setCardOpen(false)}>
          <div className="max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-2xl border border-slate-700 bg-slate-900 p-5 text-slate-100" onClick={(e) => e.stopPropagation()}>
            <div className="mb-4 flex items-center justify-between">
              <h2 className="text-lg font-bold">角色全部资料 <span className="text-xs font-normal text-slate-500">（{activeId}）</span></h2>
              <button onClick={() => setCardOpen(false)} className="rounded border border-slate-700 px-2 py-1 text-xs hover:bg-slate-800" disabled={cardBusy}>✕ 关闭</button>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <Field label="姓名"><input className="w-full rounded bg-slate-800 px-2 py-1 text-sm" value={card.name} onChange={(e) => setCardField("name", e.target.value)} /></Field>
              <Field label="角色定位 role">
                <input className="w-full rounded bg-slate-800 px-2 py-1 text-sm" value={card.role} onChange={(e) => setCardField("role", e.target.value)} />
              </Field>
              <Field label="年龄"><input className="w-full rounded bg-slate-800 px-2 py-1 text-sm" value={card.age} onChange={(e) => setCardField("age", e.target.value)} /></Field>
              <Field label="性别"><input className="w-full rounded bg-slate-800 px-2 py-1 text-sm" value={card.gender} onChange={(e) => setCardField("gender", e.target.value)} /></Field>
            </div>
            <Field label="外貌特征"><textarea rows={2} className="w-full rounded bg-slate-800 px-2 py-1 text-sm" value={card.appearance} onChange={(e) => setCardField("appearance", e.target.value)} /></Field>
            <Field label="性格标签（每行一个）"><textarea rows={2} className="w-full rounded bg-slate-800 px-2 py-1 text-sm" value={card.personality.join("\n")} onChange={(e) => setCardList("personality", e.target.value)} /></Field>
            <Field label="背景故事"><textarea rows={3} className="w-full rounded bg-slate-800 px-2 py-1 text-sm" value={card.background} onChange={(e) => setCardField("background", e.target.value)} /></Field>
            <Field label="动机"><textarea rows={2} className="w-full rounded bg-slate-800 px-2 py-1 text-sm" value={card.motivation} onChange={(e) => setCardField("motivation", e.target.value)} /></Field>
            <Field label="目标 / 冲突 / 恐惧 / 秘密">
              <div className="grid grid-cols-2 gap-2">
                <input className="rounded bg-slate-800 px-2 py-1 text-sm" placeholder="目标" value={card.goal} onChange={(e) => setCardField("goal", e.target.value)} />
                <input className="rounded bg-slate-800 px-2 py-1 text-sm" placeholder="冲突" value={card.conflict} onChange={(e) => setCardField("conflict", e.target.value)} />
                <input className="rounded bg-slate-800 px-2 py-1 text-sm" placeholder="恐惧" value={card.fear} onChange={(e) => setCardField("fear", e.target.value)} />
                <input className="rounded bg-slate-800 px-2 py-1 text-sm" placeholder="秘密" value={card.secret} onChange={(e) => setCardField("secret", e.target.value)} />
              </div>
            </Field>
            <Field label="喜好（每行一个）"><textarea rows={2} className="w-full rounded bg-slate-800 px-2 py-1 text-sm" value={card.likes.join("\n")} onChange={(e) => setCardList("likes", e.target.value)} /></Field>
            <Field label="厌恶（每行一个）"><textarea rows={2} className="w-full rounded bg-slate-800 px-2 py-1 text-sm" value={card.dislikes.join("\n")} onChange={(e) => setCardList("dislikes", e.target.value)} /></Field>
            <Field label="对白风格">
              <div className="grid grid-cols-2 gap-2">
                <input className="rounded bg-slate-800 px-2 py-1 text-sm" placeholder="语气基调" value={card.speech_style.tone} onChange={(e) => setCard((c) => (c ? { ...c, speech_style: { ...c.speech_style, tone: e.target.value } } : c))} />
                <input className="rounded bg-slate-800 px-2 py-1 text-sm" placeholder="正式程度" value={card.speech_style.formality} onChange={(e) => setCard((c) => (c ? { ...c, speech_style: { ...c.speech_style, formality: e.target.value } } : c))} />
                <input className="rounded bg-slate-800 px-2 py-1 text-sm" placeholder="口头禅(逗号分隔)" value={card.speech_style.catchphrases.join(",")} onChange={(e) => setCard((c) => (c ? { ...c, speech_style: { ...c.speech_style, catchphrases: e.target.value.split(",").map((x) => x.trim()).filter(Boolean) } } : c))} />
                <input className="rounded bg-slate-800 px-2 py-1 text-sm" placeholder="口癖(逗号分隔)" value={card.speech_style.quirks.join(",")} onChange={(e) => setCard((c) => (c ? { ...c, speech_style: { ...c.speech_style, quirks: e.target.value.split(",").map((x) => x.trim()).filter(Boolean) } } : c))} />
              </div>
            </Field>
            <Field label="关系行为规则（每行一个）"><textarea rows={2} className="w-full rounded bg-slate-800 px-2 py-1 text-sm" value={card.relationship_rules.join("\n")} onChange={(e) => setCardList("relationship_rules", e.target.value)} /></Field>
            <Field label="隐藏信息 / 角色弧光 / 可达结局">
              <div className="grid grid-cols-3 gap-2">
                <textarea className="rounded bg-slate-800 px-2 py-1 text-sm" placeholder="隐藏信息(每行一条)" rows={3} value={card.hidden_information.join("\n")} onChange={(e) => setCardList("hidden_information", e.target.value)} />
                <textarea className="rounded bg-slate-800 px-2 py-1 text-sm" placeholder="角色弧光(每行一条)" rows={3} value={card.character_arc.join("\n")} onChange={(e) => setCardList("character_arc", e.target.value)} />
                <textarea className="rounded bg-slate-800 px-2 py-1 text-sm" placeholder="可达结局(每行一条)" rows={3} value={card.possible_endings.join("\n")} onChange={(e) => setCardList("possible_endings", e.target.value)} />
              </div>
            </Field>
            <div className="mt-4 flex justify-end gap-2">
              <button onClick={() => setCardOpen(false)} className="rounded border border-slate-700 px-3 py-1.5 text-sm hover:bg-slate-800">取消</button>
              <button onClick={() => { void saveCard(); }} disabled={cardBusy} className="rounded bg-emerald-600 px-4 py-1.5 text-sm hover:bg-emerald-500 disabled:opacity-40">
                {cardBusy ? "保存中…" : "保存角色资料"}
              </button>
            </div>
            <p className="mt-2 text-[10px] text-slate-500">保存后写入角色卡，供剧情/立绘/分镜的一致性 & AI 生成复用。</p>
          </div>
        </div>
      )}
    </main>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="mb-2 block text-xs text-slate-400">
      <span className="mb-0.5 block font-semibold text-slate-300">{label}</span>
      {children}
    </label>
  );
}