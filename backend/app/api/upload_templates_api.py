"""
Column template CRUD API.
GET    /api/upload/templates         — list all templates
POST   /api/upload/templates         — create template
PUT    /api/upload/templates/{id}    — update template
DELETE /api/upload/templates/{id}    — delete non-builtin template
"""
import hashlib
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.models.database import get_db
from app.models.schemas import ColumnTemplate, ColumnTemplateIn, ColumnTemplateOut

router = APIRouter(prefix="/api/upload/templates", tags=["upload-templates"])


def _fingerprint(mapping: dict) -> str:
    cols = sorted(mapping.keys())
    return hashlib.md5(",".join(cols).encode()).hexdigest()


@router.get("", response_model=list[ColumnTemplateOut])
def list_templates(db: Session = Depends(get_db)):
    return db.query(ColumnTemplate).order_by(
        ColumnTemplate.is_builtin.desc(), ColumnTemplate.id
    ).all()


@router.post("", response_model=ColumnTemplateOut)
def create_template(payload: ColumnTemplateIn, db: Session = Depends(get_db)):
    obj = ColumnTemplate(
        name=payload.name,
        platform=payload.platform,
        col_fingerprint=_fingerprint(payload.mapping),
        mapping=payload.mapping,
        ignore_columns=payload.ignore_columns,
        is_builtin=0,
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.put("/{template_id}", response_model=ColumnTemplateOut)
def update_template(
    template_id: int, payload: ColumnTemplateIn, db: Session = Depends(get_db)
):
    obj = db.query(ColumnTemplate).filter(ColumnTemplate.id == template_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="模板不存在")
    obj.name = payload.name
    obj.platform = payload.platform
    obj.col_fingerprint = _fingerprint(payload.mapping)
    obj.mapping = payload.mapping
    obj.ignore_columns = payload.ignore_columns
    db.commit()
    db.refresh(obj)
    return obj


@router.delete("/{template_id}")
def delete_template(template_id: int, db: Session = Depends(get_db)):
    obj = db.query(ColumnTemplate).filter(ColumnTemplate.id == template_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="模板不存在")
    if obj.is_builtin:
        raise HTTPException(status_code=403, detail="内置模板不可删除")
    db.delete(obj)
    db.commit()
    return {"message": "已删除"}
