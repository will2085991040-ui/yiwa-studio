"""Step 12 测试：DialogueAgent Vertical Slice（按 (node_id, choice_id) 局部生成/修改/扩写对白）。"""
import asyncio
import json

import jsonschema
import pytest
from pydantic import ValidationError

from app.agents.base import registry
from app.agents.dialogue import DIALOGUE_BUDGET, DialogueAgent
from app.core.errors import AppError
from app.llm.provider import MockProvider
from app.llm.types import LLMResponse
from app.models import AgentRun, AgentSpec, AgentStep, Artifact, Project
from app.schemas.agent_plan import AgentPlan, ProductionTask
from app.schemas.dialogue import DialogueContent, dialogue_id, dialogue_json_schema, dialogue_kind
from app.schemas.story_graph import StoryCondition, StoryEffect
from app.services.context import compile_dialogue_context
from app.services.dialogue_service import _validate_references, run_dialogue_operation
from app.services.prompt_seed import ensure_dialogue_prompt
from app.trace.manager import trace_manager

GOAL = (
    "制作一个乙女悬疑Galgame。女主进入一家娱乐公司。三个男主：A顶流演员、B新人导演、"
    "C隐藏身份调查员。包含恋爱线、悬疑线，共5章，3个结局，玩家选择影响好感度和最终结局。"
)


class FakeProvider(MockProvider):
    name = "fake"
    model = "fake-model"

    def __init__(self, responses):
        super().__init__()
        self.responses = list(responses)
        self.captured: list = []

    async def _generate_structured(self, request):
        self.captured.append(request)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        if isinstance(item, dict):
            return LLMResponse(content=json.dumps(item, ensure_ascii=False), data=item)
        return item


# ---------------------------------------------------------------------------
# 数据夹具（与 mock Provider 产出的 StoryGraph / CharacterCard 保持一致）
# ---------------------------------------------------------------------------


def _story() -> dict:
    return {
        "graph_id": "story-01", "entry_node_id": "scene_01",
        "variables": [
            {"name": "affection", "type": "number", "initial": 0, "description": "好感度"},
            {"name": "trust", "type": "number", "initial": 0, "description": "信任度"},
        ],
        "nodes": [
            {
                "node_id": "scene_01", "kind": "scene", "title": "开局", "summary": "女主进入公司",
                "choices": [
                    {
                        "choice_id": "c01a", "text": "帮助女主",
                        "effects": [{"variable": "affection", "op": "add", "value": 10}], "next_node": "scene_02a",
                    },
                    {
                        "choice_id": "c01b", "text": "欺骗女主",
                        "effects": [{"variable": "trust", "op": "add", "value": -10}], "next_node": "scene_02b",
                    },
                    {"choice_id": "c01c", "text": "离开", "next_node": "scene_02c"},
                ],
            },
            {"node_id": "scene_02a", "kind": "scene", "title": "同盟", "summary": "与女主结盟"},
            {"node_id": "scene_02b", "kind": "scene", "title": "裂痕", "summary": "女主起疑"},
            {"node_id": "scene_02c", "kind": "ending", "title": "退出", "summary": "玩家离开"},
        ],
        "edges": [
            {"edge_id": "e1", "source": "scene_01", "target": "scene_02a", "label": "c01a"},
            {"edge_id": "e2", "source": "scene_01", "target": "scene_02b", "label": "c01b"},
            {"edge_id": "e3", "source": "scene_01", "target": "scene_02c", "label": "c01c"},
        ],
        "metadata": {},
    }


def _character(character_id: str, name: str, role: str) -> dict:
    return {
        "kind": "character_card",
        "content": {
            "character_id": character_id, "name": name, "role": role,
            "personality": ["温柔"], "motivation": "守护",
            "speech_style": {"tone": "温柔", "formality": "口语", "catchphrases": ["哼"], "quirks": ["轻声"]},
        },
    }


