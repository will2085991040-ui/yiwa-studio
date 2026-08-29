"""开放世界 / 分支试玩 Play（增量：InkOS 互动影游核心 · 干净移植）。

按 InkOS 的「实体-关系-状态槽-证据」世界图模型，用 YIWA 技术栈（Pydantic）重写：
- 世界图 = entities + edges（带时间有效性）+ state_slots + events（回合）
- 每回合模型产出 PlayMutation（upsert/expire + 证据状态推进），确定性 reducer 落图
- reducer 语义：fail-open（悬空关系边跳过不整体失败）、玩家实体 id 归一、边端点标签别名解析、
  证据状态单向推进（不可回退）、关系边 holding→observed 归一、数值状态槽钳制 [min,max]
"""
from typing import Any, Literal

from pydantic import BaseModel, Field

PlayActionKind = Literal["look", "say", "move", "do", "wait"]
PlayEntityType = Literal[
    "actor", "location", "item", "evidence", "clue", "claim", "proof_chain",
    "organization", "rule", "scene", "event",
]
PlayStateSlotKind = Literal["resource", "relation", "pressure", "clue", "evidence", "flag", "timer"]
PlayEvidenceStatus = Literal[
    "unknown", "hinted", "seen", "collected", "verified", "weaponized", "exposed", "exhausted",
]

EVIDENCE_ORDER: tuple[str, ...] = (
    "unknown", "hinted", "seen", "collected", "verified", "weaponized", "exposed", "exhausted",
)
PLAYER_ENTITY_ID = "actor_player"
_LEGACY_PLAYER_IDS = {"player"}


class PlayEntity(BaseModel):
    id: str = Field(min_length=1, max_length=80)
    type: PlayEntityType
    label: str = Field(min_length=1, max_length=200)
    summary: str = Field(default="", max_length=1000)
    status: str = Field(default="", max_length=80)
    created_event_id: str | None = Field(default=None, max_length=80)
    updated_event_id: str | None = Field(default=None, max_length=80)


class PlayEdge(BaseModel):
    id: str = Field(min_length=1, max_length=120)
    from_id: str = Field(min_length=1, max_length=80)
    type: str = Field(min_length=1, max_length=80)
    to_id: str = Field(min_length=1, max_length=80)
    value: dict[str, Any] = Field(default_factory=dict)
    valid_from_event_id: str = Field(min_length=1, max_length=80)
    valid_until_event_id: str | None = Field(default=None, max_length=80)
    source_event_id: str = Field(min_length=1, max_length=80)
    visibility: dict[str, str] = Field(default_factory=dict)
    strength: float | None = Field(default=None)
    confidence: float | None = Field(default=None)


class EdgeExpire(BaseModel):
    edge_id: str = Field(min_length=1, max_length=120)
    valid_until_event_id: str = Field(min_length=1, max_length=80)
    reason: str = Field(default="", max_length=500)


class PlayStateSlot(BaseModel):
    id: str = Field(min_length=1, max_length=120)
    owner_entity_id: str | None = Field(default=None, max_length=80)
    kind: PlayStateSlotKind
    label: str = Field(min_length=1, max_length=200)
    value: Any = None
    updated_event_id: str = Field(min_length=1, max_length=80)


class PlayTimeAdvance(BaseModel):
    elapsed: str = Field(default="", max_length=200)
    anchor: str = Field(default="", max_length=200)
    rationale: str = Field(default="", max_length=500)
    synchronized: list[str] = Field(default_factory=list)


class PlayEvidenceTransition(BaseModel):
    entity_id: str = Field(min_length=1, max_length=80)
    from_: PlayEvidenceStatus | None = Field(default=None)
    to: PlayEvidenceStatus
    reason: str = Field(default="", max_length=500)


class PlayEvent(BaseModel):
    id: str = Field(min_length=1, max_length=80)
    turn: int = Field(ge=0)
    action_kind: PlayActionKind
    raw_input: str = Field(min_length=1, max_length=4000)
    outcome_summary: str = Field(default="", max_length=2000)
    time_advance: PlayTimeAdvance | None = None
    created_at: str = Field(default="", max_length=40)


class PlayActionIntent(BaseModel):
    """每回合玩家动作的结构化意图（模型输出，宽容解析）。"""

    action_kind: PlayActionKind = "do"
    target_entity_label: str | None = None
    target_location_label: str | None = None
    intent: str = ""
    manner: str = ""
    risk: str = ""
    ambiguity: str = ""
    secondary_actions: list[str] = Field(default_factory=list)


class EntitiesMutation(BaseModel):
    upsert: list[PlayEntity] = Field(default_factory=list)


class EdgesMutation(BaseModel):
    upsert: list[PlayEdge] = Field(default_factory=list)
    expire: list[EdgeExpire] = Field(default_factory=list)


class StateSlotsMutation(BaseModel):
    upsert: list[PlayStateSlot] = Field(default_factory=list)


