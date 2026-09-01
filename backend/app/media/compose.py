"""把若干 5s 镜头片段按顺序合成一个完整成片（ffmpeg concat + 可选淡入淡出）。

合成引擎即开源 ffmpeg（经 imageio-ffmpeg 自带的静态 ffmpeg 二进制，离线可用）。
pyinstaller 打包时需把该二进制作为 data 一并打入（见 desktop/yiwa.spec）。
"""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import httpx

from app.core.config import settings

_FFMPEG_EXE = None


def ffmpeg_exe() -> str:
    global _FFMPEG_EXE
    if _FFMPEG_EXE:
        return _FFMPEG_EXE
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        exe = shutil.which("ffmpeg") or ""
    if not exe or not Path(exe).exists():
        raise RuntimeError("未找到 ffmpeg（imageio-ffmpeg 未安装或未打进桌面包）")
    _FFMPEG_EXE = exe
    return exe


def _safe_name(name: str) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff.\-]", "_", name or "film")[:40] or "film"


async def _download(url: str, dest: Path) -> Path:
    async with httpx.AsyncClient(timeout=max(120, settings.llm_timeout_seconds),
                                 follow_redirects=True) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        dest.write_bytes(resp.content)
    return dest


async def compose_clips(urls: list[str], output_path: Path,
                        transition: str = "hard", target_fps: int = 24) -> Path:
    """把 urls 依序合成一个完整 mp4。

    transition ∈ {"hard"（硬切连播，默认）｜"fade_front"（每个片段 0.5s 淡入+淡出）}。
    统一 scale/setsar/fps/yuv420p 保证 concat 不花屏。失败抛 RuntimeError。
    """
    ffmpeg = ffmpeg_exe()
    raw = list(urls or [])
    if not raw:
        raise RuntimeError("没有可合成的片段")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="yiwa_compose_"))
    try:
        norm: list[Path] = []
        for i, u in enumerate(raw):
            src = work / f"clip{i}.mp4"
            await _download(u, src)
            dst = work / f"n{i}.mp4"
            vf = "scale=trunc(iw/2)*2:trunc(ih/2)*2,setsar=1,fps=" + str(target_fps)
            if transition == "fade":
                vf += (",fade=in:st=0:d=0.4,fade=out:st=4.4:d=0.6")
            cmd = [ffmpeg, "-y", "-i", str(src), "-vf", vf,
                   "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(dst)]
            r = subprocess.run(cmd, capture_output=True, text=True)
            if r.returncode != 0:
                raise RuntimeError("ffmpeg 规整失败: " + (r.stderr or r.stdout)[-300:])
            norm.append(dst)
        listfile = work / "list.txt"
        listfile.write_text("\n".join(f"file '{p.as_posix()}'" for p in norm) + "\n", encoding="utf-8")
        cmd = [ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(listfile),
               "-c", "copy", str(output_path)]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError("ffmpeg 合成失败: " + (r.stderr or r.stdout)[-300:])
        return output_path
    finally:
        shutil.rmtree(work, ignore_errors=True)