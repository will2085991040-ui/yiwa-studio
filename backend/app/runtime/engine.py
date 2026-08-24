"""Story State Runtime 引擎（Step 13）：确定性求值 / 应用，不接触 DB / LLM。

Authoring 与 Runtime 分离的「确定性子系统」：
- evaluate_condition：由确定性代码求值 StoryCondition（变量缺失 → False，绝不泄漏 Python 异常）
- apply_effect / apply_effects：由确定性代码应用 StoryEffect（不修改入参 state，返回新 dict）
- parse_condition：把 Step10/12 旧字符串条件安全解析为结构化 StoryCondition（无法解析 → None，绝不 eval）
- visible_choices：按 Choice.condition 过滤可见选项（无法求值的条件采取保守策略：隐藏）

LLM 不直接接触本模块：它只能产出声明式 StoryEffect/StoryCondition，求值/应用全走这里；
真正的状态「提交」由 StateManager（app/runtime/state.py）独占，本模块本身无副作用。
"""
import re
from typing import Any

from app.core.errors import AppError
from app.schemas.story_graph import StoryCondition

_COND_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*(>=|<=|==|!=|>|<)\s*(.+?)\s*$")


# ---------------------------------------------------------------------------
# 初始状态
# ---------------------------------------------------------------------------


def create_initial_state(variables: list[dict]) -> dict[str, Any]:
    """由 StoryGraph.variables 构建初始 Runtime State（每个变量取其 initial）。"""
    state: dict[str, Any] = {}
    for v in variables or []:
        name = v.get("name")
        if not name:
            continue
        initial = v.get("initial")
        if initial is None:
            initial = _default_initial(v.get("type"))
        state[name] = initial
    return state


def _default_initial(var_type: str | None) -> Any:
    if var_type == "bool":
        return False
    if var_type == "number":
        return 0
    return ""  # string / enum


# ---------------------------------------------------------------------------
# 条件求值
# ---------------------------------------------------------------------------


def evaluate_condition(condition: StoryCondition | dict, state: dict) -> bool:
    """确定性求值一个 StoryCondition。

    变量不在 state 中时返回 False（明确、稳定的兼容行为），绝不抛异常泄漏到上层。
    """
    variable, op, value = _condition_parts(condition)
    if variable not in state:
        return False
    return _compare(state[variable], op, value)


def _condition_parts(condition: StoryCondition | dict) -> tuple[str, str, Any]:
    if isinstance(condition, dict):
        return condition.get("variable"), condition.get("op"), condition.get("value")
    return condition.variable, condition.op, condition.value


def _compare(actual: Any, op: str, expected: Any) -> bool:
    if op in ("==", "!="):
        return _eq(actual, expected) if op == "==" else not _eq(actual, expected)
    # 序关系：需要两侧都是数值（bool 视为非数值）
    if isinstance(actual, bool) or isinstance(expected, bool):
        return False
    if not (_is_number(actual) and _is_number(expected)):
        return False
    if op == ">=":
        return actual >= expected
    if op == "<=":
        return actual <= expected
    if op == ">":
        return actual > expected
    if op == "<":
        return actual < expected
    return False


def _eq(actual: Any, expected: Any) -> bool:
    """严格相等：数字对数字、布尔对布尔、字符串对字符串；跨类型判不等。"""
    if _is_number(actual) and _is_number(expected):
        return actual == expected
    if isinstance(actual, bool) and isinstance(expected, bool):
        return actual is expected
    if isinstance(actual, str) and isinstance(expected, str):
        return actual == expected
    return False


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


# ---------------------------------------------------------------------------
# 条件字符串解析（兼容 Step10/12 旧数据）
# ---------------------------------------------------------------------------


def parse_condition(raw: str | None) -> StoryCondition | None:
    """把旧字符串条件安全解析为结构化 StoryCondition；无法解析返回 None（绝不 eval）。

    支持形如 "affection >= 10" / "has_clue == true" / "faction == 'A'" 的单一表达式。
    """
    if raw is None:
        return None
    text = raw.strip()
    if not text:
        return None
    match = _COND_RE.match(text)
    if match is None:
        return None
    variable, op, value_raw = match.group(1), match.group(2), match.group(3)
    value = _parse_value(value_raw)
    try:
        return StoryCondition(variable=variable, op=op, value=value)
    except ValueError:
        return None


def _parse_value(raw: str) -> Any:
    text = raw.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ("'", '"'):
        return text[1:-1]
    low = text.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    try:
        return float(text) if ("." in text or "e" in low) else int(text)
    except ValueError:
        return text  # 裸标识符按字符串处理


# ---------------------------------------------------------------------------
# 效果应用
# ---------------------------------------------------------------------------


def apply_effect(effect: dict, state: dict) -> dict:
    """应用单个 StoryEffect 到 state，返回「新 state」，绝不修改入参 state。

    未声明变量 / 非法 op / 非法 value 类型 → 抛 AppError（明确错误）。
    """
    if isinstance(effect, dict):
        variable, op, value = effect.get("variable"), effect.get("op"), effect.get("value")
    else:
        variable, op, value = effect.variable, effect.op, effect.value

    if variable not in state:
        raise AppError(f"变量 {variable} 未声明，无法应用效果", code="undefined_variable", status=422)

    current = state[variable]
    if op == "add":
        _require_number(value, "effect.value")
        _require_number(current, f"state[{variable}]")
        new_value = current + value
    elif op == "sub":
        _require_number(value, "effect.value")
        _require_number(current, f"state[{variable}]")
        new_value = current - value
    elif op == "set":
        if not isinstance(value, bool | str | int | float):
            raise AppError("set 的 effect.value 必须是 number|bool|str", code="invalid_effect_value", status=422)
        new_value = value
    else:
        raise AppError(f"非法 effect op {op}", code="invalid_op", status=422)

    new_state = dict(state)
    new_state[variable] = new_value
    return new_state


def apply_effects(effects: list[dict], state: dict) -> dict:
    """依次应用多个 StoryEffect，全程不修改入参 state。"""
    current = dict(state)
    for effect in effects or []:
        current = apply_effect(effect, current)
    return current


def _require_number(value: Any, what: str) -> Any:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise AppError(f"{what} 必须是数值", code="invalid_effect_value", status=422)
    return value


# ---------------------------------------------------------------------------
# 可见选项
# ---------------------------------------------------------------------------


def visible_choices(story_graph: dict, state: dict, node_id: str) -> list[dict]:
    """返回 node 在当前 state 下可见的 choices（condition 为 None/空 → 可见）。

    无法安全解析的字符串条件：保守策略——隐藏（返回 None 的 parse 结果视为不可见），绝不 eval。
    """
    node = _locate_node(story_graph, node_id)
    if node is None:
        raise AppError(f"StoryGraph 中不存在节点 {node_id}", code="node_not_found", status=404)
    result: list[dict] = []
    for choice in node.get("choices", []):
        raw = choice.get("condition")
        if raw is None or (isinstance(raw, str) and raw.strip() == ""):
            result.append(choice)
            continue
        parsed = parse_condition(raw if isinstance(raw, str) else "")
        if parsed is None:
            continue  # 不可求值 → 保守隐藏
        if evaluate_condition(parsed, state):
            result.append(choice)
    return result


def _locate_node(story_graph: dict, node_id: str) -> dict | None:
    return next((n for n in story_graph.get("nodes", []) if n.get("node_id") == node_id), None)