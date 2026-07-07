# backend/app/api/brands_api.py
"""品牌管理 API — /api/brands"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.database import get_db
from app.models.schemas import BrandRecord, ModelRecord, BrandAlias, BrandIn, BrandOut

router = APIRouter(prefix="/api/brands", tags=["brands"])


class BrandAliasOut(BaseModel):
    id:         int
    alias_name: str
    brand_code: str
    is_active:  int = 1

    model_config = {"from_attributes": True}


class BrandAliasCreate(BaseModel):
    alias_name: str


def _clean_brand_code(value: str | None) -> str:
    return (value or "").strip()


def _clean_optional_text(value: str | None) -> str | None:
    cleaned = (value or "").strip()
    return cleaned or None


def _is_placeholder_brand_code(value: str) -> bool:
    return not value or set(value) == {"-"}


@router.get("", response_model=list[BrandOut])
def list_brands(db: Session = Depends(get_db)):
    """返回品牌主数据列表，附带型号数、别名数、覆盖品类。"""
    brands = db.query(BrandRecord).order_by(BrandRecord.brand_code).all()
    normalized_brand_code = func.trim(ModelRecord.brand_code)
    model_counts: dict[str, int] = dict(
        db.query(normalized_brand_code, func.count(ModelRecord.id))
        .filter(ModelRecord.brand_code.isnot(None))
        .group_by(normalized_brand_code)
        .all()
    )
    alias_counts: dict[str, int] = dict(
        db.query(BrandAlias.brand_code, func.count(BrandAlias.id))
        .group_by(BrandAlias.brand_code)
        .all()
    )
    # 一个品牌下型号跨品类时，全部按品类码升序列出。
    category_rows = (
        db.query(normalized_brand_code, ModelRecord.category_code)
        .filter(
            ModelRecord.brand_code.isnot(None),
            ModelRecord.category_code.isnot(None),
            ModelRecord.category_code != "",
        )
        .distinct()
        .all()
    )
    category_map: dict[str, list[str]] = {}
    for brand_code, category_code in category_rows:
        category_map.setdefault(brand_code, []).append(category_code)
    for codes in category_map.values():
        codes.sort()

    return [
        BrandOut(
            brand_code=brand.brand_code,
            brand_name=brand.brand_name,
            original_brand_name=brand.original_brand_name,
            category_codes=category_map.get(brand.brand_code, []),
            model_count=model_counts.get(brand.brand_code, 0),
            alias_count=alias_counts.get(brand.brand_code, 0),
        )
        for brand in brands
    ]


@router.post("", response_model=BrandOut, status_code=201)
def create_brand(payload: BrandIn, db: Session = Depends(get_db)):
    brand_code = _clean_brand_code(payload.brand_code)
    if _is_placeholder_brand_code(brand_code):
        raise HTTPException(status_code=400, detail="品牌码不能为空或占位符")

    if db.query(BrandRecord).filter(BrandRecord.brand_code == brand_code).first():
        raise HTTPException(status_code=409, detail="品牌已存在，可直接选择")

    brand_name = _clean_optional_text(payload.brand_name)
    brand = BrandRecord(
        brand_code=brand_code,
        brand_name=brand_name,
        # 首次创建时锁定为原始上传名，后续修改 brand_name 不会覆盖它。
        original_brand_name=brand_name,
        status="active",
    )
    db.add(brand)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="品牌已存在，可直接选择")
    db.refresh(brand)
    return BrandOut(
        brand_code=brand.brand_code,
        brand_name=brand.brand_name,
        original_brand_name=brand.original_brand_name,
        category_codes=[],
        model_count=0,
        alias_count=0,
    )


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
