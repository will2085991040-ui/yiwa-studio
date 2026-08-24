"use client";

import { useEffect, useState } from "react";
import TopNav from "@/components/TopNav";
import { getSettings, updateSettings, type SettingsView } from "@/lib/api";

type Group = {
  title: string;
  hint: string;
  readyKey: "text_ready" | "image_ready" | "video_ready";
  providerField: string;
  providerOptions: [string, string][];
  fields: { key: string; label: string; placeholder: string; secret?: boolean }[];
};

const GROUPS: Group[] = [
  {
    title: "文本生成（新剧本 / Agent）",
    hint: "OpenAI 兼容接口；火山方舟填 https://ark.cn-beijing.volces.com/api/v3，模型填接入点 ep-xxx。",
    readyKey: "text_ready",
    providerField: "llm_provider",
    providerOptions: [
      ["mock", "离线 mock（无需 key）"],
      ["openai_compat", "OpenAI 兼容"],
    ],
    fields: [
      { key: "llm_base_url", label: "Base URL", placeholder: "https://api.deepseek.com" },
      { key: "llm_model", label: "模型", placeholder: "deepseek-chat" },
      { key: "llm_api_key", label: "API Key", placeholder: "sk-…", secret: true },
      { key: "llm_timeout_seconds", label: "请求超时(秒)", placeholder: "180（长剧情/分镜建议 180~300）" },
    ],
  },
  {
    title: "生图（火山方舟 / 硅基流动）",
    hint: "选了火山方舟就填 ark.cn-beijing.volces.com 的接入点 ep-xxx；硅基则填 siliconflow。",
    readyKey: "image_ready",
    providerField: "image_provider",
    providerOptions: [
      ["mock", "离线 mock"],
      ["ark", "火山方舟文生图"],
      ["siliconflow", "硅基流动"],
    ],
    fields: [
      { key: "image_base_url", label: "Base URL", placeholder: "https://ark.cn-beijing.volces.com/api/v3" },
      { key: "image_model", label: "模型/接入点", placeholder: "ep-… 或 doubao-seedream-…" },
      { key: "image_size", label: "尺寸", placeholder: "1024x1024" },
      { key: "image_api_key", label: "API Key", placeholder: "ark-…（留空则复用文本 key）", secret: true },
    ],
  },
  {
    title: "生视频（即梦/火山方舟 Seedance）",
    hint: "异步任务：提交 → 轮询 → 取视频；未配置按 mock 立即返回。",
    readyKey: "video_ready",
    providerField: "video_provider",
    providerOptions: [
      ["mock", "离线 mock"],
      ["seedance", "火山方舟 Seedance"],
    ],
    fields: [
      { key: "video_base_url", label: "Base URL", placeholder: "https://ark.cn-beijing.volces.com/api/v3" },
      { key: "video_model", label: "模型", placeholder: "doubao-seedance-1-0-pro-250528" },
      { key: "video_api_key", label: "API Key", placeholder: "ark-…", secret: true },
    ],
  },
];

const READY_LABEL: Record<string, { ok: string; no: string }> = {
  text_ready: { ok: "已配置", no: "未配置（mock）" },
  image_ready: { ok: "已配置", no: "未配置（mock）" },
  video_ready: { ok: "已配置", no: "未配置（mock）" },
  yiwa_ready: { ok: "已接入生成服务", no: "未接入" },
};

const SECRET_KEYS = new Set(["llm_api_key", "image_api_key", "video_api_key", "yiwa_token"]);

function genToken(): string {
  const rand = () => Math.random().toString(36).slice(2, 10);
  return `yiwa_${rand()}${rand()}${Date.now().toString(36).slice(-6)}`;
}

