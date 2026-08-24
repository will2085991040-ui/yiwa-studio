import type { Metadata } from "next";
import "./globals.css";
import AuthGate from "./AuthGate";
import AiProgressBar from "@/components/AiProgressBar";

export const metadata: Metadata = {
  title: "YIWA Studio · AI 互动影视创作 OS",
  description: "AI 互动影视创作操作系统 —— 让每个脑内故事都能被写进帧里",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body>
        {/* 全局 AI 生成进度条：任何页面发起 AI 内容生成时顶部实时显示 */}
        <AiProgressBar />
        <AuthGate>{children}</AuthGate>
      </body>
    </html>
  );
}
