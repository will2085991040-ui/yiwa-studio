# -*- coding: utf-8 -*-
"""一键生成完整互动剧本（script_writer）。

复用既有 LLM Provider + Trace + Artifact 版本体系：
输入一个创意（goal），用「剧本专用模型」（llm_script_model，缺省回退 llm_model）
一次调用产出结构化「互动剧本」（分场剧本 + 对白），落库 Artifact kind="script"，返回前端。
"""
import uuid

from app.core.errors import NotFoundError
from app.llm.provider import get_script_provider
from app.llm.types import LLMProviderError, LLMRequest, TokenBudget
from app.models import Project
from app.schemas.script import Script, script_json_schema
from app.services.artifacts import persist_versioned_artifact
from app.trace.manager import trace_manager

SCRIPT_BUDGET = TokenBudget(max_input_tokens=16384, max_output_tokens=32768, max_total_tokens=49152)
PROMPT_VERSION = "script_full_v1"


def _build_system(*, genre: str | None, title_arg: str | None, scene_count: int | None) -> str:
    lines = [
        "你是一位专业影视/互动剧编剧。根据用户的一句话创意，产出一部结构完整、可直接拍摄配音的互动剧本文案。",
        "要求：",
        "- 主题连贯、人物动机清晰；对白口语化、有张力且符合人物性格。",
        "- 结构 = 若干 act(幕)，每幕 = 若干 scene(场)，每场 = 若干 beat(镜头/对白单元)。",
        "- 每场给出 scene_id、title、location、time_of_day、summary 和多个 beats；",
        "  每条 beat 给出 speaker(空=旁白/动作描述)、line(台词)、direction(表演提示)、emotion(情绪)。",
        "- characters 至少包含 6 个主要角色；全篇总场数(所有 act 的 scenes 总和)>= 12。",
        "- logline 为一句卖点(<=80 字)；synopsis 为整体剧情摘要(<=400 字)。",
        "- 输出必须严格符合给定 JSON Schema，且只输出该 JSON 对象；不要输出任何其它文字。",
    ]
    if genre:
        lines.append(f"题材要求：{genre}")
    if title_arg:
        lines.append(f"作品标题：{title_arg}")
    if scene_count:
        lines.append(f"剧本规模：期望总场数约 {int(scene_count)} 场（据此分配各幕场数）。")
    return "\n".join(lines)


async def generate_script(
    session,
    *,
    project_id: str,
    goal: str,
    genre: str | None = None,
    title: str | None = None,
    scene_count: int | None = None,
    provider=None,
) -> dict:
    """生成并持久化一部完整互动剧本文案并返回结果 dict。"""
    project = session.get(Project, project_id)
    if project is None:
        raise NotFoundError("项目不存在")
    provider = provider or get_script_provider()
    schema = script_json_schema()
    task_id = f"script-{uuid.uuid4().hex[:8]}"

    run = trace_manager.start_run(session, kind="script_writer", meta={"project_id": project_id})
    system = _build_system(genre=genre, title_arg=title, scene_count=scene_count)

    try:
        trace_manager.add_step(
            session, run, agent="script_writer", step_key="script.input",
            input_data={"project_id": project_id, "goal": goal, "model": provider.model}, output_data={},
        )

        script_obj = None
        response = None
        last_error = "未知错误"
        for attempt in range(3):
            request = LLMRequest(
                system=system,
                user=goal or (title or "请写一部互动剧"),
                json_schema=schema,
                prompt_version=PROMPT_VERSION,
                budget=SCRIPT_BUDGET,
                request_id=f"script-{project_id[:8]}-{attempt + 1}",
            )
            try:
                response = await provider.generate_structured(request)
            except LLMProviderError as exc:
                trace_manager.add_step(
                    session, run, agent="script_writer", step_key="llm.error",
                    input_data={"attempt": attempt + 1}, output_data={}, error=exc.error.message, status="failed",
                )
                raise NotFoundError(f"剧本模型调用失败：{exc.error.message}")
            if response is None:
                raise NotFoundError("剧本模型未返回任何输出")
            raw = response.data or {}
            # 兼容：模型可能在顶层给了一个包裹的 script 字段
            if isinstance(raw, dict) and isinstance(raw.get("script"), dict) and "acts" in raw["script"]:
                raw = raw["script"]
            try:
                script_obj = Script.model_validate(raw)
                break
            except Exception as exc:  # noqa: BLE001 - pydantic ValidationError 等
                last_error = str(exc)
                trace_manager.add_step(
                    session, run, agent="script_writer", step_key="validation",
                    input_data={"attempt": attempt + 1}, output_data={"valid": False, "errors": last_error[:400]},
                    status="failed",
                )
                system = system + "\n[校验失败，请按 JSON Schema 修正]" + last_error[:400]

        if script_obj is None or response is None:
            raise NotFoundError(f"多次尝试仍无法产出合法剧本：{last_error}")

        artifact = persist_versioned_artifact(
            session,
            project_id=project_id,
            task_id=task_id,
            agent="script_writer",
            kind="script",
            content=script_obj.model_dump(),
            prompt_version=PROMPT_VERSION,
            source="agent",
            change_reason="AI 一键生成剧本",
        )
        n_scenes = sum(len(act.scenes) for act in script_obj.acts)
        trace_manager.add_step(
            session, run, agent="script_writer", step_key="artifact",
            input_data={"project_id": project_id},
            output_data={"kind": "script", "version": artifact.version, "scenes": n_scenes},
            token_usage=response.usage.model_dump(), status="ok",
        )
        trace_manager.finish_run(run, status="ok")
        session.commit()
        return {
            "project_id": project_id,
            "script": script_obj.model_dump(),
            "provider": response.provider,
            "model": response.model,
            "usage": response.usage.model_dump(),
            "latency_ms": response.latency_ms,
            "artifact_kind": "script",
            "version": artifact.version,
        }
    except Exception:
        session.rollback()
        raise
