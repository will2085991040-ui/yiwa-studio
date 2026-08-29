"""Unified Context Compiler（Step 15）：全局唯一的上下文装配入口。

分层（L0–L7）：
  L0 system            硬规则（Agent 行为契约）
  L1 project           项目目标 / 模板 / 世界观 truth
  L2 story structure   剧情结构骨架（StoryGraph）
  L3 current focus     当前节点/选择 + 场景 + 相关角色/关系 + protected
  L4 relevant memory   从 MemoryStore 检索的可重建索引候选
  L5 runtime state     当前 Runtime State（可选传入）
  L6 user instruction  用户当前指令
  L7 optional material 可选素材（Step19 素材层，当前为空占位）

硬约束：
- Agent 不允许自行拼装大量上下文，一律走 compile()。
- 超出 token 预算：优先保留 system/project/structure/focus/instruction，
  压缩 runtime/memory/material，绝不伪造不存在的数据。
- missing 诚实标记「引用了但不存在」的上下文引用，绝不编造。
"""
import json
import math

from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import Artifact, Project
from app.services.context import compile_dialogue_context
from app.services.memory import memory_store
from app.services.skills import use_skill
from app.services.upstream import first_of_kind

L0, L1, L2, L3, L4, L5, L6, L7 = "L0", "L1", "L2", "L3", "L4", "L5", "L6", "L7"
LAYERS = [L0, L1, L2, L3, L4, L5, L6, L7]
_BUDGET_KEEP_ORDER = [L0, L1, L2, L3, L6, L5, L4, L7]

SYSTEM_RULES = (
    "你是 YIWA 创作 Agent。硬约束：\n"
    "1) locked 内容禁止修改；2) LLM 只能产出声明式数据（StoryEffect/StoryCondition），"
    "不得直接修改 Runtime State；3) 缺失的上下文必须标记 missing，禁止伪造；"
    "4) 生成的 Artifact 只声明不执行。"
)


def _estimate_tokens(text: str) -> int:
    return max(1, math.ceil(len(text) / 4))


class ContextCompiler:
    def __init__(self, session: Session):
        self.session = session

    def _upstream(self, project_id: str) -> dict:
        rows = (
            self.session.query(Artifact)
            .filter(Artifact.project_id == project_id, Artifact.is_latest.is_(True))
            .all()
        )
        return {a.id: {"kind": a.kind, "content": a.content or {}} for a in rows}

    def compile(
        self,
        project_id: str,
        *,
        focus_node_id: str | None = None,
        focus_choice_id: str | None = None,
        instruction: str = "",
        token_budget: int | None = None,
        runtime_state: dict | None = None,
        skills: list | None = None,
    ) -> dict:
        project = self.session.get(Project, project_id)
        if project is None:
            raise AppError("项目不存在", code="not_found", status=404)
        upstream = self._upstream(project_id)
        story = first_of_kind(upstream, "story_graph") or {}
        node_id = focus_node_id or story.get("entry_node_id")
        missing: list[str] = []

        if story:
            core = compile_dialogue_context(
                upstream, node_id=node_id or "", choice_id=focus_choice_id, instruction="",
            )
            missing.extend(core.get("missing", []))
            l2 = core["skeleton"]
            focus_parts = [core["focus"]]
            if core["scene"].strip():
                focus_parts.append("场景：\n" + core["scene"])
            if core["characters"].strip():
                focus_parts.append("相关角色：\n" + core["characters"])
            if core["relationships"].strip():
                focus_parts.append("相关关系：\n" + core["relationships"])
            if core["protected"].strip():
                focus_parts.append("PROTECTED（禁止修改）：\n" + core["protected"])
            l3 = "\n".join(focus_parts)
        else:
            l2 = "（无剧情图：StoryGraph 尚未生成）"
            l3 = "（无当前焦点）"
            missing.append("story_graph")

        query = " ".join(p for p in [str(node_id or ""), instruction] if p)
        l4 = self._memory_layer(project_id, query)

        l0 = SYSTEM_RULES
        if skills:
            l0 = SYSTEM_RULES + "\n\n" + use_skill(skills)

        layers = {
            L0: l0,
            L1: self._project_layer(project, upstream),
            L2: l2,
            L3: l3,
            L4: l4,
            L5: self._runtime_layer(runtime_state),
            L6: instruction or "（无用户指令）",
            L7: "（尚无素材）",
        }
        estimate = sum(_estimate_tokens(layers[k]) for k in LAYERS)
        if token_budget is not None:
            layers, trimmed = self._apply_budget(layers, token_budget)
        else:
            trimmed = []
        return {
            "project_id": project_id,
            "layers": layers,
            "missing": list(dict.fromkeys(missing)),
            "token_estimate": estimate,
            "trimmed": trimmed,
        }

    def _project_layer(self, project: Project, upstream: dict) -> str:
        world = first_of_kind(upstream, "world_bible") or {}
        parts = [f"项目目标：{project.goal}", f"模板：{project.template}"]
        if world:
            parts.append("世界观：" + json.dumps(world, ensure_ascii=False))
        return "\n".join(parts)

    def _memory_layer(self, project_id: str, query: str) -> str:
        results = memory_store.search(self.session, project_id, query, top_k=5)
        if not results:
            return "（无相关记忆）"
        return "\n".join(f"- [{m['kind']}] {m['content']}" for m in results)

    def _runtime_layer(self, runtime_state: dict | None) -> str:
        if runtime_state is None:
            return "（无运行时状态）"
        return "运行时状态：" + json.dumps(runtime_state, ensure_ascii=False)

    def _apply_budget(self, layers: dict, budget: int) -> tuple[dict, list[str]]:
        used = 0
        trimmed: list[str] = []
        out: dict = {}
        for key in _BUDGET_KEEP_ORDER:
            text = layers.get(key, "")
            cost = _estimate_tokens(text)
            if used + cost <= budget:
                out[key] = text
                used += cost
                continue
            remaining = budget - used
            if remaining <= 0:
                out[key] = "（已省略：超出 token 预算）"
            else:
                keep_chars = remaining * 4
                out[key] = text[:keep_chars] + "\n…（已截断）"
                used = budget
            trimmed.append(key)
        for key in LAYERS:
            out.setdefault(key, "")
        return out, trimmed


def compile_context(session: Session, project_id: str, **kwargs) -> dict:
    """便捷入口。"""
    return ContextCompiler(session).compile(project_id, **kwargs)