class EvidenceMutation(BaseModel):
    transitions: list[PlayEvidenceTransition] = Field(default_factory=list)


class PlayMutation(BaseModel):
    """一回合的世界图变更：模型产出，reducer 确定性落地。"""

    event_id: str = Field(min_length=1, max_length=80)
    turn: int = Field(default=0, ge=0)
    action_kind: PlayActionKind = "do"
    summary: str = Field(default="", max_length=2000)
    time_advance: PlayTimeAdvance | None = None
    entities: EntitiesMutation = Field(default_factory=EntitiesMutation)
    edges: EdgesMutation = Field(default_factory=EdgesMutation)
    state_slots: StateSlotsMutation = Field(default_factory=StateSlotsMutation)
    evidence: EvidenceMutation = Field(default_factory=EvidenceMutation)
    blocked: bool = False
    blocked_reason: str = Field(default="", max_length=1000)
    notes: list[str] = Field(default_factory=list)


class PlayWorld(BaseModel):
    """一个 play 会话的完整世界图快照。"""

    kind: Literal["open_world", "branching"] = "open_world"
    title: str = Field(default="", max_length=200)
    turn: int = Field(default=0, ge=0)
    entities: list[PlayEntity] = Field(default_factory=list)
    edges: list[PlayEdge] = Field(default_factory=list)
    state_slots: list[PlayStateSlot] = Field(default_factory=list)
    events: list[PlayEvent] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 确定性 reducer（纯函数，无 DB 副作用）
# ---------------------------------------------------------------------------


def _evidence_rank(status: str) -> int:
    return EVIDENCE_ORDER.index(status) if status in EVIDENCE_ORDER else 0


def _canonicalize(entity_id: str) -> str:
    return PLAYER_ENTITY_ID if entity_id.strip() in _LEGACY_PLAYER_IDS else entity_id


def _build_alias_map(world: PlayWorld, turn_entities: list[PlayEntity]) -> dict[str, str]:
    aliases: dict[str, str] = {}
    ambiguous: set[str] = set()

    def add(alias: str | None, entity_id: str | None) -> None:
        a = (alias or "").strip()
        eid = (entity_id or "").strip()
        if not a or not eid:
            return
        existing = aliases.get(a)
        if existing and existing != eid:
            ambiguous.add(a)
            aliases.pop(a, None)
            return
        if a not in ambiguous:
            aliases[a] = eid

    for e in world.entities:
        add(e.id, e.id)
        add(e.label, e.id)
    for e in turn_entities:
        add(e.id, e.id)
        add(e.label, e.id)
    return aliases


def _is_record(value: Any) -> bool:
    return isinstance(value, dict)


def _current_evidence_status(world: PlayWorld, entity_id: str) -> str:
    for slot in world.state_slots:
        if slot.owner_entity_id != entity_id:
            continue
        if slot.id == f"evidence:{entity_id}:status" or slot.kind == "evidence":
            if _is_record(slot.value) and slot.value.get("status") in EVIDENCE_ORDER:
                return slot.value["status"]
    return "unknown"


def _normalize_state_slot(slot: PlayStateSlot) -> PlayStateSlot:
    if not _is_record(slot.value):
        return slot
    current = slot.value.get("current")
    if not isinstance(current, int | float) or isinstance(current, bool):
        return slot
    low = slot.value.get("min")
    high = slot.value.get("max")
    next_value = current
    if isinstance(low, int | float) and not isinstance(low, bool):
        next_value = max(low, next_value)
    if isinstance(high, int | float) and not isinstance(high, bool):
        next_value = min(high, next_value)
    if next_value == current:
        return slot
    return slot.model_copy(update={"value": {**slot.value, "current": next_value}})


def _normalize_holding_edge(edge: PlayEdge, target: PlayEntity | None) -> PlayEdge:
    if not _is_record(edge.value) or edge.value.get("role") != "holding":
        return edge
    if target is None:
        return edge
    if target.type == "item":
        return edge
    physical = edge.value.get("physical") is True or edge.value.get("portable") is True
    if physical and target.type in ("evidence", "clue", "claim", "proof_chain"):
        return edge
    return edge.model_copy(update={"value": {**edge.value, "role": "observed"}})


