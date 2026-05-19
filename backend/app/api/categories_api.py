# backend/app/api/categories_api.py
"""品类管理 API — /api/categories"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.models.database import get_db
from app.models.schemas import Category, ModelRecord, MetadataSpec, CategoryOut, CategoryCreate

router = APIRouter(prefix="/api/categories", tags=["categories"])


class CategoryNameUpdate(BaseModel):
    name: str


@router.get("", response_model=list[CategoryOut])
def list_categories(db: Session = Depends(get_db)):
    return db.query(Category).order_by(Category.name).all()


@router.post("", response_model=CategoryOut, status_code=201)
def create_category(payload: CategoryCreate, db: Session = Depends(get_db)):
    existing = db.query(Category).filter(Category.code == payload.code).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"品类码 {payload.code} 已存在")
    cat = Category(
        code=payload.code.strip(),
        name=payload.name.strip(),
        parent_code=payload.parent_code,
        sort_order=payload.sort_order,
    )
    db.add(cat)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail=f"品类码 {payload.code} 已存在")
    db.refresh(cat)
    return cat


@router.put("/{category_id}", response_model=CategoryOut)
def update_category(category_id: int, payload: CategoryNameUpdate, db: Session = Depends(get_db)):
    cat = db.query(Category).filter(Category.id == category_id).first()
    if not cat:
        raise HTTPException(status_code=404, detail="品类不存在")
    cat.name = payload.name.strip()
    db.commit()
    db.refresh(cat)
    return cat


@router.delete("/{category_id}", status_code=204)
def delete_category(category_id: int, db: Session = Depends(get_db)):
    cat = db.query(Category).filter(Category.id == category_id).first()
    if not cat:
        raise HTTPException(status_code=404, detail="品类不存在")
    # 检查关联数据
    model_count = db.query(ModelRecord).filter(ModelRecord.category_code == cat.code).count()
    if model_count:
        raise HTTPException(status_code=409, detail=f"品类下存在 {model_count} 个型号，请先处理")
    spec_count = db.query(MetadataSpec).filter(MetadataSpec.category_code == cat.code).count()
    if spec_count:
        raise HTTPException(status_code=409, detail=f"品类下存在 {spec_count} 条元数据规格，请先处理")
    db.delete(cat)
    db.commit()
