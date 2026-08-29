"""API：角色立绘 + 8 段外貌 + 差分（增量：Funloom 蒸馏 · Phase 2）。

以 Artifact(kind="character_portrait:{character_id}") 作为权威数据，复用既有
`persist_versioned_artifact` 版本链，与 StoryGraph 编辑器的读写模式一致。
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.errors import AppError, NotFoundError
from app.db.base import get_session
from app.media.images import generate_image
from app.media.types import ImageRequest
from app.models import Artifact, Project
from app.schemas.character_card import CharacterCard
from app.schemas.portrait import (
    CharacterPortrait,
    PortraitVariant,
    compose_base_prompt,
    compose_variant_prompt,
    portrait_template,
    promote_variant,
)
from app.services.artifacts import latest_artifact, persist_versioned_artifact
from app.services.portrait_ref import resolve_portrait_image

router = APIRouter(prefix="/api")

_AGENT = "portrait_editor"
_TASK = "portrait_editor"


def _kind(character_id: str) -> str:
    return f"character_portrait:{character_id}"


def _require_project(session: Session, project_id: str) -> None:
    if session.get(Project, project_id) is None:
        raise NotFoundError("项目不存在")


def _empty(character_id: str, name: str = "") -> CharacterPortrait:
    return CharacterPortrait(character_id=character_id, name=name)


def _load(session: Session, project_id: str, character_id: str) -> tuple[CharacterPortrait, int]:
    artifact = latest_artifact(session, project_id, kind=_kind(character_id))
    if artifact is None:
        return _empty(character_id), 0
    return CharacterPortrait.model_validate(artifact.content or {"character_id": character_id}), artifact.version


def _view(portrait: CharacterPortrait, version: int) -> dict:
    d = portrait.model_dump()
    d["version"] = version
    d["base_prompt"] = compose_base_prompt(portrait)
    d["variant_prompts"] = {v.variant_id: compose_variant_prompt(portrait, v) for v in portrait.variants}
    return d


class PortraitSaveInput(BaseModel):
    portrait: CharacterPortrait
    change_reason: str | None = None


class PromoteInput(BaseModel):
    variant_id: str


class PromptPreviewInput(BaseModel):
    portrait: CharacterPortrait


class VariantImageInput(BaseModel):
    size: str = ""
    ref_image: str | None = None


class BatchVariantsInput(BaseModel):
    character_ids: list[str] | None = None
    force: bool = False


def _aspect_size(aspect: str) -> str:
    if aspect == "9:16":
        return "768x1344"
    if aspect == "16:9":
        return "1344x768"
    return "1024x1024"


@router.get("/portraits/template")
def template() -> dict:
    return portrait_template()


@router.get("/projects/{project_id}/characters")
def list_characters(project_id: str, session: Session = Depends(get_session)) -> list[dict]:
    """返回该项目最新角色卡（供角色选择器）。"""
    _require_project(session, project_id)
    rows = (
        session.query(Artifact)
        .filter(
            Artifact.project_id == project_id, Artifact.kind.startswith("character_card"), Artifact.is_latest.is_(True)
        )
        .order_by(Artifact.created_at)
        .all()
    )
    seen: dict[str, dict] = {}
    for a in rows:
        cid = (a.content or {}).get("character_id") or ""
        if not cid:
            continue
        seen[cid] = {
            "character_id": cid,
            "name": (a.content or {}).get("name") or "未命名角色",
            "role": (a.content or {}).get("role") or "",
            "kind": a.kind,
        }
    return list(seen.values())


class CharacterCreateInput(BaseModel):
    """新建角色：最小信息即可，其余字段可后续在表单补全。"""

    name: str = ""
    role: str = ""
    appearance: str = ""
    character_id: str | None = None  # 缺省自动生成 char-{n}


class CharacterUpsertInput(BaseModel):
    """保存整张角色卡（手动编辑 / 新增）。"""

    card: CharacterCard
    change_reason: str | None = None


def _next_character_id(session: Session, project_id: str) -> str:
    """生成不冲突的角色 id：char-1 / char-2 ..."""
    rows = (
        session.query(Artifact)
        .filter(Artifact.project_id == project_id, Artifact.kind.startswith("character_card"))
        .all()
    )
    used: set[str] = set()
    for a in rows:
        cid = (a.content or {}).get("character_id")
        if cid:
            used.add(cid)
    n = 1
    while f"char-{n}" in used:
        n += 1
    return f"char-{n}"


def _find_character_card(session: Session, project_id: str, character_id: str) -> Artifact | None:
    """找角色卡：先按 per-entity kind，再兼容旧无后缀 kind 的遗留数据。"""
    artifact = latest_artifact(session, project_id, kind=f"character_card:{character_id}")
    if artifact is not None:
        return artifact
    return (
        session.query(Artifact)
        .filter(
            Artifact.project_id == project_id,
            Artifact.kind == "character_card",
            Artifact.is_latest.is_(True),
        )
        .filter(Artifact.content["character_id"].as_string() == character_id)
        .order_by(Artifact.created_at.desc())
        .first()
    )


@router.post("/projects/{project_id}/characters")
def create_character(
    project_id: str, payload: CharacterCreateInput, session: Session = Depends(get_session)
) -> dict:
    """手动新增一个角色：落一张 character_card:{id}（source=user）。"""
    _require_project(session, project_id)
    cid = (payload.character_id or "") if payload.character_id else ""
    if cid and _find_character_card(session, project_id, cid) is not None:
        raise AppError(f"角色 id {cid} 已存在", code="character_id_exists", status=400)
    if not cid:
        cid = _next_character_id(session, project_id)
    card = CharacterCard(
        character_id=cid,
        name=payload.name.strip() or "新角色",
        role=payload.role.strip() or "角色",
        appearance=payload.appearance.strip(),
    )
    artifact = persist_versioned_artifact(
        session, project_id=project_id, task_id=f"manual-{cid}", agent="user_editor",
        kind=f"character_card:{cid}", content=card.model_dump(), prompt_version="",
        source="user", change_reason="手动新增角色",
    )
    session.commit()
    return {"character_id": cid, "version": artifact.version, "card": card.model_dump()}


@router.get("/projects/{project_id}/characters/{character_id}")
def get_character(project_id: str, character_id: str, session: Session = Depends(get_session)) -> dict:
    """读取单张角色卡；不存在则返回 card=None。"""
    _require_project(session, project_id)
    artifact = _find_character_card(session, project_id, character_id)
    if artifact is None:
        return {"character_id": character_id, "version": 0, "card": None}
    return {"character_id": character_id, "version": artifact.version, "card": artifact.content}


@router.put("/projects/{project_id}/characters/{character_id}")
def update_character(
    project_id: str, character_id: str, payload: CharacterUpsertInput, session: Session = Depends(get_session)
) -> dict:
    """手动编辑整张角色卡（SourceGraph 用户改写），追加新版本。"""
    _require_project(session, project_id)
    if payload.card.character_id != character_id:
        raise AppError("卡片 character_id 与路径不一致", code="id_mismatch", status=400)
    artifact = persist_versioned_artifact(
        session, project_id=project_id, task_id=f"manual-{character_id}", agent="user_editor",
        kind=f"character_card:{character_id}", content=payload.card.model_dump(), prompt_version="",
        source="user", change_reason=payload.change_reason or "手动编辑角色",
    )
    session.commit()
    return {"character_id": character_id, "version": artifact.version, "card": payload.card.model_dump()}


@router.delete("/projects/{project_id}/characters/{character_id}")
def delete_character(project_id: str, character_id: str, session: Session = Depends(get_session)) -> dict:
    """删除角色：移除其角色卡（含版本历史）与立绘。角色选择器不再提示。"""
    _require_project(session, project_id)
    kinds = [f"character_card:{character_id}", f"character_portrait:{character_id}"]
    deleted = (
        session.query(Artifact)
        .filter(Artifact.project_id == project_id, Artifact.kind.in_(kinds))
        .delete(synchronize_session=False)
    )
    # 兼容遗留无后缀 character_card（按 content.character_id 匹配）一并清理
    legacy_card = (
        session.query(Artifact)
        .filter(
            Artifact.project_id == project_id,
            Artifact.kind == "character_card",
            Artifact.is_latest.is_(True),
        )
        .all()
    )
    legacy_ids = [a.id for a in legacy_card if (a.content or {}).get("character_id") == character_id]
    if legacy_ids:
        session.query(Artifact).filter(Artifact.id.in_(legacy_ids)).delete(synchronize_session=False)
        deleted += len(legacy_ids)
    session.commit()
    return {"deleted": True, "character_id": character_id, "rows": deleted}


@router.get("/projects/{project_id}/characters/{character_id}/portrait")
def get_portrait(project_id: str, character_id: str, session: Session = Depends(get_session)) -> dict:
    _require_project(session, project_id)
    portrait, version = _load(session, project_id, character_id)
    return _view(portrait, version)


@router.put("/projects/{project_id}/characters/{character_id}/portrait")
def put_portrait(
    project_id: str, character_id: str, payload: PortraitSaveInput, session: Session = Depends(get_session)
) -> dict:
    _require_project(session, project_id)
    if payload.portrait.character_id != character_id:
        raise AppError("character_id 不一致", code="character_id_mismatch", status=400)
    artifact = persist_versioned_artifact(
        session,
        project_id=project_id,
        task_id=_TASK,
        agent=_AGENT,
        kind=_kind(character_id),
        content=payload.portrait.model_dump(),
        prompt_version="",
        source="user",
        change_reason=payload.change_reason,
    )
    session.commit()
    return _view(CharacterPortrait.model_validate(artifact.content), artifact.version)


@router.post("/projects/{project_id}/characters/{character_id}/portrait/promote")
def promote(project_id: str, character_id: str, payload: PromoteInput, session: Session = Depends(get_session)) -> dict:
    """把某个差分提升为基础立绘（自动保留原基础立绘备份）并落库。"""
    _require_project(session, project_id)
    portrait, _ = _load(session, project_id, character_id)
    try:
        updated = promote_variant(portrait, payload.variant_id)
    except ValueError as e:
        raise AppError(str(e), code="variant_not_found", status=404) from e
    artifact = persist_versioned_artifact(
        session, project_id=project_id, task_id=_TASK, agent=_AGENT, kind=_kind(character_id),
        content=updated.model_dump(), prompt_version="", source="user", change_reason=f"promote→{payload.variant_id}",
    )
    session.commit()
    return _view(CharacterPortrait.model_validate(artifact.content), artifact.version)


@router.post("/projects/{project_id}/characters/{character_id}/portrait/variants/{variant_id}/image")
async def generate_variant_image(
    project_id: str,
    character_id: str,
    variant_id: str,
    payload: VariantImageInput,
    session: Session = Depends(get_session),
) -> dict:
    """按差分提示词生成立绘差分图，把结果写回 variant.image 并落库。"""
    _require_project(session, project_id)
    portrait, _ = _load(session, project_id, character_id)
    variant = next((v for v in portrait.variants if v.variant_id == variant_id), None)
    if variant is None:
        raise NotFoundError(f"差分 {variant_id} 不存在")
    prompt = compose_variant_prompt(portrait, variant)
    result = await generate_image(ImageRequest(
        prompt=prompt,
        size=payload.size or _aspect_size(variant.aspect),
        ref_image=payload.ref_image,
    ))
    url = result.urls[0] if result.urls else (result.b64[0] if result.b64 else "")
    updated_variant = variant.model_copy(update={
        "image": {"source": "generated", "url": url, "provider": result.provider, "model": result.model},
        "status": "saved",
        "source": "generated",
    })
    updated = portrait.model_copy(update={
        "variants": [v if v.variant_id != variant_id else updated_variant for v in portrait.variants],
    })
    artifact = persist_versioned_artifact(
        session, project_id=project_id, task_id=_TASK, agent=_AGENT, kind=_kind(character_id),
        content=updated.model_dump(), prompt_version="", source="generated",
        change_reason=f"generate-image→{variant_id}",
    )
    session.commit()
    return {
        "portrait": _view(CharacterPortrait.model_validate(artifact.content), artifact.version),
        "prompt": prompt,
        "image": result.model_dump(),
    }


@router.post("/projects/{project_id}/portraits/batch-generate")
async def batch_generate_variants(
    project_id: str,
    payload: BatchVariantsInput,
    session: Session = Depends(get_session),
) -> dict:
    """批量立绘差分：对指定（或全部）角色逐个补全差分图，写回 image 并落库。

    - 仅生成尚未产出画像的差分；force=True 时全部重生成。
    - 每个角色在全部差分生成完后统一落一个版本（避免逐差分版本爆炸）。
    """
    _require_project(session, project_id)
    if payload.character_ids:
        character_ids = [c for c in payload.character_ids if c]
    else:
        rows = (
            session.query(Artifact)
            .filter(
                Artifact.project_id == project_id,
                Artifact.kind.startswith("character_card"),
                Artifact.is_latest.is_(True),
            )
            .order_by(Artifact.created_at)
            .all()
        )
        character_ids = [(a.content or {}).get("character_id") or "" for a in rows]

    results: list[dict] = []
    for cid in character_ids:
        portrait, _ = _load(session, project_id, cid)
        generated = 0
        variants = list(portrait.variants)
        for v in variants:
            if not payload.force and v.image is not None:
                continue
            prompt = compose_variant_prompt(portrait, v)
            result = await generate_image(ImageRequest(prompt=prompt, size=_aspect_size(v.aspect)))
            url = result.urls[0] if result.urls else (result.b64[0] if result.b64 else "")
            variants = [
                (
                    vv
                    if vv.variant_id != v.variant_id
                    else vv.model_copy(update={
                        "image": {
                            "source": "generated", "url": url,
                            "provider": result.provider, "model": result.model,
                        },
                        "status": "saved", "source": "generated",
                    })
                )
                for vv in variants
            ]
            generated += 1

        if generated == 0:
            results.append({"character_id": cid, "name": portrait.name, "generated": 0, "version": 0})
            continue

        updated = portrait.model_copy(update={"variants": variants})
        artifact = persist_versioned_artifact(
            session, project_id=project_id, task_id=_TASK, agent=_AGENT, kind=_kind(cid),
            content=updated.model_dump(), prompt_version="", source="generated",
            change_reason=f"batch-generate→{generated} 差分",
        )
        results.append({
            "character_id": cid, "name": portrait.name, "generated": generated, "version": artifact.version,
        })

    session.commit()
    return {"results": results, "total_generated": sum(r["generated"] for r in results)}


@router.post("/projects/{project_id}/characters/{character_id}/portrait/prompt")
def preview_prompt(
    project_id: str, character_id: str, payload: PromptPreviewInput, session: Session = Depends(get_session)
) -> dict:
    """不落库地合成基础/差分提示词，供画布即时预览。"""
    _require_project(session, project_id)
    return _view(payload.portrait, 0)



class PortraitGenerateInput(BaseModel):
    style: str = "anime"   # 画面风格 key（app/media/styles.py）
    aspect: str = "9:16"
    force: bool = False


@router.post("/projects/{project_id}/characters/{character_id}/portrait/generate")
async def generate_base_portrait(project_id: str, character_id: str, payload: PortraitGenerateInput,
                                 session: Session = Depends(get_session)) -> dict:
    """One-click: read character card, merge 8-section appearance, compose base prompt, generate, and save."""

    _require_project(session, project_id)
    card = _find_character_card(session, project_id, character_id)
    portrait, _version = _load(session, project_id, character_id)
    if card is not None:
        text = (card.content or {}).get("appearance") or (card.content or {}).get("description") or ""
        text = str(text).strip()
        app9 = dict(portrait.appearance or {})
        if text:
            existing = (app9.get("basic") or "").strip()
            app9["basic"] = (existing + "，" + text) if existing else text
        if not portrait.name and (card.content or {}).get("name"):
            portrait = portrait.model_copy(update={"name": (card.content or {}).get("name")})
        portrait = portrait.model_copy(update={"appearance": app9})
    portrait = portrait.model_copy(update={"style": payload.style or portrait.style,
                                             "aspect": payload.aspect or portrait.aspect})
    prompt = compose_base_prompt(portrait)
    result = await generate_image(ImageRequest(prompt=prompt, size=_aspect_size(portrait.aspect),
        style=payload.style))
    url = result.urls[0] if result.urls else (result.b64[0] if result.b64 else "")
    if not url:
        raise AppError("生成立绘未返回图片", code="no_image", status=400)
    base_var = PortraitVariant(
        variant_id="base", name="基础立绘", category="base", value="基础立绘",
        description="一键生成的基础立绘", style=portrait.style, aspect=portrait.aspect,
        image={"source": "generated", "url": url,
        "provider": result.provider, "model": result.model},
        status="saved", source="generated",
    )
    variants = [v for v in portrait.variants if v.variant_id != "base"] + [base_var]
    updated = portrait.model_copy(update={"variants": variants, "base_variant_id": "base"})
    artifact = persist_versioned_artifact(
        session, project_id=project_id, task_id=_TASK, agent=_AGENT, kind=_kind(character_id),
        content=updated.model_dump(), prompt_version="", source="generated", change_reason="一键生成立绘",
    )
    session.commit()
    return {"portrait": _view(CharacterPortrait.model_validate(artifact.content), artifact.version),
        "image_url": url, "prompt": prompt}


@router.get("/projects/{project_id}/characters/{character_id}/portrait/video_ref")
def portrait_video_ref(project_id: str, character_id: str, session: Session = Depends(get_session)) -> dict:
    """返回该角色已保存立绘图 URL，作为图生视频首帧（保证人物一致）。"""
    _require_project(session, project_id)
    url = resolve_portrait_image(session, project_id, character_id)
    return {"character_id": character_id, "ref_image": url, "has_portrait": bool(url)}