def apply_play_mutation(
    world: PlayWorld, mutation: PlayMutation, raw_input: str, created_at: str | None = None
) -> dict:
    """把一回合 PlayMutation 落到世界图，返回 {world, event, blocked}。

    语义（与 InkOS 对齐）：
    - 玩家实体 id 归一（player → actor_player，边端点同步）
    - 边端点按「标签/旧 id」别名解析到实体 id
    - 证据状态单向推进；悬空关系边 fail-open（跳过，不整体失败）
    """
    # 1) 归一玩家 id
    entities = [
        PlayEntity(**{**e.model_dump(), "id": _canonicalize(e.id)}) for e in mutation.entities.upsert
    ]
    edges_upsert = [
        PlayEdge(**{**e.model_dump(), "from_id": _canonicalize(e.from_id), "to_id": _canonicalize(e.to_id)})
        for e in mutation.edges.upsert
    ]
    state_slots = [
        PlayStateSlot(**{
            **s.model_dump(),
            "owner_entity_id": _canonicalize(s.owner_entity_id) if s.owner_entity_id else None,
        })
        for s in mutation.state_slots.upsert
    ]
    normalized = mutation.model_copy(update={
        "entities": EntitiesMutation(upsert=entities),
        "edges": EdgesMutation(upsert=edges_upsert, expire=mutation.edges.expire),
        "state_slots": StateSlotsMutation(upsert=state_slots),
    })

    # 2) 边端点标签/别名解析
    if normalized.edges.upsert:
        aliases = _build_alias_map(world, normalized.entities.upsert)
        resolved = [
            PlayEdge(**{
                **e.model_dump(),
                "from_id": aliases.get(e.from_id, e.from_id),
                "to_id": aliases.get(e.to_id, e.to_id),
            })
            for e in normalized.edges.upsert
        ]
        normalized = normalized.model_copy(update={
            "edges": EdgesMutation(upsert=resolved, expire=normalized.edges.expire),
        })

    # 3) 校验（证据单向、槽引用存在）
    upserted_ids = {e.id for e in normalized.entities.upsert}
    entity_by_id = {e.id: e for e in list(world.entities) + normalized.entities.upsert}

    def _exists(entity_id: str) -> bool:
        return entity_id in upserted_ids or any(e.id == entity_id for e in world.entities)

    for slot in normalized.state_slots.upsert:
        if slot.owner_entity_id and not _exists(slot.owner_entity_id):
            raise ValueError(f"Play mutation 引用不存在的实体（state slot {slot.id}）：{slot.owner_entity_id}")

    for tr in normalized.evidence.transitions:
        entity = entity_by_id.get(tr.entity_id)
        if entity is None:
            raise ValueError(f"Play evidence transition 引用不存在的实体：{tr.entity_id}")
        if entity.type not in ("evidence", "clue"):
            raise ValueError(f"Play evidence transition 需要 evidence/clue 实体：{tr.entity_id}")
        current = _current_evidence_status(world, tr.entity_id)
        if tr.from_ is not None and tr.from_ != current:
            raise ValueError(f"证据状态期望 {tr.from_} 但当前是 {current}")
        if _evidence_rank(tr.to) < _evidence_rank(current):
            raise ValueError(f"证据状态不能从 {current} 回退到 {tr.to}")

    # 4) 记录事件
    event = PlayEvent(
        id=normalized.event_id,
        turn=normalized.turn,
        action_kind=normalized.action_kind,
        raw_input=raw_input,
        outcome_summary=normalized.summary or normalized.blocked_reason,
        time_advance=normalized.time_advance,
        created_at=created_at or "",
    )

    if normalized.blocked:
        new_world = world.model_copy(update={"events": [*world.events, event], "turn": max(world.turn, event.turn)})
        return {"world": new_world, "event": event, "blocked": True}

    # 5) 落地变更
    world_entities = list(world.entities)
    for e in normalized.entities.upsert:
        world_entities = [x for x in world_entities if x.id != e.id] + [e]

    world_edges = list(world.edges)
    for exp in normalized.edges.expire:
        world_edges = [
            e.model_copy(update={"valid_until_event_id": exp.valid_until_event_id})
            if e.id == exp.edge_id else e
            for e in world_edges
        ]
    for e in normalized.edges.upsert:
        if _exists(e.from_id) and _exists(e.to_id):
            target = next((x for x in normalized.entities.upsert if x.id == e.to_id), None) or next(
                (x for x in world.entities if x.id == e.to_id), None
            )
            world_edges = [x for x in world_edges if x.id != e.id] + [_normalize_holding_edge(e, target)]

    world_slots = list(world.state_slots)
    for s in normalized.state_slots.upsert:
        world_slots = [x for x in world_slots if x.id != s.id] + [_normalize_state_slot(s)]

    for tr in normalized.evidence.transitions:
        slot = PlayStateSlot(
            id=f"evidence:{tr.entity_id}:status",
            owner_entity_id=tr.entity_id,
            kind="evidence",
            label="证据状态",
            value={
                "previous": _current_evidence_status(world, tr.entity_id),
                "status": tr.to,
                "reason": tr.reason,
            },
            updated_event_id=normalized.event_id,
        )
        world_slots = [x for x in world_slots if x.id != slot.id] + [slot]

    new_world = PlayWorld(
        kind=world.kind,
        title=world.title,
        turn=max(world.turn, event.turn),
        entities=world_entities,
        edges=world_edges,
        state_slots=world_slots,
        events=[*world.events, event],
    )
    return {"world": new_world, "event": event, "blocked": False}


def new_world(kind: str = "open_world", title: str = "") -> PlayWorld:
    return PlayWorld(kind=kind, title=title)