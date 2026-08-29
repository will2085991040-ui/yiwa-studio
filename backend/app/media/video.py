"""生视频：支持 阿里DashScope happyhorse / 火山Seedance / YIWA网关 / mock。

- dashscope : 阿里云百炼视频合成（原生异步任务，happyhorse-1.1-t2v 等 t2v）
    POST https://dashscope.aliyuncs.com/api/v1/services/aigc/video-generation/video-synthesis  (X-DashScope-Async: enable)
         {"model", "input":{"text","resolution"}, "parameters"}
    GET  https://dashscope.aliyuncs.com/api/v1/tasks/{id}
         -> {"output":{"task_id","task_status","video_url"|"results":[{url}],"message"}}
- seedance : 火山方舟内容生成异步任务 POST {base}/contents/generations/tasks ; GET .../tasks/{id}
- minimax   : tokenhub 网关视频(model=minimax-video-h3, 文生视频+首尾帧)
- yiwa_gateway : YIWA 自研 /v1/videos/generations
provider=mock 或未配置 key 时回退 mock。
"""
import uuid

import httpx

from app.core.config import settings
from app.media.types import MediaError, VideoResult, VideoTask

_TERMINAL = ("succeeded", "failed")
_DASHSCOPE_ROOT = "https://dashscope.aliyuncs.com/api/v1"
_DASHSCOPE_SUBMIT = _DASHSCOPE_ROOT + "/services/aigc/video-generation/video-synthesis"

_SUPPORTED_RES = {"auto", "480p", "540p", "720p", "1080p", "1440p", "2k", "4k"}


def _auth(cfg):
    return {"Authorization": "Bearer " + (cfg.get("api_key") or "")}


def _as_json(resp):
    try:
        return resp.json()
    except ValueError as exc:
        raise MediaError("返回非JSON:" + (resp.text[:200] or "")) from exc


def _effective():
    if settings.yiwa_token and settings.yiwa_gateway_url:
        return {"provider": "yiwa_gateway", "base_url": settings.yiwa_gateway_url.rstrip("/"),
                "api_key": settings.yiwa_token, "model": settings.video_model,
                "query_path": settings.video_query_path,
                "poll_interval": settings.video_poll_interval, "max_polls": settings.video_max_polls}
    return {"provider": settings.video_provider,
            "base_url": (settings.video_base_url or "").rstrip("/"),
            "api_key": settings.video_api_key or settings.llm_api_key,
            "model": settings.video_model,
            "query_path": settings.video_query_path,
            "poll_interval": settings.video_poll_interval, "max_polls": settings.video_max_polls}


def _video_url_from(data):
    if not isinstance(data, dict):
        return ""
    if isinstance(data.get("output"), dict):
        data = data["output"]
    for key in ("video_url", "url", "download_url", "signed_url"):
        v = data.get(key)
        if isinstance(v, str) and v:
            return v
    for key in ("results", "output", "content", "result", "payload"):
        c = data.get(key)
        if isinstance(c, list):
            for it in c:
                if isinstance(it, dict):
                    for k in ("url", "video_url", "output"):
                        v = it.get(k)
                        if isinstance(v, str) and v:
                            return v
                elif isinstance(it, str) and it.startswith("http"):
                    return it
        elif isinstance(c, dict):
            for k in ("url", "video_url", "download_url"):
                v = c.get(k)
                if isinstance(v, str) and v:
                    return v
    return ""


def _normal_status(s):
    s = (s or "").strip().upper()
    return {"SUCCEEDED": "succeeded", "RUNNING": "running", "PENDING": "queued",
            "QUEUED": "queued", "FAILED": "failed", "SUCCESS": "succeeded"}.get(s, s.lower() or "queued")


def _seedance_content(request):
    content = []
    if request.ref_image:
        content.append({"type": "image_url", "image_url": {"url": request.ref_image}})
    content.append({"type": "text", "text": request.prompt})
    return content


async def submit_video(request, resolution="720p"):
    cfg = _effective()
    model = cfg.get("model") or ""
    if cfg.get("provider") == "mock" or not cfg.get("api_key") or not model:
        return VideoTask(provider="mock", model=model or "video",
                         task_id="mock-" + uuid.uuid4().hex[:8], status="succeeded")
    provider = cfg["provider"]
    try:
        if provider == "dashscope":
            return await _submit_dashscope(cfg, request, resolution)
        if provider == "yiwa_gateway":
            return await _submit_yiwa(cfg, request)
        if provider == "seedance":
            return await _submit_seedance(cfg, request)
        if provider == "minimax":
            return await _submit_minimax(cfg, request)
        if provider == "metaso_minimax":
            return await _submit_metaso(cfg, request)
    except MediaError:
        raise
    except Exception as exc:
        raise MediaError("生视频提交失败:" + str(exc)) from exc
    raise MediaError("未知 video_provider: " + str(provider))


