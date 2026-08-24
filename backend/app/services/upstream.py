"""upstream 数据流契约（Step 9）：任务依赖输出按 task_id 键化。

上游结构统一为：
    upstream = {task_id: {"kind": <artifact kind>, "content": <结构化内容 dict>}}

按 task_id（而非 agent_type）键化，才能支撑未来同一 Agent 类型的多个任务
（如 character_001 / character_002 / character_003、多个 scene/dialogue 任务）。
"""
from typing import Any


def artifacts_of_kind(upstream: dict | None, kind: str) -> list[dict]:
    """从 upstream 中取出指定 kind 的所有 content（供下游 Agent 读取）。

    多角色/多节点资源使用 `kind:entity_id` 子 kind（如 character_card:char-01、scene:node2），
    因此同时精确匹配 kind 与 `kind:` 前缀，兼容旧单卡 `character_card` 与新 per-entity kind。
    """
    result: list[dict] = []
    for value in (upstream or {}).values():
        if not (isinstance(value, dict) and "content" in value):
            continue
        vkind = value.get("kind")
        if vkind == kind or vkind.startswith(kind + ":"):
            content = value["content"]
            if isinstance(content, dict):
                result.append(content)
    return result


def first_of_kind(upstream: dict | None, kind: str) -> dict | None:
    items = artifacts_of_kind(upstream, kind)
    return items[0] if items else None


def upstream_entry(kind: str, content: Any) -> dict:
    """构造一个标准 upstream 条目。"""
    return {"kind": kind, "content": content}