# backend/app/api/brands_api.py
"""品牌管理 API — /api/brands"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.database import get_db
from app.models.schemas import ModelRecord, BrandAlias

router = APIRouter(prefix="/api/brands", tags=["brands"])


class BrandOut(BaseModel):
    brand_code:  str
    brand_name:  Optional[str] = None
    model_count: int
    alias_count: int


class BrandAliasOut(BaseModel):
    id:         int
    alias_name: str
    brand_code: str
    is_active:  int = 1

    model_config = {"from_attributes": True}


class BrandAliasCreate(BaseModel):
    alias_name: str


@router.get("", response_model=list[BrandOut])
def list_brands(db: Session = Depends(get_db)):
    """返回所有品牌（来自 models 表），聚合型号数和别名数。"""
    brand_rows = (
        db.query(
            ModelRecord.brand_code,
            func.max(ModelRecord.brand_name).label("brand_name"),
            func.count(ModelRecord.id).label("model_count"),
        )
        .filter(ModelRecord.brand_code.isnot(None))
        .group_by(ModelRecord.brand_code)
        .order_by(ModelRecord.brand_code)
        .all()
    )
    alias_counts: dict[str, int] = dict(
        db.query(BrandAlias.brand_code, func.count(BrandAlias.id))
        .group_by(BrandAlias.brand_code)
        .all()
    )
    return [
        BrandOut(
            brand_code=r.brand_code,
            brand_name=r.brand_name,
            model_count=r.model_count,
            alias_count=alias_counts.get(r.brand_code, 0),
        )
        for r in brand_rows
    ]


@router.get("/{brand_code}/aliases", response_model=list[BrandAliasOut])
def list_brand_aliases(brand_code: str, db: Session = Depends(get_db)):
    return (
        db.query(BrandAlias)
        .filter(BrandAlias.brand_code == brand_code)
        .order_by(BrandAlias.alias_name)
        .all()
    )


@router.post("/{brand_code}/aliases", response_model=BrandAliasOut, status_code=201)
def create_brand_alias(brand_code: str, payload: BrandAliasCreate, db: Session = Depends(get_db)):
    if db.query(BrandAlias).filter(BrandAlias.alias_name == payload.alias_name).first():
        raise HTTPException(status_code=409, detail=f"别名 '{payload.alias_name}' 已存在")
    alias = BrandAlias(alias_name=payload.alias_name.strip(), brand_code=brand_code)
    db.add(alias)
    db.commit()
    db.refresh(alias)
    return alias


@router.delete("/{brand_code}/aliases/{alias_id}", status_code=204)
def delete_brand_alias(brand_code: str, alias_id: int, db: Session = Depends(get_db)):
    alias = db.query(BrandAlias).filter(
        BrandAlias.id == alias_id,
        BrandAlias.brand_code == brand_code,
    ).first()
    if not alias:
        raise HTTPException(status_code=404, detail="别名不存在")
    db.delete(alias)
    db.commit()