async def _submit_seedance(cfg, request):
    url = cfg["base_url"] + "/contents/generations/tasks"
    payload = {"model": cfg["model"], "content": _seedance_content(request),
               "duration": max(1, min(int(request.duration_seconds or 5), 60)),
               "aspect_ratio": request.aspect_ratio if request.aspect_ratio in ("16:9", "9:16") else "16:9",
               "resolution": "720p", "watermark": False}
    async with httpx.AsyncClient(timeout=max(60, settings.llm_timeout_seconds)) as client:
        resp = await client.post(url, json=payload, headers=_auth(cfg))
    if resp.status_code >= 400:
        raise MediaError("生视频提交错误(" + str(resp.status_code) + "):" + resp.text[:300])
    data = _as_json(resp)
    task_id = data.get("id") or data.get("task_id") or (data.get("data") or {}).get("id")
    if not task_id:
        raise MediaError("生视频提交未返回任务id:" + resp.text[:300])
    return VideoTask(provider="seedance", model=cfg["model"], task_id=str(task_id), status="queued")

async def _submit_minimax(cfg, request):
    # tokenhub 网关视频: POST {base}/wand/minimax-video-v2/generation
    url = cfg['base_url'] + '/wand/minimax-video-v2/generation'
    content = [{'type': 'text', 'text': request.prompt}]
    if request.ref_image:
        content.append({'type': 'image_url', 'image_url': {'url': request.ref_image}, 'role': 'first_frame'})
    if request.ref_image_last:
        content.append({'type': 'image_url', 'image_url': {'url': request.ref_image_last}, 'role': 'last_frame'})
    payload = {'model': cfg['model'] or 'minimax-video-h3', 'content': content,
               'resolution': '768P', 'duration': max(1, min(int(request.duration_seconds or 5), 10))}
    if request.aspect_ratio in ("16:9", "9:16", "4:3", "3:4"):
        payload['ratio'] = request.aspect_ratio
    async with httpx.AsyncClient(timeout=max(60, settings.llm_timeout_seconds)) as client:
        resp = await client.post(url, json=payload, headers=_auth(cfg))
    if resp.status_code >= 400:
        raise MediaError('生视频提交错误(' + str(resp.status_code) + '):' + resp.text[:300])
    data = _as_json(resp)
    task_id = (data.get('task_id') or data.get('id')
               or (data.get('data') or {}).get('task_id') or (data.get('data') or {}).get('id'))
    if not task_id:
        raise MediaError('生视频提交未返回任务id:' + resp.text[:300])
    return VideoTask(provider='minimax', model=cfg['model'] or 'minimax-video-h3', task_id=str(task_id), status='queued')


async def _submit_metaso(cfg, request):
    # 秘塔/MiniMax 视频: POST {base}/api/minimax/v2/video_generation（已实测 key 有效返回 task_id）
    url = cfg['base_url'] + '/api/minimax/v2/video_generation'
    content = [{'type': 'text', 'text': request.prompt}]
    if request.ref_image:
        content.append({'type': 'image_url', 'image_url': {'url': request.ref_image}, 'role': 'first_frame'})
    if request.ref_image_last:
        content.append({'type': 'image_url', 'image_url': {'url': request.ref_image_last}, 'role': 'last_frame'})
    payload = {'model': cfg['model'] or 'MiniMax-H3', 'content': content,
               'resolution': '2K', 'duration': max(1, min(int(request.duration_seconds or 5), 10))}
    if request.aspect_ratio in ('16:9', '9:16', '4:3', '3:4'):
        payload['ratio'] = request.aspect_ratio
    async with httpx.AsyncClient(timeout=max(60, settings.llm_timeout_seconds)) as client:
        resp = await client.post(url, json=payload, headers=_auth(cfg))
    if resp.status_code >= 400:
        raise MediaError('生视频提交错误(' + str(resp.status_code) + '):' + resp.text[:300])
    data = _as_json(resp)
    task_id = (data.get('task_id') or data.get('id') or (data.get('data') or {}).get('task_id')
               or (data.get('data') or {}).get('id'))
    if not task_id:
        raise MediaError('生视频提交未返回任务id:' + resp.text[:300])
    return VideoTask(provider='metaso_minimax', model=cfg['model'] or 'MiniMax-H3', task_id=str(task_id), status='queued')


async def _submit_yiwa(cfg, request):
    url = cfg["base_url"] + "/v1/videos/generations"
    payload = {"model": cfg["model"], "prompt": request.prompt,
               "ref_image": request.ref_image, "duration_seconds": request.duration_seconds,
               "aspect_ratio": request.aspect_ratio}
    async with httpx.AsyncClient(timeout=max(60, settings.llm_timeout_seconds)) as client:
        resp = await client.post(url, json=payload, headers=_auth(cfg))
    if resp.status_code >= 400:
        raise MediaError("生视频提交错误(" + str(resp.status_code) + "):" + resp.text[:300])
    data = _as_json(resp)
    task_id = data.get("id") or data.get("task_id")
    if not task_id:
        raise MediaError("生视频提交未返回任务id:" + resp.text[:300])
    return VideoTask(provider=cfg["provider"], model=cfg["model"], task_id=str(task_id), status="queued")


