"""Storyboard 分镜 + 视频生成（增量：Funloom 蒸馏 · Phase 3）。

吸收 Funloom 的「剧情节点 → AI 拆镜 → Seedance 视频」模型：
- Shot：景别 / 运镜 / 逐字对白 / 动作 / 情绪 / 光照 / 音效 / 衔接 / 提示词
- VideoJob：时长定价（10 积分/秒）＋ Seedance 导演提示词
仅数据 + 确定性纯函数（mock 拆镜 / 提示词合成），服务层与 API 直接复用。
"""
from typing import Literal

from pydantic import BaseModel, Field, model_validator

SHOT_SIZES = ["大远景", "远景", "全景", "中景", "中近景", "近景", "特写", "大特写"]
CAMERA_MOVEMENTS = ["固定镜头", "缓慢推近", "缓慢拉远", "水平平移", "跟随移动", "环绕运镜", "手持摇晃", "升降镜头"]
LINK_MODES = ["new_clip", "auto"]
COST_PER_SECOND = 10
DEFAULT_SHOT_DURATION = 4

ShotStatus = Literal["draft", "ready"]
VideoStatus = Literal["queued", "done", "failed"]


class Shot(BaseModel):
    """一个分镜镜头。"""

    shot_no: int = Field(ge=1)
    duration_sec: float = Field(default=DEFAULT_SHOT_DURATION, ge=1, le=30)
    scene_id: str = Field(default="", max_length=220)
    character_ids: list[str] = Field(default_factory=list)
    visual_description: str = Field(default="", max_length=600, description="画面描述")
    shot_size: str = Field(default="中景", max_length=40)
    camera_movement: str = Field(default="固定镜头", max_length=40)
    character_action: str = Field(default="", max_length=300)
    emotion: str = Field(default="", max_length=200)
    lighting: str = Field(default="", max_length=200)
    sound_effect: str = Field(default="", max_length=200, description="环境音/音效")
    dialogue: str = Field(default="", max_length=1000, description="逐字对白（与口型对齐）")
    generate_audio: bool = Field(default=True)
    storyboard_prompt: str = Field(default="", max_length=1200)
    motion_prompt: str = Field(default="", max_length=500, description="运镜/动效提示词")
    link_from_previous: str = Field(default="new_clip", max_length=20)
    status: ShotStatus = "draft"


class Storyboard(BaseModel):
    """某剧情节点的分镜表。"""

    node_id: str = Field(min_length=1, max_length=80)
    synopsis: str = Field(default="", max_length=800)
    shots: list[Shot] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def _shot_no_unique(self) -> "Storyboard":
        nos = [s.shot_no for s in self.shots]
        if len(nos) != len(set(nos)):
            raise ValueError("shot_no 不能重复")
        return self


class VideoJob(BaseModel):
    """一次视频生成任务（mock：确定性计价 + 状态）。"""

    job_id: str = Field(min_length=1, max_length=80)
    node_id: str = Field(min_length=1, max_length=80)
    status: VideoStatus = "queued"
    duration_sec: float = Field(ge=0)
    cost_per_second: int = COST_PER_SECOND
    total_cost: int = Field(ge=0)
    seedance_director_prompt: str = Field(default="", max_length=4000)
    task_id: str = Field(default="", max_length=160)
    video_url: str = Field(default="", max_length=2000)
    provider: str = Field(default="mock", max_length=40)
    aspect_ratio: str = Field(default="16:9", max_length=10, description="16:9 横屏 / 9:16 竖屏")
    error: str = Field(default="", max_length=2000, description="失败原因（厂商返回的真实错误文案）")


def storyboard_template() -> dict:
    return {
        "shot_sizes": SHOT_SIZES,
        "camera_movements": CAMERA_MOVEMENTS,
        "link_modes": LINK_MODES,
        "cost_per_second": COST_PER_SECOND,
        "default_shot_duration": DEFAULT_SHOT_DURATION,
    }


