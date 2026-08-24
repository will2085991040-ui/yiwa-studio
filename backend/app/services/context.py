"""Thin Context Compiler（Step 12）：把 upstream 编译为结构化的对白运行时上下文。

这是「全量数据 != 全量进 Context」的最小落地：只提取 StoryGraph 骨架、当前 (node, choice)
焦点、相关 Scene、相关角色声线、相关关系边，并诚实标记缺失项（如 scene 尚未生成）。

职责边界（硬约束）：
- 纯函数：不查询 DB、不调用 LLM、不写 Artifact、不修改 State。
- DB 查询一律留在 dialogue_service；本模块只做 `upstream -> RuntimeContext` 的确定性变换。
- 未来升级为完整 L3 Context Compiler 时只替换本模块内部实现，调用方签名不变。
"""
import json
from typing import Any

from app.services.upstream import artifacts_of_kind, first_of_kind


def compile_dialogue_context(
    upstream: dict | None,
    *,
    node_id: str,
    choice_id: str | None,
    instruction: str | None,
) -> dict[str, Any]:
    """编译单个 (node_id, choice_id) 的对白上下文。

    返回 dict：skeleton / focus / scene / characters / relationships / protected / missing。
    其中 missing 是所有已检测到的缺失上下文引用（如 ["scene:scene_01"]），供 Trace 记录。
    """
    missing: list[str] = []
    story = first_of_kind(upstream, "story_graph") or {}
    node = _locate_node(story, node_id)
    choice = _locate_choice(node, choice_id) if node is not None else None
    scene_content = first_of_kind(upstream, f"scene:{node_id}")
    cards = artifacts_of_kind(upstream, "character_card")
    involved = _involved_character_ids(scene_content, cards)

    return {
        "skeleton": _build_skeleton(story),
        "focus": _build_focus(node, choice, node_id, choice_id, instruction),
        "scene": _build_scene(scene_content, node_id, missing),
        "characters": _build_characters(cards, involved),
        "relationships": _build_relationships(upstream, involved),
        "protected": _build_protected(node),
        "missing": missing,
    }


def _locate_node(story: dict, node_id: str) -> dict | None:
    return next((n for n in story.get("nodes", []) if n.get("node_id") == node_id), None)


def _locate_choice(node: dict | None, choice_id: str | None) -> dict | None:
    if node is None or choice_id is None:
        return None
    return next((c for c in node.get("choices", []) if c.get("choice_id") == choice_id), None)


def _involved_character_ids(scene_content: dict | None, cards: list[dict]) -> set[str]:
    """相关角色集合：有场景按在场角色，无场景退化为全部已登记角色（诚实降级）。"""
    if scene_content and scene_content.get("characters_present"):
        return set(scene_content["characters_present"])
    return {c.get("character_id") for c in cards if c.get("character_id")}


def _build_skeleton(story: dict) -> str:
    """全图骨架：每个节点一行（id[kind] title + choice 文案→目标），不注入 sceneDesc/dialogue 正文。"""
    lines: list[str] = []
    for n in story.get("nodes", []):
        targets = ", ".join(
            f"{c.get('text', '')}→{c.get('next_node')}" for c in n.get("choices", []) if c.get("next_node")
        )
        line = f"- {n.get('node_id')}[{n.get('kind')}] {n.get('title')}"
        if targets:
            line += f"（{targets}）"
        lines.append(line)
    var_names = [v.get("name") for v in story.get("variables", []) if v.get("name")]
    header = "变量：" + ", ".join(var_names) if var_names else "变量：（无）"
    return "节点骨架：\n" + ("\n".join(lines) if lines else "（无节点）") + "\n" + header


def _build_focus(
    node: dict | None,
    choice: dict | None,
    node_id: str,
    choice_id: str | None,
    instruction: str | None,
) -> str:
    parts: list[str] = []
    if node is not None:
        parts.append(f"当前节点：{node_id}（kind={node.get('kind')}，title={node.get('title')}）")
    else:
        parts.append(f"当前节点：{node_id}（未找到）")
    if choice is not None:
        parts.append(f"当前选择：{choice_id}")
        parts.append(f"选择文案：{choice.get('text', '')}")
        if choice.get("condition"):
            parts.append(f"选择条件：{choice.get('condition')}")
        effects = choice.get("effects", [])
        if effects:
            parts.append("选择效果：" + _fmt_effects(effects))
        if choice.get("next_node"):
            parts.append(f"下一节点：{choice.get('next_node')}")
    elif choice_id is not None:
        parts.append(f"当前选择：{choice_id}（未找到）")
    else:
        parts.append("当前选择：默认/开场对白（choice_id = null）")
    if instruction:
        parts.append(f"用户指令：{instruction}")
    return "\n".join(parts)


