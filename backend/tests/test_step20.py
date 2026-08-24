"""Step 20 测试：Play Runtime（声明式 PlayMutation / 确定性 Apply / Turn 生命周期 / 与作者态分离）。"""
import pytest

from app.core.errors import AppError
from app.models import PlayTurn, Project
from app.runtime.play import (
    PlayService,
    apply_mutation,
    empty_world,
    render_world,
    validate_mutation,
)


def _project(session) -> Project:
    project = Project(goal="制作乙女悬疑Galgame。", template="galgame")
    session.add(project)
    session.commit()
    return project


def _mutation(*ops):
    return {"operations": list(ops)}


def test_empty_world(session_factory):
    session = session_factory()
    project = _project(session)
    out = PlayService(session).create(project.id)
    assert out["world"] == empty_world()
    session.close()


def test_validate_mutation_errors():
    assert validate_mutation({}) == ["mutation 必须是 {operations: [...]}"]
    assert any("未知操作" in e for e in validate_mutation(_mutation({"op": "hack"})))
    assert any("value" in e for e in validate_mutation(_mutation({"op": "set_slot", "key": "x", "value": ["a"]})))


def test_validate_mutation_field_errors():
    errs = validate_mutation(_mutation(
        {"op": "set_slot"},                       # 缺 key 且缺 value
        {"op": "add_entity"},
        {"op": "add_edge", "source": "e1"},
        {"op": "add_evidence"},
        {"op": "add_timeline"},
        {"op": "nope"},
    ))
    assert any("key" in e for e in errs)
    assert any("value" in e for e in errs)
    assert any("add_entity" in e for e in errs)
    assert any("add_edge" in e for e in errs)
    assert any("add_evidence" in e for e in errs)
    assert any("add_timeline" in e for e in errs)
    assert any("未知操作" in e for e in errs)


def test_apply_mutation_update_and_replace():
    world = empty_world()
    new = apply_mutation(world, _mutation(
        {"op": "set_slot", "key": "affection", "value": 1},
        {"op": "set_slot", "key": "affection", "value": 2},            # 更新同 slot
        {"op": "set_slot", "entity_id": "e1", "key": "hp", "value": 10},
        {"op": "add_entity", "entity_id": "e1", "entity_type": "character"},
        {"op": "add_entity", "entity_id": "e1", "entity_type": "npc"},  # 替换同名实体
    ))
    slots = {s["key"]: s["value"] for s in new["state"]}
    assert slots["affection"] == 2 and slots["hp"] == 10
    assert new["entities"] == [{"entity_id": "e1", "entity_type": "npc", "attributes": {}}]


def test_apply_mutation_does_not_mutate_input():
    world = empty_world()
    original = empty_world()
    new = apply_mutation(world, _mutation({"op": "set_slot", "key": "affection", "value": 5}))
    assert world == original                # 原 world 不变（LLM/外部无法直接改 State）
    assert new["state"] == [{"entity_id": None, "key": "affection", "value": 5}]


def test_apply_mutation_ops():
    world = empty_world()
    new = apply_mutation(world, _mutation(
        {"op": "add_entity", "entity_id": "e1", "entity_type": "character", "attributes": {"name": "女主"}},
        {"op": "add_edge", "source": "e1", "relation": "loves", "target": "e2"},
        {"op": "add_evidence", "name": "线索A", "description": "天台照片", "tags": ["关键"]},
        {"op": "add_timeline", "kind": "event", "content": "主角告白"},
    ))
    assert new["entities"][0]["entity_id"] == "e1"
    assert new["edges"] == [{"source": "e1", "relation": "loves", "target": "e2"}]
    assert new["evidence"][0]["name"] == "线索A"
    assert new["timeline"][0]["content"] == "主角告白"
    assert "e1" not in render_world(world) and "e1" in render_world(new)


def test_turn_lifecycle(session_factory):
    session = session_factory()
    project = _project(session)
    ps_id = PlayService(session).create(project.id)["id"]
    out = PlayService(session).turn(
        ps_id, intent="选择告白",
        mutation=_mutation({"op": "set_slot", "key": "affection", "value": 10}),
    )
    assert out["seq"] == 1 and "affection=10" in out["rendered"]
    out2 = PlayService(session).turn(
        ps_id, intent="", mutation=_mutation({"op": "add_entity", "entity_id": "e1"}),
    )
    assert out2["seq"] == 2
    turns = session.query(PlayTurn).filter(PlayTurn.play_session_id == ps_id).all()
    assert [t.seq for t in turns] == [1, 2]
    world_view = PlayService(session).world_view(ps_id)
    assert any(e["entity_id"] == "e1" for e in world_view["entities"])
    assert len(world_view["state"]) == 1
    session.close()


def test_invalid_turn_rejected_without_state_change(session_factory):
    session = session_factory()
    project = _project(session)
    ps_id = PlayService(session).create(project.id)["id"]
    with pytest.raises(AppError) as e:
        PlayService(session).turn(ps_id, intent="", mutation=_mutation({"op": "hack"}))
    assert e.value.code == "play_mutation_invalid"
    world_view = PlayService(session).world_view(ps_id)  # 状态未被污染
    assert world_view["entities"] == [] and world_view["state"] == []
    session.close()


def test_play_turn_api(client, session_factory):
    session = session_factory()
    project = _project(session)
    session.close()
    resp = client.post(f"/api/projects/{project.id}/play/sessions")
    assert resp.status_code == 200, resp.text
    sid = resp.json()["id"]
    resp = client.post(
        f"/api/projects/{project.id}/play/sessions/{sid}/turn",
        json={"intent": "询问线索", "mutation": {"operations": [{"op": "add_evidence", "name": "旧钥匙"}]}},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["seq"] == 1 and "证据：1" in resp.json()["rendered"]


def test_play_not_found(session_factory):
    session = session_factory()
    with pytest.raises(AppError) as e:
        PlayService(session).get("no-such-session")
    assert e.value.code == "play_session_not_found"
    session.close()