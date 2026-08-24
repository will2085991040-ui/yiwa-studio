"""StoryboardAgent：针对 StoryGraph 指定节点生成 AI 分镜（LLM 拆镜）。

这是「用户主动调用」的创作工具能力（pipeline=False），把剧情节点 + 世界/角色/关系/场景上下文
喂给 LLM，产出 Structure Storyboard（node_id/synopsis/shots）。

若 LLM 生成失败，调用方（storyboard API）会回退到确定性 mock `auto_breakdown`，
保证离线可用。
"""
import json

from app.agents.base import BaseAgent
from app.agents.generation import generate_structured
from app.core.errors import AppError
from app.llm.provider import get_script_provider
from app.llm.types import TokenBudget
from app.schemas.storyboard import Storyboard, storyboard_json_schema
from app.services.prompts import get_definition, get_latest, prompt_tag, render
from app.services.upstream import artifacts_of_kind, first_of_kind
from app.trace.manager import trace_manager

STORYBOARD_BUDGET = TokenBudget(max_input_tokens=12288, max_output_tokens=16384, max_total_tokens=28672)


class StoryboardAgent(BaseAgent):
    name = "storyboard"
    layer = "content"
    description = "分镜师：针对 StoryGraph 指定节点做 AI 拆镜，产出可编辑的分镜表与导演提示词"
    input_schema = {
        "type": "object",
        "properties": {"goal": {"type": "string"}, "node_id": {"type": "string"}},
        "required": ["goal", "node_id"],
    }
    output_schema = storyboard_json_schema()
    pipeline = False  # on-demand：由用户在分镜工作台按节点调用

    def __init__(self, max_attempts: int = 2):
        self.max_attempts = max_attempts

    async def run(self, input_data: dict) -> dict:
        session = input_data["session"]
        run = input_data["run"]
        task = input_data["task"]
        goal = input_data["goal"]
        node_id = input_data.get("node_id")
        upstream = input_data.get("upstream", {})
        provider = input_data.get("provider") or get_script_provider()
        budget = input_data.get("budget") or STORYBOARD_BUDGET
        revision = input_data.get("revision")

        if not node_id:
            raise AppError("缺少 node_id（分镜必须按 StoryGraph 节点生成）", code="node_id_required", status=400)

        version = _load_storyboard_prompt(session)
        tag = prompt_tag("storyboard_generation", version.version_no)
        temperature = (version.model_preferences or {}).get("temperature")

        node, ctx = _locate_node(upstream, node_id)
        system = render(version, {
            "goal": goal,
            "focus": _build_focus(node_id, node, ctx, revision),
            "characters": _build_characters_summary(upstream),
            "relationships": _build_relationships_summary(upstream),
            "scene": _build_scene_summary(upstream, node_id),
            "world": _build_world_summary(upstream),
        })

        trace_manager.add_step(
            session, run, agent="storyboard", step_key="storyboard.input",
            input_data={"task": task.id, "node_id": node_id, "goal": goal},
            output_data={"prompt_version": tag},
        )

        content, response, attempts = await generate_structured(
            session, run, agent="storyboard", provider=provider, budget=budget,
            prompt_version=tag, temperature=temperature, system=system, user=goal,
            json_schema=storyboard_json_schema(),
            validate=Storyboard.model_validate,
            max_attempts=self.max_attempts,
        )
        # 稳定引用：node_id 强制等于 StoryGraph.node_id（不依赖模型输出）
        content.node_id = node_id
        # 镜头补全：保证 shot_no 连续、默认 status=draft
        content.shots = [
            s.model_copy(update={"shot_no": i + 1, "status": "draft" if not s.status else s.status})
            for i, s in enumerate(content.shots)
        ]

        trace_manager.add_step(
            session, run, agent="storyboard", step_key="artifact",
            input_data={"task": task.id, "node_id": node_id},
            output_data={"kind": f"storyboard:{node_id}", "shot_count": len(content.shots)}, status="ok",
        )
        return {
            "ok": True, "agent": "storyboard", "node_id": node_id,
            "storyboard": content,  # 结构化结果，供 API 直接落库
            "prompt_version": tag, "provider": response.provider, "model": response.model,
            "usage": response.usage.model_dump(), "latency_ms": response.latency_ms, "attempts": attempts,
        }


