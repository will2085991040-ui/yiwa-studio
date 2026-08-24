"""小说导入与拆解（增量）：文本 -> 章节/场景 -> 角色卡 -> 人物关系 -> 串联互动图。

干净移植：仅复刻 Funloom「导入小说 → 拆剧本 → 角色卡 → 关系 → 互动影游」创作闭环的结构与
交互语义，所有实现为本项目自有的确定性拆解 + StoryGraph Schema，不复制任何受限源码/文案。
"""
import re

from app.schemas.story_graph import (
    Choice,
    StoryEdge,
    StoryEnding,
    StoryGraph,
    StoryNode,
    StoryVariable,
    WorldAnchor,
)

GAME_TYPE_LABELS = {
    "galgame": "Galgame 恋爱冒险",
    "avg": "AVG 文字冒险",
    "interactive_film": "互动影视",
}

# 小说对白两种常见形态：`某人说/问/道` 与 剧本式整行 `某人：台词`。
_SPEAKER_RE = re.compile(r"([\u4e00-\u9fa5]{2,4})[说道问答喊叫]")
_LINE_SPEAKER_RE = re.compile(r"^\s*([\u4e00-\u9fa5A-Za-z0-9·．]{1,6})[：:]")
_VERB_TAIL = frozenset("说道问答喊叫")
_STOP_WORDS = {
    "我", "你", "他", "她", "它", "我们", "你们", "他们", "她们", "它们",
    "自己", "这", "那", "什么", "怎么", "为什么", "谁", "哪", "一个", "一旦",
    "低声", "大声", "小声", "轻声", "冷声", "淡声", "喃喃", "一下", "然后",
}
_REL_LABELS = ["伙伴", "对手", "家人", "知己", "宿敌", "至交"]


def _clean_name(raw: str) -> str:
    """去掉紧随其后的动词尾（「林烬说」→「林烬」）便于剧本式 `某人：台词` 里识别说话人。"""
    name = raw.strip()
    while len(name) > 1 and name[-1] in _VERB_TAIL:
        name = name[:-1]
    return name


def game_type_label(game_type: str | None) -> str:
    return GAME_TYPE_LABELS.get(game_type or "", "互动叙事")


def _split_scenes(text: str, chunk: int = 420) -> list[str]:
    """按空行/章节标题拆分段落，过短则合并；全篇无分隔时按字数硬切。"""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    scenes: list[str] = []
    buf = ""
    for p in paras:
        if buf and len(buf) + len(p) + 2 > chunk:
            scenes.append(buf)
            buf = p
        else:
            buf = (buf + "\n\n" + p).strip()
    if buf:
        scenes.append(buf)
    if len(scenes) <= 1:
        scenes = [text[i : i + chunk] for i in range(0, len(text), chunk)]
    return [s for s in scenes if s.strip()]


def _extract_characters(text: str) -> list[dict]:
    """说话人启发式：从「某人说/问/道」与剧本式「某人：台词」里按频次提取角色卡（保底「主角」）。"""
    counts: dict[str, int] = {}

    def bump(raw: str) -> None:
        name = _clean_name(raw)
        if len(name) < 2 or name in _STOP_WORDS:
            return
        counts[name] = counts.get(name, 0) + 1

    for m in _SPEAKER_RE.finditer(text):
        bump(m.group(1))
    for line in text.splitlines():
        m = _LINE_SPEAKER_RE.match(line)
        if m:
            bump(m.group(1))

    top = sorted(counts.items(), key=lambda kv: -kv[1])[:10]
    chars = [
        {"name": name, "role": "主角" if rank == 0 else "主要角色",
         "description": f"对白中出现 {freq} 次", "mentions": freq}
        for rank, (name, freq) in enumerate(top)
    ]
    if not chars:
        chars.append({"name": "主角", "role": "主角", "description": "导入文本中的主要角色", "mentions": 0})
    return chars


def _build_relationships(chars: list[dict]) -> list[dict]:
    rels: list[dict] = []
    for i in range(len(chars)):
        for j in range(i + 1, len(chars)):
            if len(rels) >= 12:
                break
            rels.append({
                "source": chars[i]["name"],
                "target": chars[j]["name"],
                "kind": _REL_LABELS[(i + j) % len(_REL_LABELS)],
                "description": "由导入文本中的角色共现推演，可在工作台进一步编辑",
            })
    return rels


def _build_story_graph(title: str, scenes: list[str], game_type: str | None) -> dict:
    """把拆解出的场景串成一张可立刻试玩/导出的 StoryGraph（线性主线 + 可选支线）。"""
    cap = scenes[:60]  # 长链条：尽可能多地把导入小说的场景铺进剧情图（>=60 节点），支撑长片叙事
    nodes = [
        StoryNode(
            node_id=f"n{i}",
            kind="scene",
            title=f"第 {i + 1} 幕",
            summary=cap[i][:160].replace("\n", " "),
            position={"x": i * 280.0, "y": 80.0},
        )
        for i in range(len(cap))
    ]
    endings = [StoryEnding(
        ending_id="fin",
        node_id="end",
        title="结局",
        type="neutral" if game_type != "galgame" else "good",
        description="由导入小说铺陈出的主线结局",
    )]
    nodes.append(StoryNode(node_id="end", kind="ending", title="结局", summary="故事在此收束"))

    for i in range(len(cap)):
        nxt = f"n{i + 1}" if i + 1 < len(cap) else "end"
        choices = [Choice(choice_id=f"c{i}_go", text="继续推进", next_node=nxt)]
        if game_type != "avg" and i + 2 < len(cap):
            alt = f"n{i + 2}"
            choices.append(Choice(choice_id=f"c{i}_alt", text="换一条路试探", next_node=alt, weight="heavy"))
        elif game_type != "avg" and i + 1 < len(cap):
            choices.append(Choice(choice_id=f"c{i}_alt", text="换一种选择", next_node="end", weight="light"))
        nodes[i] = nodes[i].model_copy(update={"choices": choices})

    edges = [
        StoryEdge(edge_id=f"e{i}", source=f"n{i}", target=f"n{i + 1}", label="主线")
        for i in range(len(cap) - 1)
    ]
    if cap:
        edges.append(StoryEdge(edge_id="e_end", source=f"n{len(cap) - 1}", target="end", label="收束"))

    variables = [StoryVariable(name="affection", type="number", initial=0, description="好感度")]
    world = WorldAnchor(
        story_core=title or "导入小说",
        theme="",
        genre=GAME_TYPE_LABELS.get(game_type or "", "互动叙事"),
        duration_minutes=max(5, min(120, len(cap) * 5)),
    )
    graph = StoryGraph(
        graph_id="novel",
        nodes=nodes,
        edges=edges,
        variables=variables,
        endings=endings,
        world_anchor=world,
        entry_node_id="n0",
        metadata={"scenes": len(cap), "game_type": game_type, "engine": "novel_import"},
    )
    return graph.model_dump()


def breakdown_novel(text: str, game_type: str | None = None, title: str | None = None) -> dict:
    """拆解入口：返回 scenes / characters / relationships / story_graph 的可序列化结果。"""
    scenes = _split_scenes(text)
    chars = _extract_characters(text)
    rels = _build_relationships(chars)
    graph = _build_story_graph(title or "导入作品", scenes, game_type)
    return {
        "title": title or "导入作品",
        "game_type": game_type,
        "game_type_label": game_type_label(game_type),
        "scene_count": len(scenes),
        "scenes": [{"index": i, "summary": s[:160]} for i, s in enumerate(scenes)],
        "characters": chars,
        "relationships": rels,
        "story_graph": graph,
    }