def _scene_content() -> dict:
    return {
        "scene_id": "scene_01", "title": "入职第一天", "summary": "女主初入公司",
        "location": "前台大厅", "time": "白天 · 上午", "atmosphere": "紧张",
        "characters_present": ["char-01"],
        "events": ["办理入职"], "visual_direction": "", "camera_direction": "",
        "stage_direction": "", "emotional_beats": ["忐忑"],
        "state_changes": [], "continuity_notes": "", "asset_requirements": {},
    }


def _upstream(with_scene: bool = False) -> dict:
    up = {
        "s1": {
            "kind": "world_bible",
            "content": {"world_id": "world-01", "title": "乙女悬疑世界", "setting": "娱乐公司"},
        },
        "c1": _character("char-01", "林晚", "女主"),
        "c2": _character("char-02", "顾沉", "男二"),
        "r1": {
            "kind": "relationship_graph",
            "content": {
                "graph_id": "rel-01", "characters": ["char-01", "char-02", "char-03"],
                "edges": [
                    {"source_character": "char-01", "target_character": "char-02", "relationship_type": "爱慕"},
                    {"source_character": "char-02", "target_character": "char-03", "relationship_type": "敌对"},
                ],
            },
        },
        "s4": {"kind": "story_graph", "content": _story()},
    }
    if with_scene:
        up["sc1"] = {"kind": "scene:scene_01", "content": _scene_content()}
    return up


def _dialogue() -> dict:
    return {
        "dialogue_id": "scene_01:default", "node_id": "scene_01", "choice_id": None,
        "lines": [
            {
                "speaker": "char-01", "text": "欢迎来到公司。", "emotion": "温柔",
                "delivery": "轻声", "action": "", "target": None, "relationship_context": "",
            },
        ],
        "conditions": [{"variable": "affection", "op": ">=", "value": 0}],
        "effects": [],
        "next_node": None, "branch": None, "tags": ["demo"], "continuity_notes": "", "asset_requirements": {},
    }


# ---------------------------------------------------------------------------
# StoryCondition / StoryEffect 结构化 schema（Step 12）
# ---------------------------------------------------------------------------


def test_story_condition_schema_roundtrip():
    c = StoryCondition.model_validate({"variable": "affection", "op": ">=", "value": 10})
    assert c.op == ">=" and c.value == 10 and c.variable == "affection"
    assert StoryCondition.model_validate_json(c.model_dump_json()) == c
    # bool 也应被接受（number | bool | str）
    assert StoryCondition.model_validate({"variable": "x", "op": "==", "value": True}).value is True


def test_story_condition_rejects_bad_value_and_op():
    with pytest.raises(ValidationError):
        StoryCondition.model_validate({"variable": "x", "op": ">=", "value": {"a": 1}})
    with pytest.raises(ValidationError):
        StoryCondition.model_validate({"variable": "x", "op": ">=", "value": None})
    with pytest.raises(ValidationError):
        StoryCondition.model_validate({"variable": "x", "op": "~=", "value": 1})


def test_story_effect_sub_and_illegal_op():
    assert StoryEffect.model_validate({"variable": "trust", "op": "sub", "value": 5}).op == "sub"
    # 向后兼容：add / set 仍合法
    assert StoryEffect.model_validate({"variable": "x", "op": "add", "value": 1}).op == "add"
    assert StoryEffect.model_validate({"variable": "x", "op": "set", "value": 1}).op == "set"
    with pytest.raises(ValidationError):
        StoryEffect.model_validate({"variable": "x", "op": "mul", "value": 1})


# ---------------------------------------------------------------------------
# DialogueContent Schema
# ---------------------------------------------------------------------------


def test_dialogue_schema_roundtrip():
    schema = dialogue_json_schema()
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(_dialogue(), schema)
    d = DialogueContent.model_validate(_dialogue())
    assert DialogueContent.model_validate_json(d.model_dump_json()) == d
    assert d.dialogue_id == "scene_01:default"
    assert d.node_id == "scene_01" and d.choice_id is None
    assert len(d.lines) == 1 and d.lines[0].speaker == "char-01"


