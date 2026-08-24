"""Step 13 测试：Story State / Runtime 最小闭环（确定性求值 + 状态推进 + API）。"""
import pytest

from app.core.errors import AppError
from app.models import AgentRun, AgentStep, Artifact, PlayerSession, Project
from app.runtime.engine import (
    apply_effect,
    apply_effects,
    create_initial_state,
    evaluate_condition,
    parse_condition,
    visible_choices,
)
from app.runtime.session_service import (
    choose_choice,
    create_runtime_session,
    get_runtime_session,
    runtime_choices,
)
from app.runtime.state import StateManager
from app.schemas.story_graph import StoryGraph

GOAL = (
    "制作一个乙女悬疑Galgame。女主进入一家娱乐公司。三个男主：A顶流演员、B新人导演、"
    "C隐藏身份调查员。包含恋爱线、悬疑线，共5章，3个结局，玩家选择影响好感度和最终结局。"
)


def _story() -> dict:
    """含条件/加减设效果/merge/ending 的迷你剧情图。"""
    return {
        "graph_id": "story-13", "entry_node_id": "start",
        "variables": [
            {"name": "affection", "type": "number", "initial": 0, "description": "好感度"},
            {"name": "trust", "type": "number", "initial": 0, "description": "信任度"},
            {"name": "has_clue", "type": "bool", "initial": False, "description": "线索"},
        ],
        "nodes": [
            {
                "node_id": "start", "kind": "scene", "title": "起点", "summary": "",
                "choices": [
                    {
                        "choice_id": "c_high", "text": "高好感", "condition": "affection >= 10",
                        "effects": [{"variable": "trust", "op": "add", "value": 5}], "next_node": "good_end",
                    },
                    {
                        "choice_id": "c_gain", "text": "积累好感",
                        "effects": [{"variable": "affection", "op": "add", "value": 15}], "next_node": "start2",
                    },
                    {
                        "choice_id": "c_illegal", "text": "非法条件", "condition": "affection ??? 10",
                        "effects": [], "next_node": "bad_end",
                    },
                ],
            },
            {
                "node_id": "start2", "kind": "scene", "title": "第二阶段", "summary": "",
                "choices": [
                    {
                        "choice_id": "c_high2", "text": "高好感", "condition": "affection >= 10",
                        "effects": [{"variable": "trust", "op": "sub", "value": 3}], "next_node": "good_end",
                    },
                    {
                        "choice_id": "c_bad", "text": "走坏结局",
                        "effects": [{"variable": "trust", "op": "set", "value": -100}], "next_node": "bad_end",
                    },
                    {"choice_id": "c_merge", "text": "进汇合点", "effects": [], "next_node": "merge_node"},
                ],
            },
            {"node_id": "good_end", "kind": "ending", "title": "好结局", "summary": ""},
            {"node_id": "bad_end", "kind": "ending", "title": "坏结局", "summary": ""},
            {"node_id": "merge_node", "kind": "merge", "title": "汇合点", "summary": "各分支汇合"},
        ],
        "edges": [], "metadata": {},
    }


def _seed_project(session, story) -> Project:
    project = Project(goal=GOAL, template="galgame")
    session.add(project)
    session.flush()
    session.add(Artifact(
        project_id=project.id, task_id="s4", agent="plot", kind="story_graph",
        content=story, prompt_version="plot_generation:v1", version=1, is_latest=True,
    ))
    session.commit()
    return project


# ---------------------------------------------------------------------------
# evaluate_condition / apply_effect（确定性引擎）
# ---------------------------------------------------------------------------


def test_evaluate_condition_all_ops():
    state = {"affection": 10, "flag": True, "name": "A"}
    assert evaluate_condition({"variable": "affection", "op": ">=", "value": 10}, state) is True
    assert evaluate_condition({"variable": "affection", "op": "<=", "value": 10}, state) is True
    assert evaluate_condition({"variable": "affection", "op": ">", "value": 5}, state) is True
    assert evaluate_condition({"variable": "affection", "op": "<", "value": 5}, state) is False
    assert evaluate_condition({"variable": "affection", "op": "==", "value": 10}, state) is True
    assert evaluate_condition({"variable": "affection", "op": "!=", "value": 10}, state) is False
    assert evaluate_condition({"variable": "flag", "op": "==", "value": True}, state) is True
    assert evaluate_condition({"variable": "name", "op": "==", "value": "A"}, state) is True
    # 跨类型判不等（数字 vs 字符串）
    assert evaluate_condition({"variable": "affection", "op": "==", "value": "10"}, state) is False


def test_apply_effect_add_sub_set():
    assert apply_effect({"variable": "a", "op": "add", "value": 5}, {"a": 1}) == {"a": 6}
    assert apply_effect({"variable": "a", "op": "sub", "value": 5}, {"a": 10}) == {"a": 5}
    assert apply_effect({"variable": "s", "op": "set", "value": "done"}, {"s": "waiting"}) == {"s": "done"}


