"""Step 7 测试：CharacterAgent Vertical Slice（WorldBible -> CharacterAgent -> CharacterCard Artifact）。"""
import asyncio
import json

import jsonschema
import pytest
from pydantic import ValidationError

from app.agents.character import CHARACTER_BUDGET, CharacterAgent
from app.llm.provider import MockProvider
from app.llm.types import LLMResponse
from app.schemas.agent_plan import AgentPlan
from app.schemas.character_card import CharacterCard, character_card_json_schema
from app.services.prompt_seed import ensure_character_prompt
from app.trace.manager import trace_manager

GOLDEN_GOAL = (
    "制作一个乙女悬疑Galgame。女主进入一家娱乐公司。三个男主：A顶流演员、B新人导演、"
    "C隐藏身份调查员。包含恋爱线、悬疑线，共5章，3个结局，玩家选择影响好感度和最终结局。"
)


class FakeProvider(MockProvider):
    """可编程 Provider：按队列返回 LLMResponse / 异常，并捕获收到的 LLMRequest。"""

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


def character_card_dict() -> dict:
    return {
        "character_id": "char-01", "name": "林晚", "role": "女主", "age": "22", "gender": "女",
        "appearance": "清冷气质的都市新人",
        "personality": ["坚韧", "敏锐"],
        "background": "娱乐公司新人，暗藏调查目的",
        "motivation": "查明亲人失踪真相", "goal": "揭开公司黑幕", "conflict": "恋爱与真相的取舍",
        "fear": "再失去重要之人", "secret": "真实身份是调查员之女",
        "relationship_rules": ["对信任者坦诚"],
        "speech_style": {"tone": "克制温柔", "formality": "偏礼貌", "catchphrases": ["嗯……"], "quirks": ["把玩发梢"]},
        "likes": ["推理小说"], "dislikes": ["被欺骗"],
        "hidden_information": ["其真实目的"],
        "character_arc": ["新人", "察觉异常", "直面真相"],
        "possible_endings": ["真相大白"],
    }


def _world() -> dict:
    return {
        "world_id": "world-01", "title": "乙女悬疑娱乐公司", "setting": "娱乐公司内的悬疑恋爱双线",
        "era": "现代", "location": "都市",
    }


def _plan_dict() -> dict:
    def t(i, a, o, deps=None):
        return {
            "id": i, "agent_type": a, "objective": o, "dependencies": deps or [],
            "output_schema": {"type": "object"},
        }

    return {
        "goal": GOLDEN_GOAL, "goal_summary": "乙女悬疑互动", "project_type": "galgame",
        "target_audience": "乙女用户", "genre": "乙女悬疑", "tone": "甜宠悬疑",
        "business_objective": "", "creative_objective": "",
        "required_capabilities": ["worldbuilding", "character"],
        "characters_required": "三男主一女主", "worldbuilding_required": "娱乐公司世界观",
        "story_required": "", "scene_required": "", "branch_required": "",
        "dialogue_required": "", "evaluation_required": "",
        "generation_steps": [t("s1", "world", "构建世界观"), t("s2", "character", "设计角色卡", ["s1"])],
        "success_metrics": [], "constraints": [],
        "budget": {"max_total_tokens": 100000, "max_cost_usd": None}, "priority": "high",
    }


@pytest.fixture()
def character_ctx(session_factory):
    session = session_factory()
    ensure_character_prompt(session)
    run = trace_manager.start_run(session, kind="orchestrate")
    yield session, run
    session.close()


def _run_character(session, run, provider, upstream=None, max_attempts=3):
    plan = AgentPlan.model_validate(_plan_dict())
    task = plan.generation_steps[1]  # s2 = character（依赖 s1/world）
    return asyncio.run(
        CharacterAgent(max_attempts=max_attempts).run({
            "session": session, "run": run, "task": task, "goal": GOLDEN_GOAL, "plan": plan,
            "project": {"genre": plan.genre, "tone": plan.tone, "project_type": plan.project_type},
            "upstream": upstream or {}, "provider": provider,
        })
    )


def test_character_card_schema_roundtrip():
    schema = character_card_json_schema()
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(character_card_dict(), schema)
    card = CharacterCard.model_validate(character_card_dict())
    assert CharacterCard.model_validate_json(card.model_dump_json()) == card
    # 结构化：speech_style 为嵌套对象，供 DialogueAgent 读取
    assert card.speech_style.tone == "克制温柔"
    assert card.speech_style.catchphrases == ["嗯……"]


