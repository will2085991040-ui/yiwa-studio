"""StateManager（Step 13）：Runtime State 的唯一提交入口。

职责边界：
- 持有权威 state 的「一份副本」，绝不就地修改外部传入的 dict
- 所有 StoryEffect 必须经由 apply_effect / apply_effects 落地（亦不允许 Agent/API 直接写状态）
- commit() 是唯一把 state 写回 PlayerSession 持久化的地方

其余确定性逻辑（求值/应用/可见选项）全部下沉到 app/runtime/engine.py。
"""
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import PlayerSession
from app.runtime.engine import apply_effect, apply_effects, create_initial_state, evaluate_condition, visible_choices


class StateManager:
    def __init__(self, session: Session, player_session: PlayerSession):
        self._db = session
        self._ps = player_session
        self._state: dict = dict(player_session.state or {})

    @staticmethod
    def create_initial_state(variables: list[dict]) -> dict:
        return create_initial_state(variables)

    def get_state(self) -> dict:
        return dict(self._state)

    def evaluate_condition(self, condition) -> bool:
        return evaluate_condition(condition, self._state)

    def apply_effect(self, effect: dict) -> dict:
        self._state = apply_effect(effect, self._state)
        return dict(self._state)

    def apply_effects(self, effects: list[dict]) -> dict:
        self._state = apply_effects(effects, self._state)
        return dict(self._state)

    def set_state_value(self, name: str, value) -> dict:
        """仅供 Runtime 保留键（如小游戏结果）写入；普通 StoryEffect 仍走 apply_effect 声明校验。"""
        if not isinstance(value, bool | str | int | float):
            raise AppError(
                f"保留键 {name} 的值类型非法（只能为 number|bool|str）", code="invalid_state_value", status=500
            )
        self._state[name] = value
        return dict(self._state)

    def get_visible_choices(self, story_graph: dict, node_id: str) -> list[dict]:
        return visible_choices(story_graph, self._state, node_id)

    def commit(self) -> dict:
        """唯一提交点：校验后把副本写回 PlayerSession。"""
        self._validate()
        self._ps.state = dict(self._state)
        return dict(self._state)

    def _validate(self) -> None:
        for name, value in self._state.items():
            if not isinstance(value, bool | str | int | float):
                raise AppError(
                    f"变量 {name} 的值类型非法（只能为 number|bool|str）",
                    code="invalid_state_value", status=500,
                )