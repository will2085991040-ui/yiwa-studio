"use client";

import { useEffect, useMemo, useRef, useState } from "react";

// 配置驱动的小游戏渲染器：读取 ?config=<urlencoded JSON of MinigameConfig>
// 依 game_id 渲染不同小游戏（连点 / 记忆配对），一切参数来自配置，不再硬编码。
export type MiniConfig = {
  game_id?: string;
  title?: string;
  description?: string;
  success_result?: "success" | "perfect";
  score_variable?: string | null;
  settings?: {
    target?: number;
    time_limit_s?: number;
    grid?: number;
  };
};

const EMOJIS = ["🌙", "⭐", "☀️", "💎", "🌺", "🍀", "🔥", "⚡", "🦄", "🥇"];

function safePct(v: number | undefined, d: number): number {
  const n = Number(v);
  return Number.isFinite(n) && n > 0 ? Math.floor(n) : d;
}

export default function MinigamePage() {
  const [cfg, setCfg] = useState<MiniConfig>({});
  const [gameId, setGameId] = useState("click");

  useEffect(() => {
    const q = new URLSearchParams(window.location.search);
    setGameId(q.get("game") ?? "click");
    const raw = q.get("config");
    if (raw) {
      try {
        setCfg(JSON.parse(decodeURIComponent(raw)) as MiniConfig);
      } catch {
        setCfg({});
      }
    }
  }, []);

  const title = cfg.title || (gameId === "memory" ? "记忆配对" : "连点挑战");
  const description =
    cfg.description ||
    (gameId === "memory" ? "翻开卡片，找出所有配对的图案" : "在限定时间内完成点击次数");
  const settings = cfg.settings ?? {};

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-950 text-slate-100">
      <div className="w-full max-w-md rounded-2xl border border-slate-800 bg-slate-900 p-5 text-center">
        <div className="text-xs uppercase tracking-widest text-amber-400">小游戏 · {gameId}</div>
        <h1 className="mt-1 text-xl font-bold">{title}</h1>
        {description && <p className="mt-1 text-xs text-slate-400">{description}</p>}
        {gameId === "memory" ? (
          <MemoryGame settings={settings} onDone={(result, score) => {
            window.parent?.postMessage(
              { type: "funloom:minigame:complete", gameId, result, score }, "*",
            );
          }} />
        ) : (
          <ClickGame settings={settings} onDone={(result, score) => {
            window.parent?.postMessage(
              { type: "funloom:minigame:complete", gameId, result, score }, "*",
            );
          }} />
        )}
      </div>
    </div>
  );
}

function ClickGame({ settings, onDone }: { settings: MiniConfig["settings"]; onDone: (r: string, s: number) => void }) {
  const target = safePct(settings?.target, 8);
  const limit = safePct(settings?.time_limit_s, 8);
  const [clicks, setClicks] = useState(0);
  const [finished, setFinished] = useState<string | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const startRef = useRef<number | null>(null);

  const clickOne = () => {
    if (finished) return;
    if (startRef.current === null) startRef.current = Date.now();
    const next = clicks + 1;
    setClicks(next);
    if (next >= target) {
      const sec = (Date.now() - startRef.current) / 1000;
      setElapsed(Math.round(sec * 10) / 10);
      setFinished(sec <= limit ? "perfect" : "success");
      onDone(sec <= limit ? "perfect" : "success", next);
    }
  };

  return (
    <>
      <div className="mt-4 text-xs text-slate-400">完成 {target} 次点击 · {limit} 秒内为 perfect</div>
      <div className="mt-4 text-4xl font-black text-amber-300">{clicks} / {target}</div>
      {finished ? (
        <div className="mt-4 rounded-lg border border-emerald-600/50 bg-emerald-600/10 p-3 text-sm">
          <div className="font-bold text-emerald-300">{finished === "perfect" ? "完美！" : "完成"}</div>
          <div className="text-xs text-slate-400">用时 {elapsed}s · 成绩已回传</div>
        </div>
      ) : (
        <button
          onClick={clickOne}
          className="mt-5 h-28 w-28 rounded-full bg-gradient-to-br from-rose-500 to-amber-500 text-3xl font-black text-white shadow-lg active:scale-95"
        >
          点
        </button>
      )}
    </>
  );
}

