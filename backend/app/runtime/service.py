"""Runtime 接口与实现：AI 导演（Director）互动运行器。

每个构建状态都有真实处理逻辑，不再返回"未接入"的死路：
- draft   ：诚实反映构建骨架阶段（保留原 Phase 0 文案），并说明后续互动会随构建完成接入。
- building：诚实汇报构建进度（已完成/进行中/待处理步骤 + 已产出的 Artifact 摘要）。
- failed  ：如实汇报失败并给出下一步。
- ok      ：已构建完成 → 调用 LLM 让 AI 导演基于「真实成品摘要」回应用户消息；
            若 LLM 不可用/失败，回退为诚实的成品汇报（绝不编造，绝不 500）。

所有回复都记录 Trace（AgentRun + AgentStep），与其它 Agent 一致。
"""
import time
from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.agents.generation import generate_structured
from app.core.errors import AppError, NotFoundError
from app.llm.provider import get_provider
from app.llm.types import TokenBudget
from app.models import AgentSpec, AgentVersion, Artifact
from app.services.prompt_seed import ensure_director_chat_prompt
from app.services.prompts import get_definition, get_latest, prompt_tag, render
from app.trace.manager import trace_manager

# AI 导演 chat 的 LLM 调用预算
_DIRECTOR_CHAT_BUDGET = TokenBudget(max_input_tokens=8192, max_output_tokens=4096, max_total_tokens=12288)

_CHAT_SCHEMA: dict = {
    "type": "object",
    "properties": {"reply": {"type": "string"}},
    "required": ["reply"],
}


class _ChatReply(BaseModel):
    reply: str


class BaseRuntime(ABC):
    @abstractmethod
    async def handle(self, session: Session, agent_spec_id: str, user_input: str) -> dict[str, Any]:
        raise NotImplementedError