def test_dialogue_schema_rejects_empty_lines_and_blank_speaker():
    bad = _dialogue()
    bad["lines"] = []
    with pytest.raises(ValidationError):
        DialogueContent.model_validate(bad)
    bad2 = _dialogue()
    bad2["lines"][0]["speaker"] = ""
    with pytest.raises(ValidationError):
        DialogueContent.model_validate(bad2)
    bad3 = _dialogue()
    bad3["lines"][0]["speaker"] = "   "
    with pytest.raises(ValidationError):
        DialogueContent.model_validate(bad3)
    bad4 = _dialogue()
    bad4["lines"][0]["text"] = "   "
    with pytest.raises(ValidationError):
        DialogueContent.model_validate(bad4)


def test_dialogue_schema_tags_dedup_and_blank_rejected():
    d = DialogueContent.model_validate({**_dialogue(), "tags": ["a", "b", "a", "  c  "]})
    assert d.tags == ["a", "b", "c"]
    with pytest.raises(ValidationError):
        DialogueContent.model_validate({**_dialogue(), "tags": ["a", "  "]})
    with pytest.raises(ValidationError):
        DialogueContent.model_validate({**_dialogue(), "node_id": "   "})


def test_dialogue_kind_and_id_derivation():
    assert dialogue_kind("scene_01", None) == "dialogue:scene_01"
    assert dialogue_kind("scene_01", "c01a") == "dialogue:scene_01:c01a"
    assert dialogue_id("scene_01", None) == "scene_01:default"
    assert dialogue_id("scene_01", "c01a") == "scene_01:c01a"


# ---------------------------------------------------------------------------
# Thin Context Compiler
# ---------------------------------------------------------------------------


def test_compiler_scene_present_injects_fields():
    ctx = compile_dialogue_context(_upstream(with_scene=True), node_id="scene_01", choice_id=None, instruction=None)
    assert "入职第一天" in ctx["scene"]
    assert "前台大厅" in ctx["scene"]
    assert "characters_present" in ctx["scene"]
    assert ctx["missing"] == []


def test_compiler_scene_missing_marks_missing():
    ctx = compile_dialogue_context(_upstream(with_scene=False), node_id="scene_01", choice_id=None, instruction=None)
    assert "缺失" in ctx["scene"]
    assert ctx["missing"] == ["scene:scene_01"]


def test_compiler_scopes_characters_and_relationships():
    ctx = compile_dialogue_context(_upstream(with_scene=True), node_id="scene_01", choice_id=None, instruction=None)
    # 场景在场角色只有 char-01：char-02（顾沉）不应被注入
    assert "林晚" in ctx["characters"]
    assert "顾沉" not in ctx["characters"]
    assert "口头禅=哼" in ctx["characters"]
    # 关系边只保留涉及 char-01 的：char-01—爱慕→char-02 保留，char-02—敌对→char-03 滤除
    assert "爱慕" in ctx["relationships"]
    assert "敌对" not in ctx["relationships"]


def test_compiler_choice_focus_and_instruction():
    ctx = compile_dialogue_context(_upstream(), node_id="scene_01", choice_id="c01a", instruction="让女主更傲娇")
    assert "c01a" in ctx["focus"]
    assert "帮助女主" in ctx["focus"]
    assert "scene_02a" in ctx["focus"]
    assert "affection" in ctx["focus"]  # 选择效果
    assert "让女主更傲娇" in ctx["focus"]
    ctx2 = compile_dialogue_context(_upstream(), node_id="scene_01", choice_id=None, instruction=None)
    assert "默认" in ctx2["focus"]


def test_compiler_skeleton_variables_and_locked_protected():
    ctx = compile_dialogue_context(_upstream(), node_id="scene_01", choice_id=None, instruction=None)
    assert "scene_01" in ctx["skeleton"]
    assert "affection" in ctx["skeleton"] and "trust" in ctx["skeleton"]
    assert ctx["protected"] == ""
    locked = _story()
    locked["nodes"][0]["locked"] = True
    up = _upstream()
    up["s4"]["content"] = locked
    ctx2 = compile_dialogue_context(up, node_id="scene_01", choice_id=None, instruction=None)
    assert "LOCKED" in ctx2["protected"] and "scene_01" in ctx2["protected"]