def _load_storyboard_prompt(session):
    definition = get_definition(session, "storyboard_generation")
    if definition is None:
        raise AppError("storyboard_generation 未初始化", code="prompt_missing", status=500)
    version = get_latest(session, definition, status="active") or get_latest(session, definition)
    if version is None:
        raise AppError("storyboard_generation 无可用版本", code="prompt_missing", status=500)
    return version


def _locate_node(upstream: dict, node_id: str) -> tuple[dict, dict]:
    graph = first_of_kind(upstream, "story_graph")
    if not graph:
        raise AppError("上游缺少 StoryGraph，无法定位剧情节点", code="no_story_graph", status=400)
    node = next((n for n in graph.get("nodes", []) if n.get("node_id") == node_id), None)
    if node is None:
        raise AppError(f"StoryGraph 中不存在节点 {node_id}", code="node_not_found", status=404)

    edges = graph.get("edges", [])
    predecessors = [e["source"] for e in edges if e.get("target") == node_id]
    successors = [e["target"] for e in edges if e.get("source") == node_id]
    ctx = {
        "predecessors": predecessors,
        "successors": successors,
        "choices": node.get("choices", []),
        "variables": graph.get("variables", []),
        "kind": node.get("kind"),
    }
    return node, ctx


def _build_focus(node_id: str, node: dict, ctx: dict, revision: dict | None = None) -> str:
    parts = [f"节点 node_id={node_id}", f"节点类型={ctx['kind']}", f"标题={node.get('title', '')}"]
    if node.get("summary"):
        parts.append(f"剧情摘要={node['summary']}")
    if ctx["predecessors"]:
        parts.append(f"前置节点={','.join(ctx['predecessors'])}")
    if ctx["successors"]:
        parts.append(f"后续节点={','.join(ctx['successors'])}")
    if ctx["choices"]:
        parts.append(
            "此处选项=" + "；".join(f"{c['text']} -> {c.get('next_node') or '（无）'}" for c in ctx["choices"])
        )
    if ctx["variables"]:
        parts.append("状态变量=" + ",".join(f"{v['name']}={v['initial']}" for v in ctx["variables"]))
    if revision:
        parts.append(f"修改要求：{revision.get('instruction') or ''}")
        previous = revision.get("previous")
        if previous:
            parts.append(f"当前分镜基线（JSON）：{json.dumps(previous, ensure_ascii=False)[:1600]}")
    return "；".join(parts)


def _build_characters_summary(upstream: dict) -> str:
    cards = artifacts_of_kind(upstream, "character_card")
    if not cards:
        return "（无角色卡）"
    lines = []
    for c in cards:
        name = c.get("name", "")
        if c.get("appearance"):
            lines.append(f"{name}({c.get('role', '')})：外貌={c['appearance'][:120]}")
        else:
            lines.append(f"{name}({c.get('role', '')})")
    return "；".join(lines)


def _build_relationships_summary(upstream: dict) -> str:
    graph = first_of_kind(upstream, "relationship_graph")
    if not graph or not graph.get("edges"):
        return "（无人物关系边）"
    return "；".join(
        f"{e.get('source_character')}—{e.get('relationship_type')}→{e.get('target_character')}"
        for e in graph["edges"]
    )


def _build_scene_summary(upstream: dict, node_id: str) -> str:
    scene = first_of_kind(upstream, f"scene:{node_id}")
    if not scene:
        return "（暂无场景正文，可依据剧情摘要拆镜）"
    if scene.get("synopsis"):
        return scene["synopsis"]
    if scene.get("summary"):
        return scene["summary"]
    if scene.get("content"):
        return str(scene["content"])[:300]
    return "（已提供场景正文，请作为拆镜参考）"


def _build_world_summary(upstream: dict) -> str:
    world = first_of_kind(upstream, "world_bible")
    if not world:
        return "（无世界观）"
    parts = []
    if world.get("title"):
        parts.append(f"世界观《{world['title']}》")
    if world.get("setting"):
        parts.append(world["setting"][:200])
    if world.get("era"):
        parts.append(f"时代：{world['era']}")
    if world.get("location"):
        parts.append(f"地点：{world['location']}")
    return "；".join(parts)