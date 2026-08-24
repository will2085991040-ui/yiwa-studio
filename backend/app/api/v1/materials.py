"""API：Material（Step 19）。"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.base import get_session
from app.models import Material
from app.schemas import MaterialAssociateInput, MaterialCreateInput, MaterialOut
from app.services.materials import material_store

router = APIRouter(prefix="/api/projects")


def _out(m: Material) -> dict:
    return {
        "id": m.id, "project_id": m.project_id, "kind": m.kind, "name": m.name,
        "description": m.description, "storage_path": m.storage_path, "mime_type": m.mime_type,
        "metadata": m.meta or {}, "ref_kind": m.ref_kind, "ref_id": m.ref_id,
        "tags": m.tags or [], "status": m.status,
    }


@router.post("/{project_id}/materials", response_model=MaterialOut)
def upload_material(project_id: str, payload: MaterialCreateInput, session: Session = Depends(get_session)) -> dict:
    m = material_store.upload(
        session, project_id, kind=payload.kind, name=payload.name, description=payload.description,
        storage_path=payload.storage_path, mime_type=payload.mime_type, metadata=payload.metadata,
        ref_kind=payload.ref_kind, ref_id=payload.ref_id, tags=payload.tags,
    )
    return _out(m)


@router.get("/{project_id}/materials", response_model=list[MaterialOut])
def list_materials(
    project_id: str, kind: str | None = None, q: str | None = None, session: Session = Depends(get_session)
) -> list[dict]:
    if q:
        return material_store.search(session, project_id, q)
    return material_store.list_materials(session, project_id, kind=kind)


@router.post("/{project_id}/materials/{material_id}/associate", response_model=MaterialOut)
def associate_material(
    project_id: str, material_id: str, payload: MaterialAssociateInput, session: Session = Depends(get_session)
) -> dict:
    return _out(material_store.associate(session, material_id, ref_kind=payload.ref_kind, ref_id=payload.ref_id))


@router.post("/{project_id}/materials/{material_id}/abandon", response_model=MaterialOut)
def abandon_material(project_id: str, material_id: str, session: Session = Depends(get_session)) -> dict:
    return _out(material_store.abandon(session, material_id))