# ---------------------------------------------------------------------------
# DialogueAgent
# ---------------------------------------------------------------------------


@pytest.fixture()
def dialogue_ctx(session_factory):
    session = session_factory()
    ensure_dialogue_prompt(session)
    run = trace_manager.start_run(session, kind="orchestrate")
    yield session, run
    session.close()


def _run_agent(session, run, provider, upstream, node_id, choice_id=None, instruction=None):
    context = compile_dialogue_context(upstream, node_id=node_id, choice_id=choice_id, instruction=instruction)
    task = ProductionTask(id=f"dialogue-{node_id}", agent_type="dialogue", objective="生成该对白")
    return asyncio.run(
        DialogueAgent(max_attempts=3).run({
            "session": session, "run": run, "task": task, "goal": GOAL,
            "node_id": node_id, "choice_id": choice_id, "context": context,
            "provider": provider, "instruction": instruction,
        })
    )


def test_dialogue_agent_injects_context(dialogue_ctx):
    session, run = dialogue_ctx
    fake = FakeProvider([_dialogue()])
    result = _run_agent(session, run, fake, _upstream(with_scene=True), "scene_01", instruction="让女主更傲娇")
    req = fake.captured[0]
    assert req.json_schema["title"] == "DialogueContent"
    assert req.prompt_version == "dialogue_generation:v1"
    assert req.budget == DIALOGUE_BUDGET
    # 世界/角色(声线)/关系/骨架/场景/指令 全注入
    for token in ("乙女悬疑", "林晚", "口头禅=哼", "爱慕", "前台大厅", "affection", "scene_01", "让女主更傲娇"):
        assert token in req.system
    assert result["artifact"]["kind"] == "dialogue"
    assert result["artifact"]["content"]["node_id"] == "scene_01"  # 稳定引用被强制
    assert result["artifact"]["content"]["choice_id"] is None
    assert result["attempts"] == 1


def test_dialogue_agent_pipeline_false():
    assert DialogueAgent().pipeline is False
    assert registry.get("dialogue").pipeline is False


# ---------------------------------------------------------------------------
# DialgoueService / API 垂直切片
# ---------------------------------------------------------------------------


def _make_ready(client) -> str:
    created = client.post("/api/director/plan", json={"goal": GOAL}).json()
    assert client.post(f"/api/orchestrate/{created['project_id']}").status_code == 200
    return created["project_id"]


def _seed_project(session, *, story=None, with_character=True) -> Project:
    project = Project(goal=GOAL, template="galgame")
    session.add(project)
    session.flush()
    plan = AgentPlan.model_validate({
        "goal": GOAL, "goal_summary": "测试", "project_type": "galgame",
        "target_audience": "乙女", "genre": "乙女悬疑", "tone": "甜宠",
        "generation_steps": [{"id": "s4", "agent_type": "plot", "objective": "剧情图"}],
    })
    session.add(AgentSpec(project_id=project.id, policies={"agent_plan": plan.model_dump()}, plan=[], status="ready"))
    session.flush()
    session.add(Artifact(
        project_id=project.id, task_id="s4", agent="plot", kind="story_graph",
        content=story or _story(), prompt_version="plot_generation:v1", version=1, is_latest=True,
    ))
    if with_character:
        session.add(Artifact(
            project_id=project.id, task_id="c1", agent="character", kind="character_card",
            content={"character_id": "char-01", "name": "林晚", "role": "女主"}, version=1, is_latest=True,
        ))
    session.commit()
    return project


def test_generate_dialogue_default_local_persisted(client):
    pid = _make_ready(client)
    resp = client.post(f"/api/projects/{pid}/dialogue", json={"operation": "generate", "node_id": "scene_01"})
    assert resp.status_code == 200, resp.text
    arts = {a["kind"]: a for a in resp.json()["artifacts"]}
    assert "dialogue:scene_01" in arts
    art = arts["dialogue:scene_01"]
    assert art["content"]["dialogue_id"] == "scene_01:default"
    assert art["content"]["node_id"] == "scene_01" and art["content"]["choice_id"] is None
    # 一键生成已扇出 dialogue:scene_01 v1，故局部生成为 v2
    assert art["version"] == 2 and art["source"] == "agent"
    # mock 对白里的 sub 效果被原样保留（Step12 声明、不执行）
    assert art["content"]["effects"][0]["op"] == "sub"
    # 局部生成：world/character/relationship/story_graph 均未重新生成（Orchestrator 未被触发）
    for k in ("world_bible", "character_card:char-01", "relationship_graph", "story_graph"):
        assert arts[k]["version"] == 1


