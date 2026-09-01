"use client";

// 资产（Assets）：汇总所有 Agent 生成的视频 / 图片 / 文本 / 其他产物。
import { useCallback, useEffect, useState } from "react";
import { listAssets } from "@/lib/api";
import type { AssetOut } from "@/types";

const SPIN_SVG =
  "data:image/svg+xml;charset=utf-8," +
  encodeURIComponent(
    "<svg xmlns='http://www.w3.org/2000/svg' width='80' height='80' viewBox='0 0 80 80'><rect width='80' height='80' rx='10' fill='%230b0a1c'/><path d='M20 55 L35 34 L46 48 L56 30 L62 46' fill='none' stroke='%237c3aed' stroke-width='3' stroke-linejoin='round'/><circle cx='28' cy='26' r='4' fill='%23ec4899'/></svg>"
  );

const TYPE_BADGE: Record<AssetOut["type"], { label: string; cls: string }> = {
  video: { label: "🎬 视频", cls: "border-accent/40 bg-accent/10 text-accent" },
  image: { label: "🖼 图片", cls: "border-mint/40 bg-mint/10 text-mint" },
  text: { label: "📄 文本", cls: "border-sky/40 bg-sky/10 text-sky" },
  other: { label: "🗂 其他", cls: "border-white/10 bg-white/5 text-slate-300" },
};

function TypeIcon({ t }: { t: AssetOut["type"] }) {
  return <>{t === "video" ? "🎬" : t === "image" ? "🖼" : t === "text" ? "📄" : "🗂"}</>;
}

function AssetCard({ asset, onOpen }: { asset: AssetOut; onOpen: (a: AssetOut) => void }) {
  const badge = TYPE_BADGE[asset.type] ?? TYPE_BADGE.other;
  const hasUrl = !!asset.url;
  return (
    <button
      onClick={() => hasUrl && onOpen(asset)}
      className="group flex flex-col overflow-hidden rounded-xl border border-white/10 bg-panel2/70 text-left transition hover:-translate-y-0.5 hover:border-white/20 hover:shadow-[0_8px_30px_-12px_rgba(124,58,237,0.5)]"
    >
      <div className="relative h-28 overflow-hidden bg-[#0b0a1c]">
        {asset.type === "video" && hasUrl ? (
          <video src={asset.url} className="h-full w-full object-cover" muted preload="metadata" onError={(e) => ((e.currentTarget.style.display = "none"))} />
        ) : asset.type === "image" && hasUrl ? (
          <img src={asset.url} alt={asset.title} className="h-full w-full object-contain" loading="lazy" onError={(e) => ((e.currentTarget.style.display = "none"))} />
        ) : (
          <div className="grid h-full w-full place-items-center opacity-50">
            <img src={SPIN_SVG} alt="" className="h-16 w-16" />
          </div>
        )}
        {!hasUrl && (
          <div className="absolute inset-x-0 bottom-0 bg-black/60 px-2 py-0.5 text-[10px] text-slate-300">（无直链）</div>
        )}
        <span className={`absolute left-1.5 top-1.5 rounded-md border px-1.5 py-0.5 text-[10px] backdrop-blur ${badge.cls}`}>
          {badge.label}
        </span>
      </div>
      <div className="p-2">
        <div className="truncate text-xs font-bold text-white" title={asset.title}>{asset.title}</div>
        <div className="mt-0.5 flex items-center gap-1 text-[10px] text-slate-500">
          <span className="truncate">{asset.project_title || "未命名项目"}</span>
          <span>·</span>
          <span>{asset.kind_label}</span>
        </div>
      </div>
    </button>
  );
}

