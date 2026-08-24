"""Play Runtime（Step 20）：与 Authoring Runtime 严格分离的游玩运行时。

核心原则：
- LLM 只返回声明式 PlayMutation，绝不直接修改 State；
- 每个 Turn 走 Interpret → Generate Mutation → Validate → Apply → Render → Trace；
- 所有状态变更由确定性代码 apply_mutation 应用，PlayService.turn 原子提交。

世界模型（world JSON）：
  entities    World Entity 列表
  edges       Edge（source/relation/target）
  state       State Slot 列表（entity_id/key/value）
  timeline    Timeline 条目
  evidence    Evidence 条目
"""
import copy

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import PlaySession, PlayTurn
from app.trace.manager import trace_manager

MUTATION_OPS = ("set_slot", "add_entity", "add_edge", "add_evidence", "add_timeline")


def empty_world() -> dict:
    return {"entities": [], "edges": [], "state": [], "timeline": [], "evidence": []}


def _is_primitive(value) -> bool:
    return isinstance(value, bool | str | int | float)


def validate_mutation(mutation, world=None) -> list[str]:
    """确定性校验：返回错误列表（空 = 合法）。"""
    if not isinstance(mutation, dict) or not isinstance(mutation.get("operations"), list):
        return ["mutation 必须是 {operations: [...]}"]
    errors: list[str] = []
    for op in mutation["operations"]:
        if not isinstance(op, dict) or not op.get("op"):
            errors.append("每个操作需要 op 字段")
            continue
        name = op["op"]
        if name not in MUTATION_OPS:
            errors.append(f"未知操作：{name}")
        elif name == "set_slot":
            if not op.get("key"):
                errors.append("set_slot 需要 key")
            if "value" not in op or not _is_primitive(op["value"]):
                errors.append("set_slot 的 value 必须为 number|bool|str")
        elif name == "add_entity":
            if not op.get("entity_id"):
                errors.append("add_entity 需要 entity_id")
        elif name == "add_edge":
            if not op.get("source") or not op.get("relation") or not op.get("target"):
                errors.append("add_edge 需要 source/relation/target")
        elif name == "add_evidence":
            if not op.get("name"):
                errors.append("add_evidence 需要 name")
        elif name == "add_timeline":
            if not op.get("kind"):
                errors.append("add_timeline 需要 kind")
    return errors


def apply_mutation(world: dict, mutation: dict) -> dict:
    """确定性应用 PlayMutation → 新 world（非就地修改原 world）。"""
    new = copy.deepcopy(world or empty_world())
    for op in (mutation or {}).get("operations", []):
        _apply_op(new, op)
    return new


def _apply_op(world: dict, op: dict) -> None:
    name = op["op"]
    if name == "set_slot":
        for slot in world["state"]:
            if slot.get("entity_id") == op.get("entity_id") and slot.get("key") == op["key"]:
                slot["value"] = op["value"]
                return
        world["state"].append({"entity_id": op.get("entity_id"), "key": op["key"], "value": op["value"]})
    elif name == "add_entity":
        entity = {
            "entity_id": op["entity_id"], "entity_type": op.get("entity_type", ""),
            "attributes": op.get("attributes") or {},
        }
        for i, existing in enumerate(world["entities"]):
            if existing.get("entity_id") == op["entity_id"]:
                world["entities"][i] = entity
                return
        world["entities"].append(entity)
    elif name == "add_edge":
        edge = {"source": op["source"], "relation": op["relation"], "target": op["target"]}
        if edge not in world["edges"]:
            world["edges"].append(edge)
    elif name == "add_evidence":
        world["evidence"].append(
            {"name": op["name"], "description": op.get("description", ""), "tags": op.get("tags") or []},
        )
    elif name == "add_timeline":
        world["timeline"].append({"kind": op["kind"], "content": op.get("content"), "meta": op.get("meta") or {}})


def render_world(world: dict) -> str:
    w = world or {}
    entities = ", ".join(e.get("entity_id", "?") for e in w.get("entities", []))
    edges = "; ".join(f"{e['source']}—{e['relation']}→{e['target']}" for e in w.get("edges", []))
    slots = "; ".join(
        f"{(s['entity_id'] + '.') if s.get('entity_id') else ''}{s['key']}={s['value']}" for s in w.get("state", [])
    )
    return (
        f"实体：{entities or '（无）'}\n"
        f"关系：{edges or '（无）'}\n"
        f"状态：{slots or '（无）'}\n"
        f"时间线条目：{len(w.get('timeline', []))}\n"
        f"证据：{len(w.get('evidence', []))}"
    )


def entities_of(world: dict) -> list:
    return (world or {}).get("entities", [])


def edges_of(world: dict) -> list:
    return (world or {}).get("edges", [])


def state_slots_of(world: dict) -> list:
    return (world or {}).get("state", [])


def timeline_of(world: dict) -> list:
    return (world or {}).get("timeline", [])


def evidence_of(world: dict) -> list:
    return (world or {}).get("evidence", [])


class PlayService:
    """Play Runtime 的 DB 编排：创建会话 / 读取世界 / 原子执行 Turn。"""

    def __init__(self, session: Session):
        self.session = session

    def _get_ps(self, session_id: str) -> PlaySession:
        ps = self.session.get(PlaySession, session_id)
        if ps is None:
            raise AppError(f"Play 会话 {session_id} 不存在", code="play_session_not_found", status=404)
        return ps

    def create(self, project_id: str) -> dict:
        ps = PlaySession(project_id=project_id, world=empty_world())
        self.session.add(ps)
        self.session.commit()
        return self._out(ps)

    def get(self, session_id: str) -> dict:
        return self._out(self._get_ps(session_id))

    def _out(self, ps: PlaySession) -> dict:
        return {"id": ps.id, "project_id": ps.project_id, "world": ps.world or {}, "status": ps.status}

    def world_view(self, session_id: str) -> dict:
        world = self._get_ps(session_id).world or {}
        return {
            "entities": entities_of(world), "edges": edges_of(world), "state": state_slots_of(world),
            "timeline": timeline_of(world), "evidence": evidence_of(world),
        }

    def turn(self, session_id: str, *, intent: str = "", mutation: dict) -> dict:
        ps = self._get_ps(session_id)
        world = ps.world or {}
        max_seq = self.session.query(func.max(PlayTurn.seq)).filter(PlayTurn.play_session_id == ps.id).scalar()
        seq = (max_seq or 0) + 1

        run = trace_manager.start_run(
            self.session, kind="play_turn", meta={"play_session_id": ps.id, "seq": seq},
        )
        # Validate（确定性，失败即拒绝，不产生状态变更）
        errors = validate_mutation(mutation, world)
        if errors:
            trace_manager.add_step(
                self.session, run, agent="play", step_key="validate",
                input_data={"mutation": mutation}, output_data={"errors": errors}, status="failed",
            )
            trace_manager.finish_run(run, status="failed")
            self.session.commit()
            raise AppError("；".join(errors), code="play_mutation_invalid", status=422)

        new_world = apply_mutation(world, mutation)
        rendered = render_world(new_world)
        try:
            ps.world = new_world
            turn = PlayTurn(
                play_session_id=ps.id, seq=seq, intent={"text": intent},
                mutation=mutation, result={"rendered": rendered}, status="ok",
            )
            self.session.add(turn)
            trace_manager.add_step(
                self.session, run, agent="play", step_key="apply",
                input_data={"mutation": mutation}, output_data={"rendered": rendered},
            )
            trace_manager.finish_run(run, status="ok")
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise
        return {"turn_id": turn.id, "seq": seq, "world": new_world, "rendered": rendered}


play_service = PlayService