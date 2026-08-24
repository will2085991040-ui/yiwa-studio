"""增量：生图/生视频媒体层（真实厂商 + mock 回退）测试。"""
import asyncio

import httpx
import pytest

from app.core.config import settings
from app.media import images as images_mod
from app.media import video as video_mod
from app.media.images import generate_image
from app.media.types import ImageRequest, MediaError, VideoRequest
from app.media.video import generate_video, poll_video, submit_video


class _Resp:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self.text = ""
        self._payload = payload

    def json(self) -> dict:
        return self._payload


class _FakeImagesClient:
    def __init__(self, *args, **kwargs): ...

    async def __aenter__(self): return self

    async def __aexit__(self, *args): ...

    async def post(self, url, **kwargs):
        return _Resp(200, {"data": [{"url": "https://img.example/x.png"}]})


class _FakeVideoClient:
    def __init__(self, *args, **kwargs): ...

    async def __aenter__(self): return self

    async def __aexit__(self, *args): ...

    async def post(self, url, **kwargs):
        return _Resp(200, {"id": "cgt-1"})

    async def get(self, url, **kwargs):
        return _Resp(200, {"status": "succeeded", "content": {"video_url": "https://video.example/x.mp4"}})


def test_mock_image():
    result = asyncio.run(generate_image(ImageRequest(prompt="雨夜霓虹")))
    assert result.provider == "mock"
    assert result.urls and result.urls[0].startswith("data:image/svg+xml")


def test_image_falls_back_when_no_key(monkeypatch):
    monkeypatch.setattr(settings, "image_provider", "siliconflow")
    monkeypatch.setattr(settings, "image_api_key", "")
    result = asyncio.run(generate_image(ImageRequest(prompt="无密钥")))
    assert result.provider == "mock"


def test_siliconflow_image(monkeypatch):
    monkeypatch.setattr(settings, "image_provider", "siliconflow")
    monkeypatch.setattr(settings, "image_api_key", "sk-test")
    monkeypatch.setattr(httpx, "AsyncClient", _FakeImagesClient)
    result = asyncio.run(generate_image(ImageRequest(prompt="赛博城市")))
    assert result.provider == "siliconflow"
    assert result.urls == ["https://img.example/x.png"]


def test_unknown_image_provider_raises(monkeypatch):
    monkeypatch.setattr(settings, "image_provider", "bogus")
    monkeypatch.setattr(settings, "image_api_key", "x")
    with pytest.raises(MediaError):
        asyncio.run(generate_image(ImageRequest(prompt="x")))


def test_mock_video_submit_poll():
    task = asyncio.run(submit_video(VideoRequest(prompt="暴风雨")))
    assert task.provider == "mock"
    assert task.status == "succeeded"
    result = asyncio.run(poll_video(task.task_id, task))
    assert result.video_url == f"mock://video/{task.task_id}.mp4"


def test_generate_video_mock():
    result = asyncio.run(generate_video(VideoRequest(prompt="海浪拍岸")))
    assert result.status == "succeeded"
    assert result.video_url.startswith("mock://video/")


def test_seedance_submit_and_poll(monkeypatch):
    monkeypatch.setattr(settings, "video_provider", "seedance")
    monkeypatch.setattr(settings, "video_api_key", "ark-test")
    monkeypatch.setattr(httpx, "AsyncClient", _FakeVideoClient)
    task = asyncio.run(submit_video(VideoRequest(prompt="星际穿越")))
    assert task.task_id == "cgt-1"
    result = asyncio.run(poll_video(task.task_id, task))
    assert result.status == "succeeded"
    assert result.video_url == "https://video.example/x.mp4"


class _FakeGatewayImagesClient:
    def __init__(self, *args, **kwargs): ...

    async def __aenter__(self): return self

    async def __aexit__(self, *args): ...

    async def post(self, url, **kwargs):
        assert url.endswith("/images/generations"), url
        assert kwargs["headers"]["Authorization"] == "Bearer yiwa_x"
        return _Resp(200, {"data": [{"url": "https://img.example/gw.png"}]})


class _FakeGatewayVideoClient:
    def __init__(self, *args, **kwargs): ...

    async def __aenter__(self): return self

    async def __aexit__(self, *args): ...

    async def post(self, url, **kwargs):
        assert url.endswith("/v1/videos/generations"), url
        assert kwargs["headers"]["Authorization"] == "Bearer yiwa_x"
        return _Resp(200, {"id": "gw-task-1"})

    async def get(self, url, **kwargs):
        assert "/v1/videos/generations/gw-task-1" in url, url
        return _Resp(200, {"status": "succeeded", "video_url": "https://video.example/gw.mp4"})


def test_yiwa_gateway_resolution(monkeypatch):
    monkeypatch.setattr(settings, "yiwa_token", "yiwa_x")
    monkeypatch.setattr(settings, "yiwa_gateway_url", "https://gw.example/api")
    assert images_mod._effective()["provider"] == "yiwa_gateway"
    assert video_mod._effective()["provider"] == "yiwa_gateway"


def test_yiwa_gateway_image(monkeypatch):
    monkeypatch.setattr(settings, "yiwa_token", "yiwa_x")
    monkeypatch.setattr(settings, "yiwa_gateway_url", "https://gw.example/api")
    monkeypatch.setattr(httpx, "AsyncClient", _FakeGatewayImagesClient)
    result = asyncio.run(generate_image(ImageRequest(prompt="网关生图")))
    assert result.provider == "yiwa_gateway"
    assert result.urls == ["https://img.example/gw.png"]


def test_yiwa_gateway_video(monkeypatch):
    monkeypatch.setattr(settings, "yiwa_token", "yiwa_x")
    monkeypatch.setattr(settings, "yiwa_gateway_url", "https://gw.example/api")
    monkeypatch.setattr(httpx, "AsyncClient", _FakeGatewayVideoClient)
    task = asyncio.run(submit_video(VideoRequest(prompt="网关生视频")))
    assert task.provider == "yiwa_gateway"
    result = asyncio.run(poll_video(task.task_id, task))
    assert result.status == "succeeded"
    assert result.video_url == "https://video.example/gw.mp4"


def test_unknown_video_provider_raises(monkeypatch):
    monkeypatch.setattr(settings, "video_provider", "bogus")
    monkeypatch.setattr(settings, "video_api_key", "x")
    with pytest.raises(MediaError):
        asyncio.run(submit_video(VideoRequest(prompt="x")))