def storyboard_json_schema() -> dict:
    """StoryboardAgent 的结构化输出 JSON Schema（供 LLM 按 Schema 生成分镜）。"""
    return Storyboard.model_json_schema()


def compose_shot_prompt(shot: Shot, character_identity: str = "") -> str:
    """合成单镜提示词（画面 + 景别 + 运镜 + 动作 + 情绪 + 光照 + 对白 + 音效）。"""
    parts: list[str] = []
    if shot.visual_description.strip():
        parts.append(f"画面：{shot.visual_description.strip()}")
    parts.append(f"景别：{shot.shot_size}，运镜：{shot.camera_movement}")
    if shot.character_action.strip():
        parts.append(f"动作：{shot.character_action.strip()}")
    if shot.character_ids:
        parts.append("人物身份：脸型/外貌/服装/气质与角色卡完全一致，严禁换脸或换装")
    if shot.emotion.strip():
        parts.append(f"情绪：{shot.emotion.strip()}")
    if shot.lighting.strip():
        parts.append(f"光照：{shot.lighting.strip()}")
    if shot.dialogue.strip():
        parts.append(f"对白（逐字）：{shot.dialogue.strip()}")
    if shot.sound_effect.strip():
        parts.append(f"音效：{shot.sound_effect.strip()}")
    text = "\n".join(parts)
    return f"{character_identity.strip()}\n\n{text}" if character_identity.strip() else text


def compose_character_identity(cards: list[dict]) -> str:
    """把角色卡的确定性外貌描述拼成「身份一致性锁」，供画面/提示/视频复用。

    当角色卡给出非空 appearance 时，回到固定中文身份块逐条锁定外貌/服装/气质，
    让长链路里每一个镜头都不换脸换装。cards 形如
    [{"character_id": "char-01", "name": …, "appearance": …}, {"…"}…]。
    """
    lines: list[str] = []
    for card in cards or []:
        appr = (card or {}).get("appearance") or ""
        if not appr.strip():
            continue
        cid = (card or {}).get("character_id") or "char"
        name = (card or {}).get("name") or cid
        lines.append(f"[身份一致] {name}({cid}) 外貌：{appr.strip()}")
    if not lines:
        return ""
    return "角色身份一致性锁定：" + " | ".join(lines)


def compose_seedance_prompt(storyboard: Storyboard, character_identity: str = "") -> str:
    """Seedance 导演提示词：整段分镜合成为连续视频，并保留角色身份一致。"""
    lines = ["将以下分镜制作为连续视频，保持同一角色身份、画风与运镜连续："]
    if character_identity.strip():
        lines.append(character_identity.strip())
    for s in storyboard.shots:
        lines.append(f"[镜{s.shot_no}｜{s.duration_sec}s｜{s.link_from_previous}] {compose_shot_prompt(s)}")
    lines.append("对白必须与画面口型逐字对齐，画面中不得出现字幕与 Logo。")
    return "\n".join(lines)


def auto_breakdown(node_id: str, synopsis: str, requested_shots: int = 4) -> Storyboard:
    """确定性 mock 拆镜：按 synopsis 生成 requested_shots 个草稿镜头（离线可用）。"""
    count = max(1, min(requested_shots or 4, 12))
    shots: list[Shot] = []
    for i in range(count):
        shots.append(
            Shot(
                shot_no=i + 1,
                duration_sec=DEFAULT_SHOT_DURATION,
                visual_description=f"{synopsis.strip() or '剧情'} · 第 {i + 1} 个镜头",
                shot_size=SHOT_SIZES[(i * 2) % len(SHOT_SIZES)],
                camera_movement=CAMERA_MOVEMENTS[i % len(CAMERA_MOVEMENTS)],
                link_from_previous="auto" if i else "new_clip",
                status="draft",
            )
        )
    return Storyboard(node_id=node_id, synopsis=synopsis, shots=shots)