async def _submit_dashscope(cfg, request, resolution):
    if not (request.prompt or "").strip():
        raise MediaError("生成视频需要prompt")
    params = {}
    resolution = (resolution or "720p").strip().lower()
    if resolution in _SUPPORTED_RES and resolution != "auto":
        params["resolution"] = resolution
    payload = {"model": cfg["model"], "input": {"text": request.prompt}, "parameters": params}
    headers = {**{"Authorization": "Bearer " + (cfg["api_key"] or "")}, "X-DashScope-Async": "enable"}
    async with httpx.AsyncClient(timeout=max(60, settings.llm_timeout_seconds)) as client:
        resp = await client.post(_DASHSCOPE_SUBMIT, json=payload, headers=headers)
    if resp.status_code >= 400:
        raise MediaError("生视频提交错误(" + str(resp.status_code) + "):" + resp.text[:300])
    data = _as_json(resp)
    out = data.get("output") or {}
    task_id = out.get("task_id") or data.get("request_id")
    if not task_id:
        raise MediaError("生视频提交未返回任务id:" + resp.text[:300])
    return VideoTask(provider="dashscope", model=cfg["model"], task_id=str(task_id), status="queued")


async def poll_video(task_id, task=None):
    cfg = _effective()
    if task is not None and task.provider == "mock":
        return VideoResult(**task.model_dump(), video_url="mock://video/" + task.task_id + ".mp4")
    if cfg.get("provider") == "mock":
        return VideoResult(provider="mock", model=cfg["model"], task_id=task_id, status="succeeded",
                           video_url="mock://video/" + task_id + ".mp4")
    provider = cfg["provider"]
    if provider == "dashscope":
        return await _poll_dashscope(task_id)
    try:
        if provider == "seedance":
            url = cfg["base_url"] + "/contents/generations/tasks/" + task_id
        elif provider == "minimax":
            url = cfg["base_url"] + "/wand/minimax-video-v2/tasks/" + task_id
        elif provider == "metaso_minimax":
            # 秘塔查询端点以 query_path 为准（{task} 占位）；提交侧已实测 200+task_id
            qp = cfg.get("query_path") or "/api/minimax/v2/video_generation/{task}"
            url = cfg["base_url"] + qp.replace("{task}", task_id)
        else:
            url = cfg["base_url"] + "/v1/videos/generations/" + task_id
        async with httpx.AsyncClient(timeout=max(60, settings.llm_timeout_seconds)) as client:
            resp = await client.get(url, headers=_auth(cfg))
        if resp.status_code >= 400:
            raise MediaError("生视频查询错误(" + str(resp.status_code) + "):" + resp.text[:300])
        data = _as_json(resp)
    except MediaError:
        raise
    except httpx.HTTPError as exc:
        raise MediaError("生视频查询失败:" + str(exc)) from exc
    status = _normal_status(data.get("status", "queued"))
    return VideoResult(provider=provider, model=cfg["model"], task_id=task_id, status=status,
                       video_url=_video_url_from(data),
                       error=("生视频任务失败" if status == "failed" else ""))


async def _poll_dashscope(task_id):
    url = _DASHSCOPE_ROOT + "/tasks/" + task_id
    cfg = _effective()
    async with httpx.AsyncClient(timeout=max(60, settings.llm_timeout_seconds)) as client:
        resp = await client.get(url, headers=_auth(cfg))
    if resp.status_code >= 400:
        raise MediaError("生视频查询错误(" + str(resp.status_code) + "):" + resp.text[:300])
    data = _as_json(resp)
    out = data.get("output") or {}
    status = _normal_status(out.get("task_status", data.get("status", "queued")))
    video_url = ""
    for it in (out.get("results") or []):
        if isinstance(it, dict) and isinstance(it.get("url"), str) and it["url"]:
            video_url = it["url"]
            break
    if not video_url:
        video_url = _video_url_from(out)
    msg = out.get("message") or (out.get("error") if status == "failed" else "") or ""
    return VideoResult(provider="dashscope", model=cfg["model"], task_id=task_id, status=status,
                       video_url=video_url, error=str(msg) if status == "failed" else "")


async def generate_video(request):
    task = await submit_video(request)
    cfg = _effective()
    if task.status in _TERMINAL:
        return await poll_video(task.task_id, task)
    for _ in range(max(1, cfg["max_polls"])):
        await _sleep(cfg["poll_interval"])
        result = await poll_video(task.task_id, task)
        if result.status in _TERMINAL:
            return result
    raise MediaError("生视频超时: 任务 " + task.task_id + " 未在轮询上限内完成")


async def _sleep(seconds):
    import asyncio
    await asyncio.sleep(max(0.0, seconds))
