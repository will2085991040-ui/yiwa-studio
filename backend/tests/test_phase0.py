"""Phase 0 测试套件：健康检查 / 规划器 / Golden Path 创建流 / 注册表 / MockProvider / DraftRuntime / 轨迹。"""


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert data["llm_provider"] == "mock"
    assert data["agents_registered"] >= 14


def test_agents_registry(client):
    r = client.get("/api/agents")
    assert r.status_code == 200
    agents = {a["name"]: a for a in r.json()}
    required = [
        "director", "audience", "strategy", "funnel", "character",
        "branch", "runtime", "evaluation", "optimization",
    ]
    for name in required:
        assert name in agents
    # 已落地真实实现：Director/World/Character/Relationship/Plot
    # /Scene(on-demand)/Dialogue(on-demand)/Storyboard(on-demand)
    assert agents["director"]["implemented"] is True
    assert agents["world"]["implemented"] is True
    assert agents["character"]["implemented"] is True
    assert agents["relationship"]["implemented"] is True
    assert agents["plot"]["implemented"] is True
    assert agents["scene"]["implemented"] is True
    assert agents["dialogue"]["implemented"] is True
    assert agents["storyboard"]["implemented"] is True
    assert all(
        a["implemented"] is False for name, a in agents.items()
        if name not in {"director", "world", "character", "relationship", "plot", "scene", "dialogue", "storyboard"}
    )


def test_planner_templates():
    from app.services.planner import build_plan

    course = build_plan("我想推广一个AI编程课程，面向大学生")
    assert course.template == "course_promotion"
    assert len(course.steps) == 14
    assert course.steps[0]["key"] == "understand_goal"
    assert course.steps[-1]["key"] == "ready"
    assert all(s["status"] == "pending" for s in course.steps)

    cs = build_plan("给一个SaaS产品建立AI客服")
    assert cs.template == "customer_service"

    drama = build_plan("制作一个互动短剧")
    assert drama.template == "interactive_drama"

    generic = build_plan("一个完全无关的目标描述")
    assert generic.template == "generic"


def test_golden_path_create_agent(client):
    """Golden Path 第一步：自然语言 → Project + AgentSpec + AgentVersion v1 + Trace。"""
    goal = "我想推广一个AI编程课程，目标用户是大学生，希望引导用户体验免费试听"
    r = client.post("/api/projects", json={"goal": goal})
    assert r.status_code == 201, r.text
    data = r.json()

    assert data["project_id"]
    assert data["template"] == "course_promotion"
    assert data["agent_spec"]["plan"][0]["key"] == "understand_goal"
    assert data["agent_version"]["version_no"] == 1
    assert data["agent_version"]["status"] == "draft"

    # 项目列表可见
    projects = client.get("/api/projects").json()
    assert any(p["id"] == data["project_id"] for p in projects)


def test_workflow_endpoint(client):
    pid = client.post("/api/projects", json={"goal": "制作一个互动短剧"}).json()["project_id"]
    w = client.get(f"/api/projects/{pid}/workflow").json()
    assert w["status"] == "draft"
    assert len(w["steps"]) == 14
    assert all(s["status"] == "pending" for s in w["steps"])


def test_chat_draft_is_real(client):
    """草稿期聊天：真实读库 + 记录 Trace，不使用假对话。"""
    pid = client.post("/api/projects", json={"goal": "我想做一个AI客服Agent"}).json()["project_id"]
    r = client.post(f"/api/projects/{pid}/chat", json={"message": "你好，我想了解课程"})
    assert r.status_code == 200
    data = r.json()
    assert "骨架" in data["reply"]
    assert data["template"] == "customer_service"

    traces = client.get(f"/api/projects/{pid}/traces").json()
    kinds = [t["kind"] for t in traces]
    assert "create_agent" in kinds
    assert "chat" in kinds
    chat_run = next(t for t in traces if t["kind"] == "chat")
    assert chat_run["status"] == "ok"
    assert chat_run["steps"][0]["agent"] == "director"


def test_mock_provider_schema_synthesis():
    import asyncio

    from app.llm.provider import MockProvider

    schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "tags": {"type": "array", "items": {"type": "string"}},
            "score": {"type": "integer"},
            "ok": {"type": "boolean"},
            "nested": {"type": "object", "properties": {"x": {"type": "string"}}},
        },
    }
    result = asyncio.run(MockProvider().complete("sys", "user", schema))
    assert result.provider == "mock"
    assert isinstance(result.data["name"], str)
    assert isinstance(result.data["tags"], list) and len(result.data["tags"]) >= 1
    assert isinstance(result.data["score"], int)
    assert isinstance(result.data["ok"], bool)
    assert isinstance(result.data["nested"]["x"], str)
    assert result.latency_ms >= 0


def test_trace_steps_ordered(client):
    pid = client.post("/api/projects", json={"goal": "推广一门AI课程"}).json()["project_id"]
    client.post(f"/api/projects/{pid}/chat", json={"message": "hi"})
    traces = client.get(f"/api/projects/{pid}/traces").json()
    chat_run = next(t for t in traces if t["kind"] == "chat")
    assert chat_run["steps"][0]["seq"] == 1


def test_chat_building_reports_progress(client, session_factory):
    """构建中状态：AI 导演如实汇报步骤进度与已产出，不再返回"未接入"死路。"""
    from app.models import AgentSpec, Artifact

    pid = client.post("/api/projects", json={"goal": "制作一个互动悬疑AVG"}).json()["project_id"]
    session = session_factory()
    spec = session.query(AgentSpec).filter(AgentSpec.project_id == pid).first()
    spec.status = "building"
    session.add(Artifact(
        project_id=pid, task_id="s5", agent="plot", kind="story_graph",
        content={"nodes": [{"node_id": "n1", "title": "初遇"}], "edges": [], "variables": []},
        prompt_version="plot_generation:v1", version=1, is_latest=True,
    ))
    session.commit()
    session.close()

    r = client.post(f"/api/projects/{pid}/chat", json={"message": "现在到哪一步了"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["status"] == "building"
    assert "正在构建" in data["reply"]
    assert "剧情图" in data["reply"]


def test_chat_built_uses_director(client, session_factory):
    """构建完成状态：AI 导演基于真实成品回应（若 LLM 可用则走 Director 交互，否则诚实汇报）。"""
    from app.models import AgentSpec, Artifact

    pid = client.post("/api/projects", json={"goal": "做一个恋爱互动AVG"}).json()["project_id"]
    session = session_factory()
    spec = session.query(AgentSpec).filter(AgentSpec.project_id == pid).first()
    spec.status = "ok"
    session.add(Artifact(
        project_id=pid, task_id="s2", agent="character", kind="character_card:char-01",
        content={"character_id": "char-01", "name": "林晚", "role": "女主"},
        prompt_version="character_generation:v1", version=1, is_latest=True,
    ))
    session.add(Artifact(
        project_id=pid, task_id="s5", agent="plot", kind="story_graph",
        content={"nodes": [{"node_id": "n1", "title": "初遇"}], "edges": [], "variables": []},
        prompt_version="plot_generation:v1", version=1, is_latest=True,
    ))
    session.commit()
    session.close()

    r = client.post(f"/api/projects/{pid}/chat", json={"message": "帮我看看剧情有什么问题"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["status"] == "ok"
    assert data["reply"]
    # 无论走 LLM（真实导演）还是回退汇报，都不得再是"未接入"的死路文案
    assert "未接入" not in data["reply"]
