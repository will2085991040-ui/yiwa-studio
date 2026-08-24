"""增量：增强世界图试玩（InkOS 互动影游核心 · 干净移植）测试。"""
import pytest

from app.models import Project
from app.schemas.play import (
    EdgesMutation,
    EntitiesMutation,
    EvidenceMutation,
    PlayEdge,
    PlayEntity,
    PlayEvidenceTransition,
    PlayMutation,
    PlayStateSlot,
    PlayWorld,
    StateSlotsMutation,
    apply_play_mutation,
)


def _project(session) -> Project:
    project = Project(goal="剧本杀试试玩", template="galgame")
    session.add(project)
    session.commit()
    return project


def test_player_entity_id_canonicalized():
    world = PlayWorld()
    m = PlayMutation(
        event_id="e1", turn=1,
        entities=EntitiesMutation(upsert=[PlayEntity(id="player", type="actor", label="玩家")]),
    )
    result = apply_play_mutation(world, m, "开始")
    assert result["world"].entities[0].id == "actor_player"


def test_edge_endpoint_label_alias_resolved():
    world = PlayWorld(entities=[PlayEntity(id="char_lin", type="actor", label="林烬")])
    m = PlayMutation(
        event_id="e1", turn=1,
        entities=EntitiesMutation(upsert=[PlayEntity(id="knife", type="item", label="匕首")]),
        edges=EdgesMutation(upsert=[
            PlayEdge(id="e", from_id="char_lin", type="持有", to_id="匕首",
                     valid_from_event_id="e1", source_event_id="e1"),
        ]),
    )
    result = apply_play_mutation(world, m, "林烬拿起匕首")
    assert result["world"].edges[0].to_id == "knife"


def test_evidence_status_monotonic_and_no_regression():
    world = PlayWorld(entities=[PlayEntity(id="ev1", type="evidence", label="血衣")])
    m1 = PlayMutation(
        event_id="e1", turn=1,
        evidence=EvidenceMutation(transitions=[
            PlayEvidenceTransition(entity_id="ev1", to="collected", reason="拾取"),
        ]),
    )
    r1 = apply_play_mutation(world, m1, "收集血衣")
    slot = next(s for s in r1["world"].state_slots if s.owner_entity_id == "ev1")
    assert slot.value["status"] == "collected"

    m2 = PlayMutation(
        event_id="e2", turn=2,
        evidence=EvidenceMutation(transitions=[PlayEvidenceTransition(entity_id="ev1", to="seen")]),
    )
    with pytest.raises(ValueError, match="不能从 collected 回退到 seen"):
        apply_play_mutation(r1["world"], m2, "试图回退")


def test_holding_edge_normalized_for_non_physical():
    world = PlayWorld(entities=[PlayEntity(id="actor_player", type="actor", label="玩家")])
    m = PlayMutation(
        event_id="e1", turn=1,
        entities=EntitiesMutation(upsert=[PlayEntity(id="c1", type="claim", label="证词")]),
        edges=EdgesMutation(upsert=[
            PlayEdge(id="e", from_id="actor_player", type="掌握", to_id="c1",
                     value={"role": "holding"}, valid_from_event_id="e1", source_event_id="e1"),
        ]),
    )
    result = apply_play_mutation(world, m, "记录证词")
    assert result["world"].edges[0].value["role"] == "observed"


def test_state_slot_value_clamped():
    world = PlayWorld()
    m = PlayMutation(
        event_id="e1", turn=1,
        state_slots=StateSlotsMutation(upsert=[
            PlayStateSlot(id="hp", kind="resource", label="体力",
                          value={"current": 120, "min": 0, "max": 100}, updated_event_id="e1"),
        ]),
    )
    result = apply_play_mutation(world, m, "加体力")
    assert result["world"].state_slots[0].value["current"] == 100


def test_blocked_turn_records_event_without_changes():
    world = PlayWorld()
    m = PlayMutation(
        event_id="e1", turn=1, blocked=True, blocked_reason="不许动手",
        entities=EntitiesMutation(upsert=[PlayEntity(id="x", type="item", label="X")]),
    )
    result = apply_play_mutation(world, m, "尝试")
    assert result["blocked"] is True
    assert result["world"].entities == []
    assert result["event"].outcome_summary == "不许动手"
    assert len(result["world"].events) == 1


def test_dangling_edge_skipped_not_fatal():
    world = PlayWorld()
    m = PlayMutation(
        event_id="e1", turn=1,
        edges=EdgesMutation(upsert=[
            PlayEdge(id="e", from_id="ghost_a", type="相关", to_id="ghost_b",
                     valid_from_event_id="e1", source_event_id="e1"),
        ]),
    )
    result = apply_play_mutation(world, m, "引用缺失实体")
    assert result["world"].edges == []  # fail-open：跳过，不报错


def test_api_start_step_list(client, session_factory):
    session = session_factory()
    project = _project(session)
    session.close()

    resp = client.post(f"/api/projects/{project.id}/worldplay/start", json={"kind": "open_world", "title": "档案室"})
    assert resp.status_code == 200, resp.text
    play_id = resp.json()["play_id"]

    step = {
        "raw_input": "查看档案",
        "mutation": {
            "event_id": "e1", "turn": 1, "action_kind": "look",
            "entities": {"upsert": [{"id": "room", "type": "location", "label": "档案室"}]},
            "edges": {"upsert": [], "expire": []},
            "state_slots": {"upsert": []},
            "evidence": {"transitions": []},
        },
    }
    resp = client.post(f"/api/projects/{project.id}/worldplay/{play_id}/step", json=step)
    assert resp.status_code == 200, resp.text
    assert resp.json()["version"] == 2
    assert any(e["type"] == "location" for e in resp.json()["world"]["entities"])

    resp = client.get(f"/api/projects/{project.id}/worldplay/{play_id}")
    assert resp.json()["world"]["turn"] == 1

    resp = client.get(f"/api/projects/{project.id}/worldplay")
    assert any(p["play_id"] == play_id for p in resp.json())


def test_step_invalid_evidence_422(client, session_factory):
    session = session_factory()
    project = _project(session)
    session.close()

    play_id = client.post(f"/api/projects/{project.id}/worldplay/start", json={"kind": "branching"}).json()["play_id"]
    # evidence transition 指向不存在的实体 → 422
    step = {
        "raw_input": "标记",
        "mutation": {
            "event_id": "e1", "turn": 1,
            "evidence": {"transitions": [{"entity_id": "nope", "to": "collected"}]},
        },
    }
    resp = client.post(f"/api/projects/{project.id}/worldplay/{play_id}/step", json=step)
    assert resp.status_code == 422