export default function SettingsPage() {
  const [view, setView] = useState<SettingsView | null>(null);
  const [form, setForm] = useState<Record<string, string | boolean>>({});
  const [clear, setClear] = useState<Set<string>>(new Set());
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [advancedOpen, setAdvancedOpen] = useState(false);

  useEffect(() => {
    getSettings()
      .then((v) => {
        setView(v);
        const init: Record<string, string | boolean> = {};
        for (const [k, val] of Object.entries(v.values)) init[k] = SECRET_KEYS.has(k) ? "" : val;
        setForm(init);
      })
      .catch((e) => setError(e instanceof Error ? e.message : "读取失败"));
  }, []);

  const set = (key: string, value: string) => {
    setForm((f) => ({ ...f, [key]: value }));
    setClear((c) => {
      const n = new Set(c);
      if (!value) n.delete(key);
      return n;
    });
  };

  const text = (key: string) => {
    const v = form[key];
    return typeof v === "string" ? v : "";
  };

  const markClear = (key: string) => {
    setForm((f) => ({ ...f, [key]: "" }));
    setClear((c) => new Set(c).add(key));
  };

  const save = async () => {
    setSaving(true);
    setMessage("");
    setError("");
    try {
      const payload: Record<string, string | boolean> = {};
      for (const g of GROUPS) {
        payload[g.providerField] = form[g.providerField] ?? "";
        for (const f of g.fields) {
          const v = form[f.key] ?? "";
          if (SECRET_KEYS.has(f.key) && !v && !clear.has(f.key)) continue; // 空且未标记清除 → 保留原 key
          payload[f.key] = v;
        }
      }
      for (const key of ["yiwa_token", "yiwa_gateway_url"]) {
        const v = form[key] ?? "";
        if (SECRET_KEYS.has(key) && !v && !clear.has(key)) continue;
        payload[key] = v;
      }
      payload["llm_disable_thinking"] = !!form["llm_disable_thinking"];
      const to = Number(form["llm_timeout_seconds"]);
      if (Number.isFinite(to) && to > 0) payload["llm_timeout_seconds"] = String(Math.round(to)); // 以字符串传，后端 pydantic 转 int 并钳位
      else delete payload["llm_timeout_seconds"]; // 空/非法 → 不覆盖，沿用后端默认 180s
      const updated = await updateSettings(payload);
      setView(updated);
      setClear(new Set());
      setMessage("已保存（密钥不进代码，重启后对生成接口生效）");
    } catch (e) {
      setError(e instanceof Error ? e.message : "保存失败");
    } finally {
      setSaving(false);
    }
  };

  return (
    <>
      <TopNav active="settings" />
      <main className="min-h-screen px-6 py-10">
        <div className="max-w-3xl mx-auto">
        <div className="flex items-center gap-3 mb-8">
          <h1 className="text-2xl font-bold">模型设置</h1>
          <span className="text-xs text-slate-500">生图 / 生视频 / 新剧本 API</span>
        </div>

        {error && !view && <p className="mb-4 text-sm text-accent">{error}（请确认后端已启动）</p>}
        {!view && !error && <p className="text-slate-400">加载中…</p>}

        {view && (
          <>
            <p className="mb-6 text-xs text-slate-500">
              配置文件：<code className="text-glow">{view.config_file}</code>
              <span className="ml-3 text-slate-600">{view.note}</span>
            </p>

            {/* YIWA 生成服务：单 Token + 网关（对照 Funloom Token，用户不直接填各厂 key） */}
            <section className="rounded-2xl bg-panel border border-glow/40 p-6 mb-4">
              <div className="flex items-center gap-3 mb-1">
                <h2 className="font-bold">YIWA 生成服务（推荐）</h2>
                <Badge ok={view.ready.yiwa_ready} label={READY_LABEL.yiwa_ready} />
              </div>
              <p className="text-xs text-slate-500 mb-4">
                只需填一个 YIWA Token 和网关地址，文本 / 生图 / 生视频统一走 YIWA 生成服务（Bearer 鉴权）。
              </p>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs text-slate-400 mb-1">网关地址</label>
                  <input
                    value={text("yiwa_gateway_url")}
                    placeholder="https://gateway.yiwa.example/api"
                    onChange={(e) => set("yiwa_gateway_url", e.target.value)}
                    className="w-full rounded-lg bg-panel2 border border-white/10 px-3 py-2 text-sm outline-none focus:border-accent"
                  />
                </div>
                <div>
                  <label className="block text-xs text-slate-400 mb-1">
                    YIWA Token
                    <button type="button" onClick={() => set("yiwa_token", genToken())} className="ml-2 text-glow hover:underline">
                      生成
                    </button>
                    {form["yiwa_token"] && (
                      <button type="button" onClick={() => markClear("yiwa_token")} className="ml-2 text-accent hover:underline">
                        清除
                      </button>
                    )}
                  </label>
                  <input
                    type="password"
                    value={text("yiwa_token")}
                    placeholder={view.values["yiwa_token"] ? `已保存（${view.values["yiwa_token"]}）` : "yiwa_…"}
                    onChange={(e) => set("yiwa_token", e.target.value)}
                    className="w-full rounded-lg bg-panel2 border border-white/10 px-3 py-2 text-sm outline-none focus:border-accent"
                  />
                </div>
              </div>
            </section>

            <button
              type="button"
              onClick={() => setAdvancedOpen((v) => !v)}
              className="mb-4 w-full rounded-xl border border-white/10 bg-panel2 px-4 py-3 text-sm text-slate-300 hover:bg-panel"
            >
              {advancedOpen ? "▾ 收起：高级 · 直连各厂" : "▸ 高级 · 直连各厂（SiliconFlow / 火山 Seedance）"}
            </button>

            {advancedOpen && (
            <div className="space-y-6 mb-4">
              {GROUPS.map((g) => (
                <section key={g.title} className="rounded-2xl bg-panel border border-white/10 p-6">
                  <div className="flex items-center gap-3 mb-1">
                    <h2 className="font-bold">{g.title}</h2>
                    <Badge ok={view.ready[g.readyKey]} label={READY_LABEL[g.readyKey]} />
                  </div>
                  <p className="text-xs text-slate-500 mb-4">{g.hint}</p>
                  <label className="block text-xs text-slate-400 mb-1">供应商</label>
                  <select
                    value={text(g.providerField)}
                    onChange={(e) => set(g.providerField, e.target.value)}
                    className="w-full rounded-lg bg-panel2 border border-white/10 px-3 py-2 text-sm mb-4 outline-none focus:border-accent"
                  >
                    {g.providerOptions.map(([val, label]) => (
                      <option key={val} value={val}>{label}</option>
                    ))}
                  </select>

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                    {g.fields.map((f) => (
                      <div key={f.key} className={f.secret ? "md:col-span-2" : ""}>
                        <label className="block text-xs text-slate-400 mb-1">
                          {f.label}
                          {f.secret && (
                            <button
                              type="button"
                              onClick={() => markClear(f.key)}
                              className="ml-2 text-accent hover:underline"
                            >
                              清除
                            </button>
                          )}
                        </label>
                        <input
                          type={f.secret ? "password" : "text"}
                          value={text(f.key)}
                          placeholder={
                            f.secret && (view.values[f.key] || "") ? `已保存（${view.values[f.key]}）` : f.placeholder
                          }
                          onChange={(e) => set(f.key, e.target.value)}
                          className="w-full rounded-lg bg-panel2 border border-white/10 px-3 py-2 text-sm outline-none focus:border-accent"
                        />
                      </div>
                    ))}
                  </div>

                  </section>
              ))}
                <section className="rounded-2xl bg-panel border border-white/10 p-6">
                  <label className="flex items-start gap-3 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={!!form["llm_disable_thinking"]}
                      onChange={(e) => setForm((f) => ({ ...f, llm_disable_thinking: e.target.checked }))}
                      className="mt-0.5 h-4 w-4 accent-[#d90b46]"
                    />
                    <span>
                      <span className="font-bold text-sm">关闭推理模型 thinking（更快更省，推荐）</span>
                      <span className="block text-xs text-slate-500">
                        火山方舟 DeepSeek 等推理模型会先“思考”再出结果，导致每个剧本步骤生成很慢。
                        勾选后结构化生成（世界观/人物/剧情/分镜/对白）直接产 JSON，速度快数倍；想要更强质量再取消。
                      </span>
                    </span>
                  </label>
                </section>
              </div>
            )}

            <div className="mt-6 flex items-center gap-4">
              <button
                onClick={save}
                disabled={saving}
                className="rounded-xl bg-gradient-to-r from-[#d90b46] to-accent px-8 py-3 font-bold text-white disabled:opacity-40"
              >
                {saving ? "保存中…" : "保存设置"}
              </button>
              {message && <span className="text-sm text-mint">{message}</span>}
              {error && <span className="text-sm text-accent">{error}</span>}
            </div>
          </>
        )}
        </div>
      </main>
    </>
  );
}

function Badge({ ok, label }: { ok: boolean; label: { ok: string; no: string } }) {
  return (
    <span
      className={`text-xs rounded-full px-3 py-1 border ${
        ok ? "border-mint/40 bg-mint/10 text-mint" : "border-white/10 bg-panel2 text-slate-400"
      }`}
    >
      {ok ? label.ok : label.no}
    </span>
  );
}