def test_generate_dialogue_with_choice_kind(client):
    pid = _make_ready(client)
    resp = client.post(
        f"/api/projects/{pid}/dialogue",
        json={"operation": "generate", "node_id": "scene_01", "choice_id": "c01a"},
    )
    assert resp.status_code == 200, resp.text
    arts = {a["kind"]: a for a in resp.json()["artifacts"]}
    assert "dialogue:scene_01:c01a" in arts
    art = arts["dialogue:scene_01:c01a"]
    assert art["content"]["dialogue_id"] == "scene_01:c01a"
    assert art["content"]["choice_id"] == "c01a" and art["content"]["node_id"] == "scene_01"
    assert art["version"] == 1 and art["source"] == "agent"


def test_revise_dialogue_creates_v2(client):
    pid = _make_ready(client)
    client.post(f"/api/projects/{pid}/dialogue", json={"operation": "generate", "node_id": "scene_01"})
    resp = client.post(
        f"/api/projects/{pid}/dialogue",
        json={"operation": "revise", "node_id": "scene_01", "instruction": "让女主的台词更傲娇"},
    )
    assert resp.status_code == 200, resp.text
    art = {a["kind"]: a for a in resp.json()["artifacts"]}["dialogue:scene_01"]
    # 扇出 v1 -> 生成 v2 -> 修改 v3
    assert art["version"] == 3 and art["source"] == "user"
    assert art["parent_version"] == 2 and art["change_reason"] == "让女主的台词更傲娇"


def test_expand_dialogue_appends_line(client):
    pid = _make_ready(client)
    gen = client.post(f"/api/projects/{pid}/dialogue", json={"operation": "generate", "node_id": "scene_01"}).json()
    before = {a["kind"]: a for a in gen["artifacts"]}["dialogue:scene_01"]["content"]["lines"]
    resp = client.post(
        f"/api/projects/{pid}/dialogue",
        json={"operation": "expand", "node_id": "scene_01", "instruction": "再补两句"},
    )
    assert resp.status_code == 200, resp.text
    art = {a["kind"]: a for a in resp.json()["artifacts"]}["dialogue:scene_01"]
    after = art["content"]["lines"]
    assert art["version"] == 3 and art["change_reason"] == "[expand] 再补两句"  # 扇出 v1 -> 生成 v2 -> 扩写 v3
    assert len(after) == len(before) + 1  # 确定性追加了一条对白
    assert after[-1]["speaker"] == "char-01"
    assert "再补两句" in after[-1]["text"]


def test_default_vs_choice_version_independently(client):
    pid = _make_ready(client)
    client.post(f"/api/projects/{pid}/dialogue", json={"operation": "generate", "node_id": "scene_01"})
    out = client.post(
        f"/api/projects/{pid}/dialogue",
        json={"operation": "generate", "node_id": "scene_01", "choice_id": "c01a"},
    ).json()
    arts = {a["kind"]: a for a in out["artifacts"]}
    assert arts["dialogue:scene_01"]["version"] == 2     # 扇出 v1 后生成 v2
    assert arts["dialogue:scene_01:c01a"]["version"] == 1  # choice 级从未扇出，仍为 v1（各自独立版本链）


def test_locked_dialogue_rejected(session_factory):
    session = session_factory()
    story = _story()
    story["nodes"][0]["locked"] = True
    project = _seed_project(session, story=story)
    with pytest.raises(AppError) as exc:
        asyncio.run(run_dialogue_operation(session, project.id, operation="generate", node_id="scene_01"))
    assert exc.value.code == "locked_node"
    session.close()


