"""媒体生成（生图 / 生视频）类型契约。"""
from pydantic import BaseModel, Field


class MediaError(RuntimeError):
    """媒体生成统一错误（provider、任务失败、超时等）。"""


class ImageRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=2000)
    negative_prompt: str = ""
    size: str = "1024x1024"
    n: int = 1
    ref_image: str | None = None  # 图生图参考图（URL 或 data URI）


class ImageResult(BaseModel):
    provider: str
    model: str
    urls: list[str] = []
    b64: list[str] = []
    latency_ms: int = 0


class VideoRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=4000)
    ref_image: str | None = None
    duration_seconds: int = 5
    aspect_ratio: str = "16:9"


class VideoTask(BaseModel):
    provider: str
    model: str
    task_id: str
    status: str  # queued | running | succeeded | failed


class VideoResult(VideoTask):
    video_url: str = ""
    error: str = ""