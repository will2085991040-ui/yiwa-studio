"use client";

// 登录网关：当后端处于「强制登录」模式（AUTH_REQUIRED=true，EXE/生产开启）且本地无
// 有效 token 时，在客户端把进入应用的页面重定向到 /login；已登录或非强制模式则放行。
// 预渲染/服务端阶段直接透传子组件（保持页面 HTML 的完整内容），仅在客户端判断是否需要跳转，
// 因此不会因为网关占位把 / 与 /settings 等页面的原始标题内容给吞掉。
import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { getAuthStatus, getToken } from "@/lib/api";

export default function AuthGate({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname() || "/";
  const [pending, setPending] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (pathname.startsWith("/login")) return; // 登录页本身公开
      if (getToken()) return; // 已持有 token 直接放行
      try {
        const status = await getAuthStatus();
        if (cancelled) return;
        if (status?.auth_required) {
          setPending(true); // 短暂显示引导，随后交 /login
          window.location.replace(`/login?from=${encodeURIComponent(pathname)}`); // 硬跳转，静态导出环境稳定
        }
      } catch {
        // 静态/离线拿不到状态：默认放行，不阻塞开发体验
      }
    })();
    return () => { cancelled = true; };
  }, [pathname, router]);

  if (pending) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[#0b0d1f] text-sm text-slate-500">
        正在校验登录…
      </div>
    );
  }
  return <>{children}</>;
}