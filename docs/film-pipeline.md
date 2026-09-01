# 分镜 → 逐个生视频 → 页面剪辑成片（视频链路）

> 本文档说明 YIWA 的核心视频创作链路：把分镜拆成一个个镜头、每个镜头独立生成一段视频，再在页面里排序/加转场，用本地 FFmpeg 合成最终成片。全链路离线可跑（未配置密钥时自动回退 Mock）。

## 目标
- 按 Storyboard 的 `shots` ——每个分镜镜头——分别生成一段 5s（或用户所选 4–15s）视频，避免"整段一个任务"难以剪辑。
- 在页面给出一套轻量时间轴：排序、逐镜预览、转场选择，一键导出完整 MP4。
- 用户可控：**分辨率**（默认 768P）、**生成时长（4–15s）**、**首帧图 / 尾帧图**（用首尾帧控制视频的开始与结束画面）。

## 数据流

```
整列拆镜(Storyboard.shots, 结构化)
   │
   ▼  compose_shot_prompt(shot, character_identity)   # 每镜头独立提示词
POST /api/projects/{pid}/storyboard/{node}/video/clips
   │   body: { aspect_ratio, resolution, duration_sec, ref_image, ref_image_last, style }
   ▼
落库 Artifact(kind="video_clips:{node_id}")：
   { clips: [ {shot_no, prompt, status, task_id, provider, model, video_url, error} ],
     status: running|done|none, duration_per_clip, resolution, aspect_ratio }
   —— 每个镜头一个独立厂商 task（submit_video → 真实渲染异步）
   │
GET  .../video/clips                     # 前端 4s 轮询；后端逐镜头 poll_video() 并回写
   │
   ▼  全部 done
POST .../video/clips/compose
   body: { order:[shot_no,…], transition:"hard"|"fade" }
   └─ 本地 FFmpeg(offline) concat + scale/setsar/fps/yuv420p 规整
   ▼
GET  /api/projects/{pid}/compose/{filename}  → 下载最终成片 MP4
```

## 关键 API

### 1) 逐镜头生成
`POST /api/projects/{pid}/storyboard/{node}/video/clips`
- 入参（`VideoGenInput`）：
  - `aspect_ratio`: `16:9` / `9:16`
  - `resolution`: 默认 `768P`（可 `1080P`/`2K`/`4K`）
  - `duration_sec`: 4–15，后端 `eff_duration` 自动钳制
  - `ref_image`: 首帧图 URL（控制开始画面）
  - `ref_image_last`: 尾帧图 URL（控制结束画面，与首帧一起时用首尾帧）
  - `style`: 画面风格 key
- 返回 `{node_id, aspect_ratio, duration, resolution, clips:[…], status}`。

### 2) 轮询落定
`GET /api/projects/{pid}/storyboard/{node}/video/clips`
- 对仍在 `queued/running` 的镜头逐个向厂商 `poll_video(task_id)`，把 `done + video_url` / `failed + error` 回写并持久化。

### 3) 合成成片（本地 ffmpeg）
`POST /api/projects/{pid}/storyboard/{node}/video/clips/compose`
- 入参：`{ order: [1,3,2], transition: "hard"|"fade", filename: "成片" }`
- 只允许已 `done` 且带 `video_url` 的镜头入队；顺序由前端时间轴决定。
- 用 `app.media.compose.compose_clips(urls, out, transition)`：`httpx` 下载各片段 → FFmpeg
  `scale/setsar/fps/yuv420p` 规整 → concat demuxer → 输出统一 mp4，存到 `{data_dir}/composes/{project_id}/`。
- 返回 `{ url, filename, size, clips, transition }`。

### 4) 下载
`GET /api/projects/{pid}/compose/{filename}` → `FileResponse(video/mp4)`。

## 后端实现要点

- `backend/app/media/compose.py`
  - `ffmpeg_exe()`：优先 `imageio_ffmpeg.get_ffmpeg_exe()`（随包自带的静态二进制），失败回落 `shutil.which("ffmpeg")`。
  - `_download()` + `compose_clips(urls, out, transition, target_fps)`：临时目录逐段下载→规整→concat。
- `backend/app/media/video.py`
  - `_submit_*` 各自 provider；秘密/MiniMax 用 `POST {base}/api/minimax/v2/video_generation`，查询 `GET {base}/api/minimax/v2/query/video_generation/{task}`。
  - `ref_image`/`ref_image_last` 以 `role: first_frame/last_frame` 传入 content（首尾帧控制）。
  - `resolution`：`_minimax_resolution()` 归一化（默认 768P）；`duration` 钳到 4–15。
- 打包：`backend/desktop/yiwa.spec` 用 `collect_data_files("imageio_ffmpeg")` 把 ffmpeg 二进制打成 data，随 EXE 发布（离线可合成）。

## 前端
- 页面：`frontend/app/storyboard/page.tsx`
  - 生成参数：分辨率下拉（768P 默认）、时长数字框（4–15）、首帧图 / 尾帧图 URL。
  - 「生成逐个镜头」→ 轮询 `GET .../video/clips`，时间轴展示每镜头缩略图 + 状态。
  - 「导出完整成片」→ `POST .../clips/compose` → 显示下载链接。
  - 转场选择：硬切 / 淡入淡出。

## 边界与验收
- 未配密钥/离线：用 `provider=mock` 生成 `mock://video/…`，链路全流程可跑（不消耗配额）。
- 真实渲染：3 个镜头端到端实测各任务 `succeeded` 并拿到 `video_url`；ffmpeg 离线 concat 实测可产出 `composed.mp4`。
- 单镜头失败不阻断整批：该镜头标记 `failed+error`，其余镜头照常生成；合成时只取 done。