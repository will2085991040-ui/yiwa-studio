"use client";

import type { ReactNode } from "react";

function NavLink({ href, active, children }: { href: string; active?: boolean; children: ReactNode }) {
  return (
    <a
      href={href}
      className={`rounded-lg px-3 py-1.5 text-sm transition-colors ${
        active ? "bg-accent/15 text-accent" : "text-slate-300 hover:bg-white/5 hover:text-white"
      }`}
    >
      {children}
    </a>
  );
}

export default function TopNav({
  active,
  projectId,
  children,
}: {
  active?: "home" | "relations" | "settings" | "minigame" | "account";
  projectId?: string;
  children?: ReactNode;
}) {
  return (
    <header className="sticky top-0 z-20 border-b border-white/10 bg-[#14162a]/90 backdrop-blur">
      <div className="mx-auto flex h-14 max-w-7xl items-center gap-3 px-5">
        <a href="/" className="flex items-center gap-2 font-black tracking-tight">
          <span className="grid h-7 w-7 place-items-center rounded-lg bg-gradient-to-br from-[#d90b46] to-accent text-xs text-white">
            Y
          </span>
          <span className="text-white">
            YIWA<span className="ml-1 text-xs font-normal text-slate-400">互动影游创作</span>
          </span>
        </a>

        <nav className="ml-3 flex items-center gap-1">
          <NavLink href="/" active={active === "home"}>创作</NavLink>
          <NavLink href="/relations" active={active === "relations"}>关系图</NavLink>
          <NavLink href="/minigame-maker" active={active === "minigame"}>小游戏</NavLink>
          <NavLink href="/settings" active={active === "settings"}>模型设置</NavLink>
          <NavLink href="/account" active={active === "account"}>点数账户</NavLink>
        </nav>

        <div className="ml-auto flex items-center gap-2">
          {projectId && (
            <span className="mr-1 hidden rounded-full border border-white/10 bg-panel2 px-3 py-1 text-xs text-slate-400 sm:block">
              项目 {projectId.slice(0, 8)}
            </span>
          )}
          {children}
        </div>
      </div>
    </header>
  );
}