"""Material Store（Step 19）：素材元数据 + 引用 + 检索基础接口。

不做复杂 AI 绘图、不接第三方服务；先打好「数据模型 / 存储路径 / 引用 / 检索」基础。
删除 = 软废弃（status=abandoned），不物理删除。
"""
import re

from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import Material

MATERIAL_KINDS = ("character_image", "scene_image", "cg", "bgm", "sfx", "storyboard", "asset")


def _row(m: Material) -> dict:
    return {
        "id": m.id, "project_id": m.project_id, "kind": m.kind, "name": m.name,
        "description": m.description, "storage_path": m.storage_path, "mime_type": m.mime_type,
        "metadata": m.meta or {}, "ref_kind": m.ref_kind, "ref_id": m.ref_id,
        "tags": m.tags or [], "status": m.status,
    }


class MaterialStore:
    def upload(
        self,
        session: Session,
        project_id: str,
        *,
        kind: str,
        name: str,
        description: str = "",
        storage_path: str = "",
        mime_type: str = "",
        metadata: dict | None = None,
        ref_kind: str = "",
        ref_id: str | None = None,
        tags: list[str] | None = None,
    ) -> Material:
        if kind not in MATERIAL_KINDS:
            raise AppError(f"未知素材类型：{kind}", code="invalid_material_kind", status=400)
        material = Material(
            project_id=project_id, kind=kind, name=name, description=description,
            storage_path=storage_path or f"materials/{project_id}/{kind}/{name}",
            mime_type=mime_type, meta=metadata or {},
            ref_kind=ref_kind, ref_id=ref_id, tags=tags or [],
        )
        session.add(material)
        session.commit()
        return material

    def list_materials(self, session: Session, project_id: str, *, kind: str | None = None) -> list[dict]:
        query = session.query(Material).filter(Material.project_id == project_id)
        if kind is not None:
            query = query.filter(Material.kind == kind)
        return [_row(m) for m in query.order_by(Material.created_at).all()]

    def get(self, session: Session, material_id: str) -> Material:
        material = session.get(Material, material_id)
        if material is None:
            raise AppError(f"素材 {material_id} 不存在", code="material_not_found", status=404)
        return material

    def search(self, session: Session, project_id: str, query: str, *, top_k: int = 10) -> list[dict]:
        """基础检索：按 name/description/tags 的命中词数排序（可重建，非唯一数据源）。"""
        rows = (
            session.query(Material)
            .filter(Material.project_id == project_id, Material.status == "active")
            .all()
        )
        terms = [t.lower() for t in re.split(r"[\W_]+", query or "") if t]
        if not terms:
            return []
        scored: list[tuple[Material, int]] = []
        for m in rows:
            hay = f"{m.name} {m.description} {' '.join(m.tags or [])}".lower()
            score = sum(1 for t in terms if t in hay)
            if score:
                scored.append((m, score))
        scored.sort(key=lambda item: -item[1])
        return [_row(m) for m, _ in scored[:top_k]]

    def associate(self, session: Session, material_id: str, *, ref_kind: str, ref_id: str | None) -> Material:
        material = self.get(session, material_id)
        material.ref_kind = ref_kind
        material.ref_id = ref_id
        session.commit()
        return material

    def abandon(self, session: Session, material_id: str) -> Material:
        """软废弃：保留历史，仅标记 status。"""
        material = self.get(session, material_id)
        material.status = "abandoned"
        session.commit()
        return material


material_store = MaterialStore()