def test_apply_effect_does_not_mutate_input():
    state = {"a": 1, "b": 2}
    apply_effect({"variable": "a", "op": "add", "value": 5}, state)
    assert state == {"a": 1, "b": 2}
    out = apply_effects(
        [{"variable": "a", "op": "add", "value": 1}, {"variable": "b", "op": "add", "value": 1}], state,
    )
    assert out == {"a": 2, "b": 3}
    assert state == {"a": 1, "b": 2}  # 原 state 不被原地修改


def test_apply_effects_chain():
    assert apply_effects(
        [{"variable": "a", "op": "add", "value": 2}, {"variable": "a", "op": "sub", "value": 1}], {"a": 10},
    ) == {"a": 11}


def test_apply_effect_errors():
    with pytest.raises(AppError) as e:
        apply_effect({"variable": "x", "op": "add", "value": 1}, {"y": 0})
    assert e.value.code == "undefined_variable"
    with pytest.raises(AppError) as e:
        apply_effect({"variable": "a", "op": "mul", "value": 1}, {"a": 0})
    assert e.value.code == "invalid_op"
    with pytest.raises(AppError) as e:
        apply_effect({"variable": "a", "op": "add", "value": "x"}, {"a": 0})
    assert e.value.code == "invalid_effect_value"
    with pytest.raises(AppError) as e:
        apply_effect({"variable": "a", "op": "add", "value": 1}, {"a": "str"})
    assert e.value.code == "invalid_effect_value"
    with pytest.raises(AppError) as e:
        apply_effect({"variable": "a", "op": "set", "value": {"k": 1}}, {"a": 0})
    assert e.value.code == "invalid_effect_value"


def test_evaluate_undefined_variable_returns_false():
    # 变量缺失：明确、稳定返回 False（不抛 Python 异常）
    assert evaluate_condition({"variable": "nope", "op": ">=", "value": 1}, {"a": 10}) is False
    # 非数值进行序比较：返回 False（不抛异常）
    assert evaluate_condition({"variable": "a", "op": ">=", "value": 1}, {"a": "text"}) is False


def test_parse_condition_valid_and_invalid():
    c = parse_condition("affection >= 10")
    assert c is not None and c.variable == "affection" and c.op == ">=" and c.value == 10
    assert parse_condition("has_clue == true").value is True
    assert parse_condition("faction == 'A'").value == "A"
    assert parse_condition("affection < 5").op == "<"
    assert parse_condition("x != 3").op == "!="
    assert parse_condition("") is None
    assert parse_condition(None) is None
    assert parse_condition("affection ??? 10") is None
    assert parse_condition("1 >= 2") is None
    assert parse_condition("a + b") is None


# ---------------------------------------------------------------------------
# visible_choices
# ---------------------------------------------------------------------------


def test_visible_choices_filters_by_condition():
    story = _story()
    state = {"affection": 0, "trust": 0, "has_clue": False}
    vis = [c["choice_id"] for c in visible_choices(story, state, "start")]
    assert "c_gain" in vis
    assert "c_high" not in vis        # affection >= 10 不满足 → 不可见
    assert "c_illegal" not in vis     # 非法条件 → 保守隐藏
    # 提高 affection 后，c_high 变为可见
    vis2 = [c["choice_id"] for c in visible_choices(story, {"affection": 15, "trust": 0, "has_clue": False}, "start")]
    assert "c_high" in vis2


def test_visible_choices_node_not_found():
    with pytest.raises(AppError) as e:
        visible_choices(_story(), {}, "nope")
    assert e.value.code == "node_not_found"


# ---------------------------------------------------------------------------
# StateManager
# ---------------------------------------------------------------------------


def test_create_initial_state():
    state = create_initial_state([
        {"name": "a", "type": "number", "initial": 3},
        {"name": "f", "type": "bool", "initial": True},
        {"name": "s", "type": "string", "initial": "hi"},
    ])
    assert state == {"a": 3, "f": True, "s": "hi"}
    assert StateManager.create_initial_state([{"name": "a", "type": "number", "initial": 7}]) == {"a": 7}


def test_state_manager_commit_persists(session_factory):
    session = session_factory()
    project = _seed_project(session, _story())
    ps = PlayerSession(project_id=project.id, current_node_id="start",
                       state={"affection": 0, "trust": 0, "has_clue": False})
    session.add(ps)
    session.commit()

    sm = StateManager(session, ps)
    assert sm.get_state()["affection"] == 0
    sm.apply_effect({"variable": "affection", "op": "add", "value": 5})
    sm.commit()
    session.commit()  # 事务提交（StateManager 已把状态写回 PlayerSession）
    session.expire_all()
    reloaded = session.get(PlayerSession, ps.id)
    assert reloaded.state["affection"] == 5  # commit 是唯一提交入口，已写回持久化
    session.close()


# ---------------------------------------------------------------------------
# PlayerSession（创建 / 获取 / 推进 / merge / ending / trace）
# ---------------------------------------------------------------------------


def test_create_and_get_player_session(session_factory):
    session = session_factory()
    project = _seed_project(session, _story())
    out = create_runtime_session(session, project.id)
    assert out["session_id"]
    assert out["project_id"] == project.id
    assert out["current_node_id"] == "start"
    assert out["state"] == {"affection": 0, "trust": 0, "has_clue": False}
    ps = session.query(PlayerSession).filter(PlayerSession.id == out["session_id"]).first()
    assert ps is not None and ps.current_node_id == "start"
    got = get_runtime_session(session, project.id, out["session_id"])
    assert got["session_id"] == out["session_id"]
    session.close()


