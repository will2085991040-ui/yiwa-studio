"""Step 3 测试：Prompt 版本基础设施（定义 + 不可变版本 + 变量渲染 + LLM 绑定）。"""
import asyncio

from app.llm.provider import MockProvider
from app.llm.types import LLMRequest
from app.models import PromptVersion
from app.services.prompts import prompt_tag, render


def test_definition_get_or_create_idempotent(client):
    r1 = client.post("/api/prompts/definitions", json={"name": "character_generation", "description": "生成角色卡"})
    assert r1.status_code == 200
    d1 = r1.json()
    r2 = client.post("/api/prompts/definitions", json={"name": "character_generation"})
    assert r2.status_code == 200
    assert r2.json()["id"] == d1["id"]  # get-or-create，不重复建


def test_version_auto_increment_append_never_overwrites(client):
    client.post("/api/prompts/definitions", json={"name": "director_plan"})
    r1 = client.post("/api/prompts/definitions/director_plan/versions", json={"content": "v1 内容"})
    r2 = client.post("/api/prompts/definitions/director_plan/versions", json={"content": "v2 内容", "status": "active"})
    assert r1.status_code == 201 and r2.status_code == 201
    v1, v2 = r1.json(), r2.json()
    assert v1["version_no"] == 1
    assert v2["version_no"] == 2
    assert v1["content"] == "v1 内容"  # v1 未被 v2 覆盖（不可变）
    assert v2["status"] == "active"


def test_list_and_get_version_ordered(client):
    client.post("/api/prompts/definitions", json={"name": "dialogue"})
    client.post("/api/prompts/definitions/dialogue/versions", json={"content": "c1"})
    client.post("/api/prompts/definitions/dialogue/versions", json={"content": "c2"})
    versions = client.get("/api/prompts/definitions/dialogue/versions").json()
    assert [v["version_no"] for v in versions] == [1, 2]
    assert client.get("/api/prompts/definitions/dialogue/versions/1").json()["content"] == "c1"


def test_get_missing_version_404(client):
    client.post("/api/prompts/definitions", json={"name": "story"})
    r = client.get("/api/prompts/definitions/story/versions/99")
    assert r.status_code == 404


def test_render_substitutes_variables_and_defaults(client):
    client.post("/api/prompts/definitions", json={"name": "character"})
    client.post(
        "/api/prompts/definitions/character/versions",
        json={
            "content": "你是{role}，擅长{skill}，面向{audience}。",
            "variables": [
                {"name": "role", "required": True},
                {"name": "skill", "required": True},
                {"name": "audience", "default": "大学生"},
            ],
        },
    )
    r = client.post(
        "/api/prompts/definitions/character/versions/1/render",
        json={"variables": {"role": "讲师", "skill": "Python"}},
    )
    assert r.status_code == 200
    out = r.json()
    assert out["prompt_id"] == "character"
    assert out["prompt_version"] == 1
    assert out["rendered"] == "你是讲师，擅长Python，面向大学生。"


def test_render_missing_required_variable_400(client):
    client.post("/api/prompts/definitions", json={"name": "req"})
    client.post(
        "/api/prompts/definitions/req/versions",
        json={"content": "你好{name}", "variables": [{"name": "name", "required": True}]},
    )
    r = client.post("/api/prompts/definitions/req/versions/1/render", json={"variables": {}})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "missing_variable"


def test_model_preferences_roundtrip(client):
    client.post("/api/prompts/definitions", json={"name": "sales"})
    prefs = {"model": "deepseek-chat", "temperature": 0.3, "max_tokens": 1500, "response_format": "json_object"}
    r = client.post("/api/prompts/definitions/sales/versions", json={"content": "x", "model_preferences": prefs})
    assert r.json()["model_preferences"] == prefs


def test_render_service_direct():
    """service 层渲染语义：required 缺省报错、有 default 用 default。"""
    version = PromptVersion(
        content="聚焦{主题}，面向{人群}",
        variables=[{"name": "主题", "required": True}, {"name": "人群", "default": "年轻人"}],
    )
    assert render(version, {"主题": "AI课程"}) == "聚焦AI课程，面向年轻人"
    try:
        version2 = PromptVersion(content="目标{目标}", variables=[{"name": "目标", "required": True}])
        render(version2, {})
        raise AssertionError("应当抛出缺少必需变量")
    except ValueError as exc:
        assert "目标" in str(exc)


def test_prompt_version_flows_into_llm_request():
    """Prompt 版本 -> LLMRequest.prompt_version -> LLMResponse 回显（未来 Agent 绑定的贯通证明）。"""
    tag = prompt_tag("character_generation", 2)
    request = LLMRequest(system="你是角色生成器", user="一个乙女游戏向导", prompt_version=tag)
    response = asyncio.run(MockProvider().generate(request))
    assert response.prompt_version == "character_generation:v2"