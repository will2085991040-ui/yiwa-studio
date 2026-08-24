"""小游戏协议（增量：Funloom 蒸馏 · Phase 4）。

吸收 Funloom 的 minigame 节点 + `postMessage` 结果协议：
- 小游戏运行在 iframe 中，完成时向父页发送 `funloom:minigame:complete`
- 父页（Runtime）收到后调用 `POST .../runtime/sessions/{sid}/minigame-result` 落状态
- 结果写入保留状态键 `_last_minigame`（success|perfect）与 `_last_minigame_score`
仅协议数据结构 + 纯函数；Runtime 集成在 app/api/v1/minigame.py。
"""
from typing import Literal

from pydantic import BaseModel, Field

MINIGAME_COMPLETE_TYPE = "funloom:minigame:complete"
MinigameResult = Literal["success", "perfect"]
MINIGAME_RESULTS: list[str] = ["success", "perfect"]

RESULT_STATE_KEY = "_last_minigame"        # 最近一次小游戏结果（success|perfect）
SCORE_STATE_KEY = "_last_minigame_score"   # 最近一次小游戏得分（number）


class MinigameConfig(BaseModel):
    """剧情节点上的小游戏配置。玩家通过小游戏后，用节点 choices 继续推进（可条件分支）。"""

    game_id: str = Field(min_length=1, max_length=80, description="小游戏类型/ID（对应 iframe 路由）")
    game_url: str = Field(default="", max_length=800, description="iframe 地址；空则用内置演示")
    title: str = Field(default="", max_length=120)
    description: str = Field(default="", max_length=500)
    success_result: MinigameResult = Field(default="success", description="最低通过结果")
    score_variable: str | None = Field(default=None, max_length=80, description="可选：把得分写入该故事变量")
    settings: dict = Field(default_factory=dict, description="游戏参数：target/time_limit_s/grid 等（内置小游戏读取）")


class MinigameResultInput(BaseModel):
    """Runtime 接到 iframe postMessage 后提交的结果。"""

    game_id: str = Field(default="", max_length=80)
    result: MinigameResult
    score: int | None = Field(default=None, ge=0)


def minigame_protocol() -> dict:
    """返回协议说明（message type / results / 保留状态键），供前端 iframe 与 Runtime 清单化引用。"""
    return {
        "message_type": MINIGAME_COMPLETE_TYPE,
        "message": {
            "type": MINIGAME_COMPLETE_TYPE,
            "gameId": "string",
            "result": "success|perfect",
            "score": "number (optional)",
        },
        "results": MINIGAME_RESULTS,
        "reserved_state_keys": [RESULT_STATE_KEY, SCORE_STATE_KEY],
    }