def test_character_card_duplicate_likes_rejected():
    bad = character_card_dict()
    bad["likes"] = ["推理小说", "推理小说"]
    with pytest.raises(ValidationError):
        CharacterCard.model_validate(bad)


def test_character_card_id_whitespace_rejected():
    bad = character_card_dict()
    bad["character_id"] = "char 01"
    with pytest.raises(ValidationError):
        CharacterCard.model_validate(bad)


def test_character_agent_uses_structured_output(character_ctx):
    session, run = character_ctx
    fake = FakeProvider([character_card_dict()])
    result = _run_character(session, run, fake, max_attempts=1)
    req = fake.captured[0]
    assert req.json_schema["title"] == "CharacterCard"
    assert req.prompt_version == "character_generation:v1"
    assert req.budget == CHARACTER_BUDGET
    assert result["attempts"] == 1
    assert result["artifact"]["kind"] == "character_card:char-01"
    assert result["artifact"]["content"]["character_id"] == "char-01"


def test_character_agent_consumes_upstream_world(character_ctx):
    session, run = character_ctx
    fake = FakeProvider([character_card_dict()])
    # Step 9 起 upstream 按 task_id 键化：{task_id: {"kind", "content"}}
    _run_character(session, run, fake, upstream={"s1": {"kind": "world_bible", "content": _world()}}, max_attempts=1)
    req = fake.captured[0]
    # 上游 WorldBible 被注入 prompt（world -> character 数据流真实生效）
    assert "乙女悬疑娱乐公司" in req.system
    assert "现代" in req.system


def test_character_agent_repairs_invalid_then_succeeds(character_ctx):
    session, run = character_ctx
    bad = character_card_dict()
    bad["personality"] = ["坚韧", "坚韧"]  # 重复 -> Pydantic 拒绝 -> 反馈重试
    fake = FakeProvider([bad, character_card_dict()])
    result = _run_character(session, run, fake, max_attempts=3)
    assert result["attempts"] == 2
    assert result["artifact"]["content"]["name"] == "林晚"


def test_orchestrate_golden_scenario_character(client):
    created = client.post("/api/director/plan", json={"goal": GOLDEN_GOAL}).json()
    resp = client.post(f"/api/orchestrate/{created['project_id']}")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    steps = {s["key"]: s for s in data["steps"]}
    # 7 步闭环全部成功；scene/dialogue 扇出、finalize 编译收尾
    assert steps["s1"]["status"] == "succeeded" and steps["s1"]["agent"] == "world"
    assert steps["s2"]["status"] == "succeeded" and steps["s2"]["agent"] == "character"
    assert steps["s3"]["status"] == "succeeded" and steps["s3"]["agent"] == "relationship"
    assert steps["s4"]["status"] == "succeeded" and steps["s4"]["agent"] == "plot"
    assert steps["s5"]["status"] == "succeeded" and steps["s5"]["agent"] == "scene"
    # 结构 artifact 存在（含 scene:/dialogue: 节点级与 script_book 收尾）
    artifacts = {a["kind"]: a for a in data["artifacts"]}
    core = {"world_bible", "character_card:char-01", "relationship_graph", "story_graph", "script_book"}
    assert core <= set(artifacts)
    card = artifacts["character_card:char-01"]["content"]
    assert card["character_id"] == "char-01"
    assert card["name"] == "主角"
    assert isinstance(card["personality"], list) and card["personality"]
    assert isinstance(card["speech_style"], dict) and card["speech_style"]["tone"]


def test_orchestrate_trace_character(client):
    created = client.post("/api/director/plan", json={"goal": GOLDEN_GOAL}).json()
    client.post(f"/api/orchestrate/{created['project_id']}")
    traces = client.get(f"/api/projects/{created['project_id']}/traces").json()
    run = next(t for t in traces if t["kind"] == "orchestrate")
    keys = [s["step_key"] for s in run["steps"]]
    step_keys = [
        "character.input", "relationship.input", "plot.input", "world.input", "task.succeeded",
        "llm.request", "validation", "artifact",
    ]
    for k in step_keys:
        assert k in keys
    # world / character / relationship / plot 各有一条 artifact 轨迹
    assert sum(1 for k in keys if k == "artifact") >= 4