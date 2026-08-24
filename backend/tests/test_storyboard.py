"""增量 Phase 3：分镜拆镜 + 视频生成测试。"""
from app.models import AgentSpec, Artifact, Project
from app.schemas.agent_plan import AgentPlan
from app.schemas.storyboard import (
    COST_PER_SECOND,
    Shot,
    Storyboard,
    auto_breakdown,
    compose_seedance_prompt,
    compose_shot_prompt,
    storyboard_template,
)


def _project(session) -> Project:
    project = Project(goal="制作互动悬疑短剧。", template="interactive_film")
    session.add(project)
    session.commit()
    return project


def test_template():
    t = storyboard_template()
    assert "特写" in t["shot_sizes"] and "跟随移动" in t["camera_movements"]
    assert t["cost_per_second"] == 10


def test_auto_breakdown_deterministic():
    sb = auto_breakdown("node-1", "天台相遇", 4)
    assert sb.node_id == "node-1"
    assert [s.shot_no for s in sb.shots] == [1, 2, 3, 4]
    assert all(s.duration_sec == 4 for s in sb.shots)


def test_compose_shot_prompt():
    shot = Shot(shot_no=1, visual_description="天台夕阳", shot_size="特写", dialogue="好久不见")
    prompt = compose_shot_prompt(shot)
    assert "画面：天台夕阳" in prompt and "景别：特写" in prompt and "对白（逐字）：好久不见" in prompt


def test_compose_seedance_prompt():
    sb = Storyboard(node_id="n", shots=[Shot(shot_no=1, visual_description="开场")])
    prompt = compose_seedance_prompt(sb)
    assert "[镜1" in prompt and "逐字对齐" in prompt and "字幕" in prompt


def test_breakdown_endpoint(client, session_factory):
    session = session_factory()
    project = _project(session)
    session.close()

    resp = client.post(f"/api/projects/{project.id}/storyboard/node-1/breakdown", json={"requested_shots": 5})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["version"] == 1 and len(body["shots"]) == 5
    assert body["seedance_prompt"] and "5" in body["shot_prompts"]


def test_save_and_read_storyboard(client, session_factory):
    session = session_factory()
    project = _project(session)
    session.close()

    sb = Storyboard(
        node_id="node-2", synopsis="对峙",
        shots=[Shot(shot_no=1, visual_description="镜头推进到男主", dialogue="你来了")],
    )
    resp = client.put(f"/api/projects/{project.id}/storyboard/node-2", json={"storyboard": sb.model_dump()})
    assert resp.status_code == 200, resp.text
    assert resp.json()["version"] == 1

    resp = client.get(f"/api/projects/{project.id}/storyboard/node-2")
    body = resp.json()
    assert body["version"] == 1 and body["shots"][0]["dialogue"] == "你来了"


def test_video_job_cost(client, session_factory):
    session = session_factory()
    project = _project(session)
    session.close()

    client.post(f"/api/projects/{project.id}/storyboard/node-3/breakdown", json={"requested_shots": 2})
    resp = client.post(f"/api/projects/{project.id}/storyboard/node-3/video", json={})
    assert resp.status_code == 200, resp.text
    job = resp.json()
    assert job["status"] == "done"
    assert job["duration_sec"] == 8.0  # 2 镜 × 4s
    assert job["total_cost"] == 80  # 8s × 10 积分
    assert job["cost_per_second"] == COST_PER_SECOND
    assert "连续视频" in job["seedance_director_prompt"]

    resp2 = client.get(f"/api/projects/{project.id}/storyboard/node-3/video")
    assert resp2.json()["job_id"] == job["job_id"]


def test_node_id_mismatch_400(client, session_factory):
    session = session_factory()
    project = _project(session)
    session.close()

    sb = Storyboard(node_id="node-x", shots=[])
    resp = client.put(f"/api/projects/{project.id}/storyboard/node-y", json={"storyboard": sb.model_dump()})
    assert resp.status_code == 400


def _ready_project(session, node_id: str) -> Project:
    """项目 + Director 规划 + StoryGraph（含 node_id 节点），供 AI 拆镜 agent 路径测试。"""
    project = Project(goal="制作互动悬疑短剧。", template="interactive_film")
    session.add(project)
    session.flush()
    plan = AgentPlan.model_validate({
        "goal": project.goal, "goal_summary": "测试", "project_type": "interactive_film",
        "target_audience": "悬疑", "genre": "悬疑", "tone": "紧张",
        "generation_steps": [{"id": "s1", "agent_type": "world", "objective": "世界观", "dependencies": []}],
    })
    session.add(AgentSpec(project_id=project.id, policies={"agent_plan": plan.model_dump()}, plan=[], status="ready"))
    session.add(Artifact(
        project_id=project.id, task_id="s4", agent="plot", kind="story_graph",
        content={"nodes": [{"node_id": node_id, "kind": "scene", "title": "天台", "summary": "雨夜天台对峙"}],
                 "edges": [], "variables": []},
        prompt_version="plot_generation:v1", version=1, is_latest=True,
    ))
    session.commit()
    return project


def test_breakdown_agent_path_no_404(client, session_factory):
    """有规划 + 有剧情节点的项目：/breakdown 走 StoryboardAgent；无 LLM 时回退 mock，但绝不 404。"""
    session = session_factory()
    project = _ready_project(session, "node-1")
    session.close()

    resp = client.post(f"/api/projects/{project.id}/storyboard/node-1/breakdown", json={"requested_shots": 4})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["version"] == 1
    assert len(body["shots"]) >= 1
    assert body["seedance_prompt"]

    # 落库后可读回
    got = client.get(f"/api/projects/{project.id}/storyboard/node-1")
    assert got.status_code == 200
    assert got.json()["shots"]