def test_choose_applies_effect_and_jumps(session_factory):
    session = session_factory()
    project = _seed_project(session, _story())
    s = create_runtime_session(session, project.id)
    out = choose_choice(session, project.id, s["session_id"], "c_gain")
    assert out["state"]["affection"] == 15      # add 效果生效
    assert out["current_node_id"] == "start2"   # next_node 跳转
    session.close()


def test_choose_condition_not_met_rejected(session_factory):
    session = session_factory()
    project = _seed_project(session, _story())
    s = create_runtime_session(session, project.id)
    with pytest.raises(AppError) as e:
        choose_choice(session, project.id, s["session_id"], "c_high")  # affection=0 < 10
    assert e.value.code == "condition_not_met"
    session.close()


def test_choose_unevaluable_condition_rejected(session_factory):
    session = session_factory()
    project = _seed_project(session, _story())
    s = create_runtime_session(session, project.id)
    with pytest.raises(AppError) as e:
        choose_choice(session, project.id, s["session_id"], "c_illegal")
    assert e.value.code == "unevaluable_condition"
    session.close()


def test_merge_and_ending_nodes(session_factory):
    session = session_factory()
    project = _seed_project(session, _story())
    # merge：c_gain → start2 → c_merge → merge_node（叶子，无选项）
    s1 = create_runtime_session(session, project.id)
    choose_choice(session, project.id, s1["session_id"], "c_gain")
    out = choose_choice(session, project.id, s1["session_id"], "c_merge")
    assert out["current_node_id"] == "merge_node"
    assert runtime_choices(session, project.id, s1["session_id"]) == []
    # ending：c_gain → start2 → c_bad → bad_end；sub/set 效果生效
    s2 = create_runtime_session(session, project.id)
    choose_choice(session, project.id, s2["session_id"], "c_gain")
    out2 = choose_choice(session, project.id, s2["session_id"], "c_bad")
    assert out2["current_node_id"] == "bad_end"
    assert out2["state"]["trust"] == -100  # set
    assert runtime_choices(session, project.id, s2["session_id"]) == []
    session.close()


def test_story_graph_accepts_merge_kind():
    g = StoryGraph.model_validate(_story())
    kinds = {n.kind for n in g.nodes}
    assert "merge" in kinds and "ending" in kinds


def test_runtime_trace_records_choice(session_factory):
    session = session_factory()
    project = _seed_project(session, _story())
    s = create_runtime_session(session, project.id)
    choose_choice(session, project.id, s["session_id"], "c_gain")
    run = session.query(AgentRun).filter(AgentRun.kind == "runtime_choice").first()
    assert run is not None and run.status == "ok"
    step = session.query(AgentStep).filter(
        AgentStep.agent_run_id == run.id, AgentStep.step_key == "choice",
    ).first()
    assert step is not None
    assert step.input_data["session_id"] == s["session_id"]
    assert step.input_data["node_id"] == "start"
    assert step.input_data["choice_id"] == "c_gain"
    assert step.output_data["previous_state"] == {"affection": 0, "trust": 0, "has_clue": False}
    assert step.output_data["applied_effects"] == [{"variable": "affection", "op": "add", "value": 15}]
    assert step.output_data["next_node_id"] == "start2"
    session.close()


# ---------------------------------------------------------------------------
# Runtime API
# ---------------------------------------------------------------------------


def _make_ready(client) -> str:
    created = client.post("/api/director/plan", json={"goal": GOAL}).json()
    assert client.post(f"/api/orchestrate/{created['project_id']}").status_code == 200
    return created["project_id"]


def test_runtime_api_loop(client):
    pid = _make_ready(client)
    resp = client.post(f"/api/projects/{pid}/runtime/sessions")
    assert resp.status_code == 200, resp.text
    s = resp.json()
    assert s["current_node_id"] == "scene_01"
    assert s["state"] == {"affection": 0, "trust": 0}
    sid = s["session_id"]
    # GET session
    got = client.get(f"/api/projects/{pid}/runtime/sessions/{sid}")
    assert got.status_code == 200 and got.json()["session_id"] == sid
    # GET choices
    ch = client.get(f"/api/projects/{pid}/runtime/sessions/{sid}/choices")
    assert ch.status_code == 200
    assert [c["choice_id"] for c in ch.json()] == ["c01a", "c01b", "c01c"]
    # 执行 choice → effect + next_node
    out = client.post(f"/api/projects/{pid}/runtime/sessions/{sid}/choice", json={"choice_id": "c01a"})
    assert out.status_code == 200, out.text
    data = out.json()
    assert data["state"]["affection"] == 10
    assert data["current_node_id"] == "scene_02a"
    # scene_02a 无选项 → []
    ch2 = client.get(f"/api/projects/{pid}/runtime/sessions/{sid}/choices")
    assert ch2.json() == []