def test_dialogue_choice_not_found(session_factory):
    session = session_factory()
    project = _seed_project(session)
    with pytest.raises(AppError) as exc:
        asyncio.run(run_dialogue_operation(
            session, project.id, operation="generate", node_id="scene_01", choice_id="nope",
        ))
    assert exc.value.code == "choice_not_found"
    session.close()


def test_dialogue_node_not_found(session_factory):
    session = session_factory()
    project = _seed_project(session)
    with pytest.raises(AppError) as exc:
        asyncio.run(run_dialogue_operation(session, project.id, operation="generate", node_id="scene_99"))
    assert exc.value.code == "node_not_found"
    session.close()


def test_dialogue_reference_validation_codes():
    graph = _story()
    chars = {"char-01"}
    with pytest.raises(AppError) as e:
        _validate_references({"lines": [{"speaker": "char-99", "text": "x", "target": None}]}, graph, chars)
    assert e.value.code == "speaker_not_found"
    with pytest.raises(AppError) as e:
        _validate_references({"lines": [{"speaker": "char-01", "text": "x", "target": "char-99"}]}, graph, chars)
    assert e.value.code == "target_not_found"
    with pytest.raises(AppError) as e:
        _validate_references(
            {"lines": [{"speaker": "char-01", "text": "x", "target": None}], "next_node": "nope"}, graph, chars,
        )
    assert e.value.code == "next_node_not_found"
    with pytest.raises(AppError) as e:
        _validate_references(
            {"lines": [{"speaker": "char-01", "text": "x", "target": None}],
             "conditions": [{"variable": "nope_var", "op": ">=", "value": 1}]}, graph, chars,
        )
    assert e.value.code == "variable_not_found"
    with pytest.raises(AppError) as e:
        _validate_references(
            {"lines": [{"speaker": "char-01", "text": "x", "target": None}],
             "effects": [{"variable": "nope_var", "op": "add", "value": 1}]}, graph, chars,
        )
    assert e.value.code == "variable_not_found"
    # 全合法：不抛异常
    _validate_references({
        "lines": [{"speaker": "char-01", "text": "x", "target": "char-01"}],
        "next_node": "scene_02a",
        "conditions": [{"variable": "affection", "op": ">=", "value": 1}],
        "effects": [{"variable": "trust", "op": "sub", "value": 5}],
    }, graph, chars)


def test_dialogue_speaker_not_found_via_service(session_factory):
    """服务端强制引用校验：无角色卡时，mock 的 char-01 台词被拒绝（speaker_not_found）。"""
    session = session_factory()
    project = _seed_project(session, with_character=False)
    with pytest.raises(AppError) as exc:
        asyncio.run(run_dialogue_operation(session, project.id, operation="generate", node_id="scene_01"))
    assert exc.value.code == "speaker_not_found"
    session.close()


def test_dialogue_trace_records_input_and_missing_scene(session_factory):
    session = session_factory()
    project = _seed_project(session)  # 有 story_graph + character_card，但无 scene 工件
    asyncio.run(run_dialogue_operation(session, project.id, operation="generate", node_id="scene_01"))
    run = (
        session.query(AgentRun)
        .filter(AgentRun.kind == "dialogue_generate")
        .order_by(AgentRun.started_at.desc())
        .first()
    )
    assert run is not None and run.status == "ok"
    steps = {s.step_key: s for s in session.query(AgentStep).filter(AgentStep.agent_run_id == run.id).all()}
    assert "dialogue.input" in steps and "artifact" in steps
    inp = steps["dialogue.input"]
    assert inp.input_data["node_id"] == "scene_01"
    assert inp.input_data["choice_id"] is None
    assert inp.input_data["instruction"] == ""
    assert inp.input_data["context"]["missing"] == ["scene:scene_01"]  # 诚实标记 Scene 缺失
    assert inp.output_data["prompt_version"] == "dialogue_generation:v1"
    art = steps["artifact"]
    assert art.output_data["kind"] == "dialogue:scene_01"
    assert art.output_data["event_count"] == 2  # mock 确定性产出两行对白
    session.close()