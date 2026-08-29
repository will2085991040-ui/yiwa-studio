"""角色立绘引用解析：从最新 character_portrait 取可用立绘图（供图生视频首帧使用）。"""

from app.schemas.portrait import CharacterPortrait
from app.services.artifacts import latest_artifact

_BASE_NAMES = ("基础立绘", "原基础立绘备份")


def resolve_portrait_image(session, project_id: str, character_id: str) -> str:
    """返回该角色最新立绘图 URL；无则返回空串。"""
    artifact = latest_artifact(session, project_id, kind="character_portrait:" + character_id)
    if artifact is None or not artifact.content:
        return ""
    try:
        portrait = CharacterPortrait.model_validate(artifact.content)
    except (ValueError, TypeError):
        return ""
    best: str = ""
    base_id = portrait.base_variant_id
    for v in portrait.variants:
        img = v.image or {}
        url = img.get("url") or img.get("storage_path") or img.get("data") or ""
        if not url:
            continue
        name = (v.name or "").strip()
        if name in _BASE_NAMES or v.variant_id == base_id:
            return url
        if not best:
            best = url
    return best
