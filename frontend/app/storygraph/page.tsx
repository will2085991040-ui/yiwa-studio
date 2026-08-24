"use client";

import { useEffect, useState } from "react";
import dynamic from "next/dynamic";

const Editor = dynamic(() => import("./Editor"), {
  ssr: false,
  loading: () => <p className="p-8 text-slate-400">正在加载画布…</p>,
});

export default function StoryGraphPage() {
  const [projectId, setProjectId] = useState("");

  useEffect(() => {
    setProjectId(new URLSearchParams(window.location.search).get("project") ?? "");
  }, []);

  return (
    <main className="min-h-screen bg-slate-950 text-slate-100">
      <header className="flex items-center justify-between border-b border-slate-800 px-6 py-3">
        <h1 className="text-lg font-semibold">互动剧本画布 · 节点编辑器</h1>
        <div className="flex items-center gap-3 text-sm">
          {projectId && (
            <a className="text-slate-400 hover:text-white" href={`/agent?project=${projectId}`}>
              ← 工作台
            </a>
          )}
          <a className="text-slate-400 hover:text-white" href="/">
            首页
          </a>
        </div>
      </header>
      {projectId ? (
        <Editor projectId={projectId} />
      ) : (
        <p className="p-8 text-slate-400">缺少 project 参数，请从工作台进入。</p>
      )}
    </main>
  );
}