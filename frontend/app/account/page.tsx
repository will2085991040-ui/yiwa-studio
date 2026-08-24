"use client";

import { useCallback, useEffect, useState } from "react";
import TopNav from "@/components/TopNav";
import {
  getCreditLedger,
  getCreditOverview,
  getCreditPrices,
  mintCredit,
  redeemCredit,
  getToken,
  type CreditLedgerItem,
} from "@/lib/api";

const AMOUNTS = [10, 30, 50, 100, 300];

// 本地持久化的「我的兑换码」（面值 + 码 + 是否已兑换）
type MyCode = { code: string; yuan: number; engaged?: boolean; createdAt?: number };
const LS_KEY = "yiwa_my_codes";

function loadMyCodes(): MyCode[] {
  try {
    const raw = localStorage.getItem(LS_KEY);
    return raw ? (JSON.parse(raw) as MyCode[]) : [];
  } catch {
    return [];
  }
}

export default function AccountPage() {
  const [balance, setBalance] = useState<number | null>(null);
  const [markup, setMarkup] = useState(0.6);
  const [ledger, setLedger] = useState<CreditLedgerItem[]>([]);
  const [prices, setPrices] = useState<Record<string, [number, number]>>({});
  const [code, setCode] = useState("");
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  // ---- 充值 ----
  const [pick, setPick] = useState<number>(AMOUNTS[2]);
  const [custom, setCustom] = useState("");
  const [buyMsg, setBuyMsg] = useState("");
  const [myCodes, setMyCodes] = useState<MyCode[]>([]);

  const refreshMyCodes = useCallback(() => setMyCodes(loadMyCodes()), []);

  const load = useCallback(() => {
    getCreditOverview()
      .then((o) => { setBalance(o.balance); setMarkup(o.markup); })
      .catch((e) => setErr(e instanceof Error ? e.message : "加载失败"));
    getCreditLedger(20)
      .then((l) => setLedger(l.items))
      .catch(() => {});
    getCreditPrices()
      .then((p) => setPrices(p.defaults || {}))
      .catch(() => {});
  }, []);

  useEffect(() => { load(); refreshMyCodes(); }, [load, refreshMyCodes]);

  useEffect(() => {
    if (custom === "") return;
    const n = Number(custom);
    if (Number.isFinite(n) && n > 0) setPick(n);
  }, [custom]);

  if (!getToken()) {
    return (
      <main className="min-h-screen bg-[#0b0d1f] px-5 pt-24 text-slate-300">
        <div className="mx-auto max-w-xl rounded-2xl border border-white/10 bg-panel2 p-8 text-center">
          <h1 className="text-xl font-bold text-white">请先登录</h1>
          <p className="mt-2 text-sm">登录后即可查看并充值点数。</p>
          <a href="/login" className="mt-4 inline-block text-accent underline">前往登录</a>
        </div>
      </main>
    );
  }

  const submit = async () => {
    setMsg(""); setErr("");
    const c = code.trim().toUpperCase();
    if (!c) { setErr("请输入兑换码"); return; }
    try {
      const res = await redeemCredit(c);
      setBalance(res.balance);
      setMsg("兑换成功 +" + res.redeemed_points + " 点");
      setCode("");
      // 标记本地我已兑换
      const codes = loadMyCodes().map((m) => m.code === c ? { ...m, engaged: true } : m);
      localStorage.setItem(LS_KEY, JSON.stringify(codes));
      refreshMyCodes();
      load();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "兑换失败");
    }
  };

  const buy = async () => {
    setBuyMsg(""); setErr("");
    const yuan = pick > 0 ? pick : 0;
    if (yuan <= 0) { setErr("请选择充值金额"); return; }
    try {
      const m = await mintCredit(yuan, "线上充值（线下收款）");
      const updated = [...loadMyCodes(), { code: m.code, yuan: m.yuan, createdAt: Date.now() }];
      localStorage.setItem(LS_KEY, JSON.stringify(updated));
      refreshMyCodes();
      setBuyMsg("已生成 ¥" + m.yuan + " 兑换码，线下收款后可兑换入账");
      setCustom("");
    } catch (e) {
      setErr(e instanceof Error ? e.message : "充值失败");
    }
  };

  const copy = (txt: string) => {
    try { navigator.clipboard.writeText(txt); setBuyMsg("已复制：" + txt); } catch { setBuyMsg("请手动复制：" + txt); }
  };

  return (
    <div className="min-h-screen bg-[#0b0d1f]">
      <TopNav active="account" />
      <main className="mx-auto max-w-4xl px-5 py-10">
        <h1 className="text-2xl font-bold text-white">点数账户</h1>
        <p className="mt-1 text-sm text-slate-400">
          1点=1元；扣费=引擎成本÷0.6（约×1.67，含40%毛利）。余额可为负。充值=购买兑换码，线下收款后兑换入账。
        </p>

        {/* 充值 */}
        <section className="mt-6 rounded-2xl border border-white/10 bg-panel2 p-6">
          <h2 className="text-base font-semibold text-white">充值点数</h2>
          <p className="mt-1 text-xs text-slate-500">选择金额并生成兑换码，线下收款后凭码兑换</p>

          <div className="mt-4 flex flex-wrap gap-3">
            {AMOUNTS.map((a) => (
              <button
                key={a}
                onClick={() => setPick(a)}
                className={"rounded-xl border px-4 py-2 text-sm font-medium transition-colors " +
                  (pick === a ? "border-accent bg-accent/15 text-white" : "border-white/15 bg-white/5 text-slate-300 hover:border-white/40")}
              >
                ¥{a}
              </button>
            ))}
            <div className="flex items-center gap-2">
              <span className="text-sm text-slate-400">¥</span>
              <input
                value={custom}
                onChange={(e) => setCustom(e.target.value)}
                inputMode="decimal"
                placeholder="自定义"
                className="w-28 rounded-lg border border-white/15 bg-white/5 px-3 py-2 text-sm text-white outline-none focus:border-accent"
              />
            </div>
          </div>

          <div className="mt-4 flex items-center gap-3">
            <button
              onClick={buy}
              className="rounded-lg bg-gradient-to-r from-[#d90b46] to-accent px-6 py-2 text-sm font-semibold text-white"
            >
              充值 ¥{pick > 0 ? pick : ""}
            </button>
            <span className="text-xs text-slate-500">到账点数 = ¥金额</span>
          </div>
          {buyMsg && <div className="mt-3 rounded-lg bg-emerald-500/15 px-3 py-2 text-sm text-emerald-300">{buyMsg}</div>}

          {/* 我的兑换码 */}
          <div className="mt-5 border-t border-white/10 pt-4">
            <h3 className="text-sm font-semibold text-slate-300">我的兑换码</h3>
            {myCodes.length === 0 ? (
              <p className="mt-2 text-xs text-slate-500">还没有，选金额点「充值」即可生成</p>
            ) : (
              <ul className="mt-2 space-y-2">
                {myCodes.map((m, i) => (
                  <li key={i} className="flex items-center justify-between rounded-lg bg-white/5 px-3 py-2 text-sm">
                    <span className="text-slate-300">{m.code}</span>
                    <span className="flex items-center gap-2">
                      <span className="text-xs text-slate-400">¥{m.yuan}</span>
                      {m.engaged ? (
                        <span className="rounded bg-emerald-500/20 px-2 py-0.5 text-xs text-emerald-300">已兑换</span>
                      ) : (
                        <button onClick={() => copy(m.code)} className="rounded bg-white/10 px-2 py-0.5 text-xs text-white hover:bg-white/20">复制</button>
                      )}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </section>

        <div className="mt-6 grid gap-6 sm:grid-cols-2">
          <section className="rounded-2xl border border-white/10 bg-panel2 p-6">
            <div className="text-sm text-slate-400">当前点数</div>
            <div className="mt-1 text-4xl font-black text-white">
              {balance === null ? "…" : balance.toFixed(2)}
            </div>
            <div className="mt-3 text-xs text-slate-500">引擎单价（元/百万 token）</div>
            <ul className="mt-2 space-y-1 text-xs text-slate-400">
              {Object.entries(prices).map(([model, pair]) => (
                <li key={model} className="flex justify-between rounded bg-white/5 px-2 py-1">
                  <span>{model}</span>
                  <span>输入 ¥{pair[0]} / 输出 ¥{pair[1]}</span>
                </li>
              ))}
            </ul>
          </section>

          <section className="rounded-2xl border border-white/10 bg-panel2 p-6">
            <h2 className="text-base font-semibold text-white">兑换码充值</h2>
            <p className="mt-1 text-xs text-slate-500">输入兑换码到账点数</p>
            <div className="mt-4 flex gap-2">
              <input
                value={code}
                onChange={(e) => setCode(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && submit()}
                placeholder="XXXX-XXXX-XXXX"
                className="flex-1 rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm text-white outline-none focus:border-accent"
              />
              <button
                onClick={submit}
                className="rounded-lg bg-gradient-to-r from-[#d90b46] to-accent px-4 py-2 text-sm font-semibold text-white"
              >
                兑换
              </button>
            </div>
            {msg && <div className="mt-3 rounded-lg bg-emerald-500/15 px-3 py-2 text-sm text-emerald-300">{msg}</div>}
            {err && <div className="mt-3 rounded-lg bg-rose-500/15 px-3 py-2 text-sm text-rose-300">{err}</div>}
          </section>
        </div>

        <section className="mt-8 rounded-2xl border border-white/10 bg-panel2 p-6">
          <h2 className="text-base font-semibold text-white">最近流水</h2>
          {ledger.length === 0 ? (
            <p className="mt-3 text-sm text-slate-500">暂无流水</p>
          ) : (
            <ul className="mt-3 divide-y divide-white/5">
              {ledger.map((it) => (
                <li key={it.id} className="flex items-center justify-between py-2 text-sm">
                  <span className="text-slate-300">{it.note || it.model || it.kind}</span>
                  <span className={it.delta >= 0 ? "text-emerald-300" : "text-rose-300"}>
                    {it.delta >= 0 ? "+" : ""}{it.delta.toFixed(2)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>
      </main>
    </div>
  );
}