class DirectorRuntime(BaseRuntime):
    """AI 导演运行器：按构建状态真实回应；构建完成后用 LLM 互动。"""

    async def handle(self, session: Session, agent_spec_id: str, user_input: str) -> dict[str, Any]:
        spec = session.get(AgentSpec, agent_spec_id)
        if spec is None:
            raise NotFoundError("Agent 不存在")
        version = (
            session.query(AgentVersion)
            .filter(AgentVersion.agent_spec_id == spec.id)
            .order_by(AgentVersion.version_no.desc())
            .first()
        )
        started = time.perf_counter()
        run = trace_manager.start_run(session, kind="chat", agent_version_id=version.id if version else None)
        status = spec.status or "draft"
        artifacts = _latest_artifacts(session, spec.project_id)

        reply = ""
        used_llm = False
        if status == "ok" and artifacts:
            try:
                reply, used_llm = await self._director_chat(session, run, spec, user_input, artifacts)
            except AppError:
                reply = _status_reply(spec, status, user_input, artifacts)
            except Exception:
                reply = _status_reply(spec, status, user_input, artifacts)
        else:
            reply = _status_reply(spec, status, user_input, artifacts)

        trace_manager.add_step(
            session, run, agent="director", step_key="handle_message",
            input_data={"message": user_input, "status": status},
            output_data={"reply": reply, "used_llm": used_llm},
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
        finish_status = "ok"
        trace_manager.finish_run(run, status=finish_status)
        session.commit()
        return {"reply": reply, "status": status, "template": spec.project.template, "used_llm": used_llm}

    async def _director_chat(
        self, session: Session, run, spec: AgentSpec, user_input: str, artifacts: list[dict]
    ) -> tuple[str, bool]:
        ensure_director_chat_prompt(session)
        version = _load_director_chat_prompt(session)
        tag = prompt_tag("director_chat_generation", version.version_no)
        temperature = (version.model_preferences or {}).get("temperature")
        summary = _artifacts_summary(artifacts)
        system = render(version, {
            "goal": spec.project.goal,
            "status": spec.status,
            "template": spec.project.template,
            "project_summary": summary,
            "user_message": user_input,
        })
        provider = get_provider()
        content, _response, _attempts = await generate_structured(
            session, run, agent="director", provider=provider, budget=_DIRECTOR_CHAT_BUDGET,
            prompt_version=tag, temperature=temperature, system=system, user=user_input,
            json_schema=_CHAT_SCHEMA, validate=_ChatReply.model_validate, max_attempts=2,
        )
        return content.reply.strip(), True


def _latest_artifacts(session: Session, project_id: str) -> list[dict]:
    rows = (
        session.query(Artifact)
        .filter(Artifact.project_id == project_id, Artifact.is_latest.is_(True))
        .order_by(Artifact.created_at)
        .all()
    )
    return [
        {"kind": a.kind, "content": a.content or {}, "version": a.version, "id": a.id}
        for a in rows
    ]


def _load_director_chat_prompt(session):
    definition = get_definition(session, "director_chat_generation")
    if definition is None:
        raise AppError("director_chat_generation 未初始化", code="prompt_missing", status=500)
    version = get_latest(session, definition, status="active") or get_latest(session, definition)
    if version is None:
        raise AppError("director_chat_generation 无可用版本", code="prompt_missing", status=500)
    return version


def _status_reply(spec: AgentSpec, status: str, user_input: str, artifacts: list[dict]) -> str:
    goal = spec.project.goal
    if status == "draft":
        return (
            f"已收到你的消息：「{user_input}」\n"
            f"当前 Agent 处于构建骨架阶段（{status}），互动执行能力尚未接入。\n"
            f"已完成：目标理解（模板={spec.project.template}）；计划步骤：{len(spec.plan)} 个。"
        )
    if status == "building":
        done, running_count = _plan_counts(spec.plan)
        produced = _artifacts_summary(artifacts) or "（尚未产出成品）"
        return (
            f"正在构建「{goal}」…\n"
            f"构建进度：已完成 {done} 步，进行中 {running_count} 步，共 {len(spec.plan)} 步。\n"
            f"已产出：{produced}\n"
            f"请稍候，构建完成后我会就「{user_input}」继续为你执导。"
        )
    if status == "failed":
        return (
            f"「{goal}」的构建已返回失败。\n"
            f"已产出（若有）：{_artifacts_summary(artifacts) or '暂无'}\n"
            f"建议：回到项目工作流查看失败步骤并重新运行；我会在构建恢复后继续执导。"
        )
    # ok 或未知状态：LLM 不可用时的诚实成品汇报
    produced = _artifacts_summary(artifacts) or "（暂无成品）"
    return (
        f"AI 导演已就绪，当前项目「{goal}」已产出：\n{produced}\n"
        f"关于「{user_input}」，你可以在对应工作台继续修改/增删，或让我先聚焦某个环节细化。"
    )


def _plan_counts(plan: list) -> tuple[int, int]:
    done = 0
    running = 0
    for s in plan or []:
        st = (s or {}).get("status", "")
        if st in ("done", "ok", "completed"):
            done += 1
        elif st in ("running", "building", "processing"):
            running += 1
    return done, running


def _essence(kind: str, content: dict) -> str:
    text = ""
    if kind == "world_bible":
        text = (
            content.get("title") or "无标题"
        ) + (
            f"（{content.get('location') or ''}）" if content.get("location") else ""
        )
    elif kind.startswith("character_card"):
        name = content.get("name") or "未命名"
        role = content.get("role")
        text = f"{name}（{role}）" if role else name
    elif kind == "relationship_graph":
        text = f"人物关系 {len(content.get('edges', []))} 条"
    elif kind == "plot":
        text = content.get("summary") or content.get("synopsis") or "剧情大纲"
    elif kind == "story_graph":
        text = f"剧情图 {len(content.get('nodes', []))} 个节点 / {len(content.get('edges', []))} 条边"
    elif kind.startswith("scene:"):
        text = content.get("synopsis") or content.get("summary") or "场景正文"
    elif kind.startswith("dialogue:"):
        lines = content.get("lines", [])
        text = f"对白 {len(lines)} 句"
    elif kind.startswith("storyboard:"):
        text = f"分镜 {len(content.get('shots', []))} 镜"
    else:
        text = str(content)[:60]
    return (text or kind).strip()


def _artifacts_summary(artifacts: list[dict]) -> str:
    if not artifacts:
        return ""
    lines = []
    for a in artifacts:
        est = _essence(a["kind"], a["content"])
        readable = {
            "world_bible": "世界观",
            "character": "角色",
            "relationship_graph": "关系图",
            "story_graph": "剧情图",
            "plot": "剧情大纲",
        }.get(a["kind"], a["kind"])
        lines.append(f"- {readable}（v{a['version']}）：{est}")
    return "\n".join(lines)


runtime = DirectorRuntime()