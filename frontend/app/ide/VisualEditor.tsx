"use client";

// 手动编辑内容的「可视化编辑器」：把「手动编辑内容」从 JSON 文本框升级为字段级表单。
import { useState } from "react";
import type { ArtifactOut } from "@/types";

type Field = { key: string; label: string; type: "text" | "textarea" | "tags" | "list" };

const KIND_FIELDS: Record<string, Field[]> = {
  scene: [
    { key: "title", label: "标题", type: "text" },
    { key: "location", label: "地点", type: "text" },
    { key: "time", label: "时间", type: "text" },
    { key: "summary", label: "场景概述", type: "textarea" },
    { key: "characters_present", label: "出镜角色", type: "tags" },
    { key: "events", label: "事件推进", type: "list" },
    { key: "atmosphere", label: "氛围", type: "text" },
    { key: "continuity_notes", label: "衔接备注", type: "textarea" },
  ],
  character_card: [
    { key: "name", label: "姓名", type: "text" },
    { key: "role", label: "定位", type: "text" },
    { key: "age", label: "年龄", type: "text" },
    { key: "gender", label: "性别", type: "text" },
    { key: "appearance", label: "外貌", type: "textarea" },
    { key: "personality", label: "性格", type: "tags" },
    { key: "background", label: "背景", type: "textarea" },
    { key: "goal", label: "目标", type: "textarea" },
    { key: "conflict", label: "冲突", type: "textarea" },
    { key: "secret", label: "秘密", type: "textarea" },
  ],
  world_bible: [
    { key: "title", label: "标题", type: "text" },
    { key: "setting", label: "设定", type: "textarea" },
    { key: "era", label: "时代", type: "text" },
    { key: "location", label: "地域", type: "text" },
    { key: "rules", label: "世界规则", type: "list" },
    { key: "technology", label: "科技水准", type: "text" },
    { key: "consistency_notes", label: "一致性备注", type: "textarea" },
  ],
  relationship_graph: [{ key: "graph_id", label: "关系图 ID", type: "text" }],
};

const NAME_LABEL: Record<string, string> = {
  title: "标题", summary: "概述", location: "地点", time: "时间",
  atmosphere: "氛围", events: "事件", visual_direction: "视觉", camera_direction: "运镜",
  stage_direction: "舞台", continuity_notes: "衔接", name: "姓名", role: "定位",
  age: "年龄", gender: "性别", appearance: "外貌", personality: "性格", background: "背景",
  goal: "目标", conflict: "冲突", secret: "秘密", setting: "设定", era: "时代",
  rules: "规则", technology: "科技", graph_id: "关系图 ID",
};

function baseKind(k: string) {
  const i = k.indexOf(":");
  return i >= 0 ? k.slice(0, i) : k;
}

function Control({
  value,
  onValue,
  type,
}: {
  value: unknown;
  onValue: (v: unknown) => void;
  type: Field["type"];
}) {
  const inputCls =
    "mt-1 w-full rounded-md bg-panel border border-white/10 px-2 py-1.5 text-sm text-slate-200 outline-none focus:border-accent";
  if (type === "textarea") {
    return <textarea className={inputCls} rows={3} value={String(value ?? "")} onChange={(e) => onValue(e.target.value)} />;
  }
  if (type === "tags" || type === "list") {
    const arr = Array.isArray(value) ? (value as string[]) : [];
    return (
      <div className="mt-1 flex flex-wrap gap-1.5">
        {arr.map((it, i) => (
          <span key={i} className="inline-flex items-center gap-1 rounded-md bg-panel2 border border-white/10 px-2 py-0.5 text-xs text-slate-300">
            <input
              className="w-28 bg-transparent text-slate-200 outline-none"
              value={it}
              onChange={(e) => {
                const nxt = arr.slice();
                nxt[i] = e.target.value;
                onValue(nxt);
              }}
            />
            <button className="text-accent" onClick={() => onValue(arr.filter((_, j) => j !== i))}>✕</button>
          </span>
        ))}
        <button
          className="rounded-md border border-dashed border-white/20 px-2 py-0.5 text-xs text-slate-400 hover:text-slate-200"
          onClick={() => onValue([...arr, ""])}
        >
          ＋ 项
        </button>
      </div>
    );
  }
  return <input className={inputCls} value={String(value ?? "")} onChange={(e) => onValue(e.target.value)} />;
}

export default function VisualEditor({
  artifact,
  onChange,
}: {
  artifact: ArtifactOut;
  onChange: (content: Record<string, unknown>) => void;
}) {
  const [draft, setDraft] = useState<Record<string, unknown>>(artifact.content ?? {});
  const patch = (k: string, v: unknown) => {
    const next = { ...draft, [k]: v };
    setDraft(next);
    onChange(next);
  };

  const fields = KIND_FIELDS[baseKind(artifact.kind)];
  if (fields) {
    return (
      <div className="space-y-3">
        {fields.map((f) => (
          <div key={f.key}>
            <label className="block text-xs text-slate-400">{f.label}</label>
            <Control value={draft[f.key]} onValue={(v) => patch(f.key, v)} type={f.type} />
          </div>
        ))}
      </div>
    );
  }

  const entries = Object.entries(draft);
  if (entries.length === 0) {
    return <p className="text-xs text-slate-500">该内容暂无可视化字段，点击右上「开始编辑」查看原始视图。</p>;
  }
  return (
    <div className="space-y-3">
      {entries.map(([k, v]) => (
        <div key={k}>
          <label className="block text-xs text-slate-400">{NAME_LABEL[k] ?? k}</label>
          <Control
            value={v}
            onValue={(nv) => patch(k, nv)}
            type={Array.isArray(v) ? "list" : "textarea"}
          />
        </div>
      ))}
    </div>
  );
}