export default function AssetsPanel({ onClose }: { onClose?: () => void }) {
  const [assets, setAssets] = useState<AssetOut[]>([]);
  const [filter, setFilter] = useState<"all" | AssetOut["type"]>("all");
  const [viewer, setViewer] = useState<AssetOut | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    setLoading(true); setErr("");
    try {
      setAssets(await listAssets());
    } catch (e) {
      setErr((e as Error).message || "加载资产失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const filtered = filter === "all" ? assets : assets.filter((a) => a.type === filter);
  const kindGroups: Record<string, number> = {};
  for (const a of assets) {
    const k = a.kind_label || "其他";
    kindGroups[k] = (kindGroups[k] ?? 0) + 1;
  }

  return (
    <div className="flex h-full flex-col">
      {/* 工具栏 */}
      <div className="flex flex-wrap items-center gap-2 border-b border-white/10 p-3">
        <span className="text-sm font-black text-white">🗂 资产</span>
        <span className="text-[10px] text-slate-500">{assets.length} 项 · 全项目</span>
        <div className="ml-2 flex flex-wrap gap-1">
          {(["all", "video", "image", "text", "other"] as const).map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`rounded-md px-2 py-1 text-xs capitalize ${
                filter === f ? "bg-accent/20 text-accent" : "bg-white/5 text-slate-300 hover:bg-white/10"
              }`}
            >
              {f === "all" ? "全部" : TYPE_BADGE[f].label}
            </button>
          ))}
        </div>
        <div className="ml-auto flex items-center gap-1.5">
          <button onClick={() => void load()} className="rounded-md border border-white/10 bg-panel2 px-2 py-1 text-xs text-slate-300 hover:bg-white/5">↻ 刷新</button>
          {onClose && <button onClick={onClose} className="rounded-md border border-white/10 px-2 py-1 text-xs text-slate-300 hover:bg-white/5">关闭</button>}
        </div>
      </div>

      {/* 统计条 */}
      <div className="flex flex-wrap gap-1.5 border-b border-white/10 px-3 py-2">
        {Object.entries(kindGroups).length === 0 ? (
          <span className="text-[11px] text-slate-500">暂无资产</span>
        ) : (
          Object.entries(kindGroups).map(([k, n]) => (
            <span key={k} className="rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-[10px] text-slate-300">
              {k} × {n}
            </span>
          ))
        )}
      </div>

      {/* 内容 */}
      <div className="flex-1 overflow-y-auto p-3">
        {err && <p className="rounded-lg border border-red-400/30 bg-red-400/10 p-3 text-xs text-red-200">{err}</p>}
        {loading && <p className="p-6 text-center text-xs text-slate-500">加载中…</p>}
        {!loading && !err && filtered.length === 0 && (
          <p className="p-8 text-center text-sm text-slate-500">
            {assets.length === 0 ? "还没有任何资产。去「创作」里让 Agent 生成剧本、分镜、立绘或视频吧。" : "当前筛选下没有资产。"}
          </p>
        )}
        {!loading && !err && filtered.length > 0 && (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
            {filtered.map((a) => (
              <AssetCard key={a.id} asset={a} onOpen={setViewer} />
            ))}
          </div>
        )}
      </div>

      {/* 查看器 */}
      {viewer && <AssetViewer asset={viewer} onClose={() => setViewer(null)} />}
    </div>
  );
}

function AssetViewer({ asset, onClose }: { asset: AssetOut; onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/70 p-6" onClick={onClose}>
      <div className="max-h-[88vh] w-full max-w-3xl overflow-hidden rounded-2xl border border-white/15 bg-[#12112a] shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between border-b border-white/10 px-4 py-2">
          <div className="min-w-0">
            <div className="truncate text-sm font-bold text-white">{asset.title}</div>
            <div className="text-[10px] text-slate-500">{asset.kind_label} · {asset.project_title} · v{asset.version} · 来自 {asset.agent}</div>
          </div>
          <div className="flex items-center gap-1">
            {asset.url && (
              <>
                <a href={asset.url} download className="rounded-md border border-white/20 bg-white/5 px-2 py-1 text-xs text-slate-200 hover:bg-white/10" title="保存到本地">⬇ 下载</a>
                <a href={asset.url} target="_blank" rel="noreferrer" className="rounded-md border border-white/20 bg-white/5 px-2 py-1 text-xs text-slate-200 hover:bg-white/10">打开链接 ↗</a>
              </>
            )}
            <button onClick={onClose} className="rounded-md border border-white/10 px-2 py-1 text-xs text-slate-400 hover:bg-white/10">✕</button>
          </div>
        </div>
        <div className="max-h-[70vh] overflow-y-auto bg-[#0b0a1c] p-4">
          {asset.type === "video" && asset.url ? (
            <video src={asset.url} className="w-full rounded-lg" controls autoPlay loop />
          ) : asset.type === "image" && asset.url ? (
            <img src={asset.url} alt={asset.title} className="mx-auto max-h-[62vh] rounded-lg" />
          ) : (
            <pre className="whitespace-pre-wrap rounded-lg bg-black/40 p-4 text-xs text-slate-200">{asset.title}</pre>
          )}
          <div className="mt-3 rounded-lg border border-white/10 bg-panel2 p-3 text-[11px] text-slate-300">
            <div><b className="text-slate-400">类型</b>：{asset.kind_label}</div>
            <div><b className="text-slate-400">Agent</b>：{asset.agent || "—"}</div>
            <div><b className="text-slate-400">版本</b>：v{asset.version}</div>
          </div>
        </div>
      </div>
    </div>
  );
}