function MemoryGame({ settings, onDone }: { settings: MiniConfig["settings"]; onDone: (r: string, s: number) => void }) {
  const pairs = Math.max(2, Math.min(6, Math.floor(safePct(settings?.grid, 8) / 2)));
  const limit = safePct(settings?.time_limit_s, 30);
  const deck = useMemo(() => {
    const items = EMOJIS.slice(0, pairs).flatMap((e) => [e, e]);
    return items
      .map((v, i) => ({ id: i, v, open: false, matched: false }))
      .sort(() => Math.random() - 0.5);
  }, [pairs]);

  const [cards, setCards] = useState(deck);
  const [first, setFirst] = useState<number | null>(null);
  const [moves, setMoves] = useState(0);
  const [finished, setFinished] = useState<string | null>(null);
  const [seconds, setSeconds] = useState(0);
  const lockRef = useRef(false);

  useEffect(() => {
    if (finished) return;
    const t = setInterval(() => {
      setSeconds((s) => {
        if (s + 1 >= limit) {
          clearInterval(t);
          setFinished("success");
          onDone("success", moves);
          return s;
        }
        return s + 1;
      });
    }, 1000);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [finished, limit, moves]);

  const flip = (id: number) => {
    if (lockRef.current || finished) return;
    const idx = cards.findIndex((c) => c.id === id);
    const card = cards[idx];
    if (!card || card.open || card.matched) return;
    const opened = cards.map((c) => (c.id === id ? { ...c, open: true } : c));
    setCards(opened);
    const nmoves = moves + 1;
    setMoves(nmoves);
    if (first === null) {
      setFirst(id);
      return;
    }
    lockRef.current = true;
    const a = opened[idx];
    const b = opened[cards.findIndex((c) => c.id === first)];
    if (b && a.v === b.v) {
      const matched = opened.map((c) => (c.id === id || c.id === first ? { ...c, matched: true, open: false } : c));
      setFirst(null);
      lockRef.current = false;
      setCards(matched);
      if (matched.every((c) => c.matched)) {
        setFinished(seconds + 1 <= limit ? "perfect" : "success");
        onDone(seconds + 1 <= limit ? "perfect" : "success", nmoves);
      }
    } else {
      setTimeout(() => {
        setCards((cs) => cs.map((c) => (c.id === id || c.id === first ? { ...c, open: false } : c)));
        setFirst(null);
        lockRef.current = false;
      }, 700);
    }
  };

  return (
    <>
      <div className="mt-4 flex items-center justify-center gap-4 text-xs text-slate-400">
        <span>配对 {pairs} 对 · 步数 {moves}</span>
        <span>剩余 {Math.max(0, limit - seconds)}s</span>
      </div>
      {finished ? (
        <div className="mt-4 rounded-lg border border-emerald-600/50 bg-emerald-600/10 p-3 text-sm">
          <div className="font-bold text-emerald-300">{finished === "perfect" ? "完美配对！" : "完成"}</div>
          <div className="text-xs text-slate-400">步数 {moves} · 成绩已回传</div>
        </div>
      ) : (
        <div className="mt-4 grid grid-cols-4 gap-2">
          {cards.map((c) => (
            <button
              key={c.id}
              onClick={() => flip(c.id)}
              className={`flex h-16 items-center justify-center rounded-lg border text-2xl ${
                c.matched
                  ? "border-emerald-600/50 bg-emerald-900/30"
                  : c.open
                    ? "border-amber-500 bg-amber-500/10"
                    : "border-slate-700 bg-slate-800"
              }`}
            >
              {c.open || c.matched ? c.v : "?"}
            </button>
          ))}
        </div>
      )}
    </>
  );
}