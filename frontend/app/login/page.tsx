"use client";

// YIWA - Minimax style login: dark space + violet->cyan gradient + glass card.
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { loginAccount, registerAccount, setToken } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [tab, setTab] = useState<"login" | "register">("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");

  const submit = async () => {
    setMsg("");
    if (!username.trim() || !password) { setMsg("请填写用户名与密码"); return; }
    if (tab === "register" && password !== confirm) { setMsg("两次密码不一致"); return; }
    setBusy(true);
    try {
      const r = tab === "register"
        ? await registerAccount(username.trim(), password)
        : await loginAccount(username.trim(), password);
      setToken(r.token);
      setMsg("欢迎回来：" + r.user.username);
      router.push("/");
    } catch (e) {
      setMsg("操作失败：" + String((e as Error).message ?? e));
    } finally {
      setBusy(false);
    }
  };

  const inputCls = "w-full rounded-xl border border-white/10 bg-panel2/80 px-4 py-3 text-sm text-slate-100 outline-none placeholder:text-slate-500 focus:border-accent focus:ring-2 focus:ring-accent/30";

  const tabCls = (isActive: boolean) =>
    isActive
      ? "rounded-xl py-2.5 text-sm font-bold bg-gradient-to-r from-accent/80 to-sky/80 text-white shadow transition-all"
      : "rounded-xl py-2.5 text-sm font-bold text-slate-400 hover:text-white transition-all";

  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden bg-night p-6 text-slate-100">
      <div aria-hidden className="pointer-events-none absolute inset-0">
        <div className="absolute -left-24 top-10 h-80 w-80 rounded-full bg-accent/20 blur-3xl" />
        <div className="absolute -right-24 bottom-6 h-96 w-96 rounded-full bg-sky/15 blur-3xl" />
        <div className="absolute left-1/2 top-1/3 h-40 w-40 rounded-full bg-rose/10 blur-3xl" />
        <div className="absolute inset-0 opacity-[0.05]" style={{ backgroundImage: "radial-gradient(circle at 1px 1px, #fff 1px, transparent 0)", backgroundSize: "34px 34px" }} />
      </div>

      <div className="relative w-full max-w-sm">
        <Link href="/" className="mb-8 flex items-center justify-center gap-3 text-2xl font-black tracking-[0.25em]">
          <span className="grid h-11 w-11 place-items-center rounded-2xl bg-gradient-to-br from-accent via-sky to-rose text-sm font-black text-white shadow-[0_0_24px_rgba(139,92,246,0.5)]">∞</span>
          <span className="bg-gradient-to-r from-white to-sky bg-clip-text text-transparent">YIWA</span>
        </Link>

        <div className="rounded-3xl border border-white/10 bg-panel/70 p-7 shadow-[0_20px_60px_-20px_rgba(139,92,246,0.4)] backdrop-blur-xl">
          <div className="mb-6 grid grid-cols-2 rounded-2xl bg-panel2 p-1">
            {(["login", "register"] as const).map((t) => (
              <button key={t} onClick={() => { setTab(t); setMsg(""); }} className={tabCls(tab === t)}>
                {t === "login" ? "登录" : "注册"}
              </button>
            ))}
          </div>

          <label className="mb-3 block text-xs text-slate-400">
            用户名
            <input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" className={"mt-1 " + inputCls} />
          </label>
          <label className="mb-3 block text-xs text-slate-400">
            密码
            <input value={password} onChange={(e) => setPassword(e.target.value)} type="password" autoComplete={tab === "login" ? "current-password" : "new-password"}
              onKeyDown={(e) => { if (e.key === "Enter") submit(); }} className={"mt-1 " + inputCls} />
          </label>
          {tab === "register" && (
            <label className="mb-3 block text-xs text-slate-400">
              确认密码
              <input value={confirm} onChange={(e) => setConfirm(e.target.value)} type="password" autoComplete="new-password"
                onKeyDown={(e) => { if (e.key === "Enter") submit(); }} className={"mt-1 " + inputCls} />
            </label>
          )}

          {msg && <p className="mb-3 text-xs text-glow">{msg}</p>}

          <button
            onClick={submit}
            disabled={busy}
            className="w-full rounded-xl bg-gradient-to-r from-accent via-sky to-rose py-3.5 text-sm font-black tracking-widest text-white transition-all hover:scale-[1.02] hover:shadow-[0_0_30px_rgba(139,92,246,0.5)] disabled:opacity-60"
          >
            {busy ? "处理中…" : tab === "login" ? "进入 YIWA" : "创建账户"}
          </button>
          <p className="mt-5 text-center text-xs text-slate-500">
            无需真实邮箱，设置用户名+密码即可开始创作。
          </p>
        </div>
      </div>
    </div>
  );
}