def _build_scene(scene_content: dict | None, node_id: str, missing: list[str]) -> str:
    if scene_content is None:
        missing.append(f"scene:{node_id}")
        return "（缺失：该节点的 Scene 尚未生成，禁止伪造场景）"
    fields = [
        ("scene_id", scene_content.get("scene_id")),
        ("title", scene_content.get("title")),
        ("summary", scene_content.get("summary")),
        ("location", scene_content.get("location")),
        ("time", scene_content.get("time")),
        ("atmosphere", scene_content.get("atmosphere")),
        ("characters_present", scene_content.get("characters_present")),
        ("events", scene_content.get("events")),
        ("visual_direction", scene_content.get("visual_direction")),
        ("camera_direction", scene_content.get("camera_direction")),
        ("stage_direction", scene_content.get("stage_direction")),
        ("emotional_beats", scene_content.get("emotional_beats")),
        ("state_changes", scene_content.get("state_changes")),
        ("continuity_notes", scene_content.get("continuity_notes")),
    ]
    lines = [_render_label(label, value) for label, value in fields]
    lines = [line for line in lines if line]
    return "\n".join(lines) if lines else "（场景字段为空）"


def _build_characters(cards: list[dict], involved: set[str]) -> str:
    if not cards:
        return "（无角色卡）"
    selected = [c for c in cards if c.get("character_id") in involved] if involved else cards
    if not selected:
        selected = cards
    lines: list[str] = []
    for c in selected:
        ss = c.get("speech_style") or {}
        personality = "/".join(c.get("personality") or [])
        voice = (
            f"声线：tone={ss.get('tone', '')}，formality={ss.get('formality', '')}，"
            f"口头禅={','.join(ss.get('catchphrases') or [])}，口癖={','.join(ss.get('quirks') or [])}"
        )
        line = f"- {c.get('character_id')} {c.get('name', '')}（{c.get('role', '')}）"
        if personality:
            line += f" 性格:{personality}"
        if c.get("motivation"):
            line += f" 动机:{c.get('motivation')}"
        line += f" {voice}"
        lines.append(line)
    return "\n".join(lines)


def _build_relationships(upstream: dict | None, involved: set[str]) -> str:
    graph = first_of_kind(upstream, "relationship_graph")
    edges = (graph or {}).get("edges", [])
    if not edges:
        return "（无关系边）"
    if involved:
        edges = [
            e for e in edges
            if e.get("source_character") in involved or e.get("target_character") in involved
        ]
    lines: list[str] = []
    for e in edges:
        line = f"- {e.get('source_character')}—{e.get('relationship_type')}→{e.get('target_character')}"
        rules = "；".join(e.get("rules") or [])
        if rules:
            line += f" 规则:{{{rules}}}"
        triggers = "；".join(e.get("triggers") or [])
        if triggers:
            line += f" 触发:{{{triggers}}}"
        lines.append(line)
    return "\n".join(lines) if lines else "（无相关关系边）"


def _build_protected(node: dict | None) -> str:
    if node is not None and node.get("locked"):
        return f"LOCKED CONTENT MUST NOT BE MODIFIED：节点 {node.get('node_id')} 已被用户锁定。"
    return ""


def _fmt_effects(effects: list[dict]) -> str:
    return "；".join(f"{e.get('variable')} {e.get('op')} {e.get('value')}" for e in effects if e.get("variable"))


def _render_label(label: str, value: Any) -> str:
    if value is None or value == "" or value == []:
        return ""
    if isinstance(value, list):
        joined = "；".join(
            (v if isinstance(v, str) else _json(v)) for v in value
        )
        return f"{label}：{joined}"
    if isinstance(value, dict):
        return f"{label}：{_json(value)}"
    return f"{label}：{value}"


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)