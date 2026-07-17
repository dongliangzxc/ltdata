# backend/app/api/brands_api.py
"""品牌管理 API — /api/brands"""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.database import get_db
from app.models.schemas import BrandRecord, ModelRecord, BrandAlias, BrandIn, BrandOut, PaginatedResponse

router = APIRouter(prefix="/api/brands", tags=["brands"])


class BrandAliasOut(BaseModel):
    id:         int
    alias_name: str
    brand_code: str
    is_active:  int = 1

    model_config = {"from_attributes": True}


class BrandAliasCreate(BaseModel):
    alias_name: str


class BrandAliasUpdate(BaseModel):
    alias_name: str


class BrandUpdate(BaseModel):
    brand_name: str | None = None
    alias_name: str | None = None


def _clean_brand_code(value: str | None) -> str:
    return (value or "").strip()


def _clean_optional_text(value: str | None) -> str | None:
    cleaned = (value or "").strip()
    return cleaned or None


def _first_text(*values: str | None) -> str | None:
    for value in values:
        cleaned = _clean_optional_text(value)
        if cleaned:
            return cleaned
    return None


def _sync_brand_form_alias(db: Session, brand: BrandRecord, alias_name: str | None) -> None:
    current_alias_name = _clean_optional_text(brand.brand_alias_name)
    cleaned_alias_name = _clean_optional_text(alias_name)
    alias = None
    if current_alias_name:
        alias = db.query(BrandAlias).filter(
            BrandAlias.brand_code == brand.brand_code,
            BrandAlias.alias_name == current_alias_name,
        ).first()

    if not cleaned_alias_name:
        if alias:
            db.delete(alias)
        brand.brand_alias_name = None
        return

    existing_alias = db.query(BrandAlias).filter(
        BrandAlias.brand_code == brand.brand_code,
        BrandAlias.alias_name == cleaned_alias_name,
    ).first()
    if existing_alias and (not alias or existing_alias.id != alias.id):
        if alias:
            db.delete(alias)
    elif alias:
        alias.alias_name = cleaned_alias_name
    else:
        db.add(BrandAlias(alias_name=cleaned_alias_name, brand_code=brand.brand_code))
    brand.brand_alias_name = cleaned_alias_name


def _is_placeholder_brand_code(value: str) -> bool:
    return not value or set(value) == {"-"}


def _build_brand_outs(db: Session, brands: list[BrandRecord]) -> list[BrandOut]:
    if not brands:
        return []

    brand_codes = [brand.brand_code for brand in brands]
    normalized_brand_code = func.trim(ModelRecord.brand_code)
    model_counts: dict[str, int] = dict(
        db.query(normalized_brand_code, func.count(ModelRecord.id))
        .filter(ModelRecord.brand_code.isnot(None), normalized_brand_code.in_(brand_codes))
        .group_by(normalized_brand_code)
        .all()
    )
    alias_counts: dict[str, int] = dict(
        db.query(BrandAlias.brand_code, func.count(BrandAlias.id))
        .filter(BrandAlias.brand_code.in_(brand_codes))
        .group_by(BrandAlias.brand_code)
        .all()
    )
    model_brand_names: dict[str, str] = {}
    category_map: dict[str, set[str]] = {}
    for brand_code, brand_name, category_code in (
        db.query(normalized_brand_code, ModelRecord.brand_name, ModelRecord.category_code)
        .filter(ModelRecord.brand_code.isnot(None), normalized_brand_code.in_(brand_codes))
        .all()
    ):
        if not brand_code:
            continue
        if brand_name and brand_code not in model_brand_names:
            model_brand_names[brand_code] = brand_name
        if category_code:
            category_map.setdefault(brand_code, set()).add(category_code)
    category_codes_by_brand = {
        brand_code: sorted(codes)
        for brand_code, codes in category_map.items()
    }

    return [
        BrandOut(
            brand_code=brand.brand_code,
            brand_name=_first_text(brand.brand_name, model_brand_names.get(brand.brand_code)),
            original_brand_name=_first_text(brand.original_brand_name, brand.brand_name, model_brand_names.get(brand.brand_code)),
            category_codes=category_codes_by_brand.get(brand.brand_code, []),
            model_count=model_counts.get(brand.brand_code, 0),
            alias_count=alias_counts.get(brand.brand_code, 0),
            brand_alias_name=brand.brand_alias_name,
        )
        for brand in brands
    ]


@router.get("", response_model=PaginatedResponse)
def list_brands(
    keyword: str | None = Query(None),
    category_code: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=2000),
    db: Session = Depends(get_db),
):
    """返回分页品牌主数据列表，附带型号数、别名数、覆盖品类。"""
    normalized_model_brand_code = func.trim(ModelRecord.brand_code)
    query = db.query(BrandRecord)

    cleaned_keyword = (keyword or "").strip()
    if cleaned_keyword:
        pattern = f"%{cleaned_keyword}%"
        keyword_brand_codes = (
            db.query(normalized_model_brand_code)
            .filter(
                ModelRecord.brand_code.isnot(None),
                ModelRecord.brand_name.ilike(pattern),
            )
            .distinct()
        )
        query = query.filter(
            BrandRecord.brand_code.ilike(pattern) |
            BrandRecord.brand_name.ilike(pattern) |
            BrandRecord.original_brand_name.ilike(pattern) |
            BrandRecord.brand_code.in_(keyword_brand_codes)
        )

    cleaned_category_code = (category_code or "").strip()
    if cleaned_category_code:
        category_brand_codes = (
            db.query(normalized_model_brand_code)
            .filter(
                ModelRecord.brand_code.isnot(None),
                ModelRecord.category_code == cleaned_category_code,
            )
            .distinct()
        )
        query = query.filter(BrandRecord.brand_code.in_(category_brand_codes))

    total = query.count()
    brands = (
        query.order_by(BrandRecord.brand_code)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return PaginatedResponse(
        total=total,
        page=page,
        page_size=page_size,
        items=_build_brand_outs(db, brands),
    )


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
    _sync_brand_form_alias(db, brand, payload.alias_name)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="品牌已存在，可直接选择")
    db.refresh(brand)
    return _build_brand_outs(db, [brand])[0]


@router.patch("/{brand_code}", response_model=BrandOut)
def update_brand(brand_code: str, payload: BrandUpdate, db: Session = Depends(get_db)):
    brand = db.query(BrandRecord).filter(BrandRecord.brand_code == brand_code).first()
    if not brand:
        raise HTTPException(status_code=404, detail="品牌不存在")

    cleaned_name = payload.brand_name.strip() if payload.brand_name is not None else None
    cleaned_alias_name = payload.alias_name.strip() if payload.alias_name is not None else None

    brand.brand_name = cleaned_name or None
    if payload.alias_name is not None:
        _sync_brand_form_alias(db, brand, cleaned_alias_name)
    db.commit()
    db.refresh(brand)
    # 编辑响应必须精确反映 brands.brand_name（清空后为 None），
    # 不复用列表 API 的“回退到型号品牌名”行为。
    out = _build_brand_outs(db, [brand])[0]
    out.brand_name = brand.brand_name
    return out


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
    cleaned_alias_name = payload.alias_name.strip()
    if not cleaned_alias_name:
        raise HTTPException(status_code=400, detail="别名不能为空")
    if db.query(BrandAlias).filter(
        BrandAlias.brand_code == brand_code,
        BrandAlias.alias_name == cleaned_alias_name,
    ).first():
        raise HTTPException(status_code=409, detail=f"别名 '{cleaned_alias_name}' 已存在")
    alias = BrandAlias(alias_name=cleaned_alias_name, brand_code=brand_code)
    db.add(alias)
    db.commit()
    db.refresh(alias)
    return alias


@router.patch("/{brand_code}/aliases/{alias_id}", response_model=BrandAliasOut)
def update_brand_alias(brand_code: str, alias_id: int, payload: BrandAliasUpdate, db: Session = Depends(get_db)):
    cleaned_alias_name = payload.alias_name.strip()
    if not cleaned_alias_name:
        raise HTTPException(status_code=400, detail="别名不能为空")

    alias = db.query(BrandAlias).filter(BrandAlias.id == alias_id).first()
    if not alias or alias.brand_code != brand_code:
        raise HTTPException(status_code=404, detail="别名不存在")

    if cleaned_alias_name != alias.alias_name and db.query(BrandAlias).filter(
        BrandAlias.brand_code == brand_code,
        BrandAlias.alias_name == cleaned_alias_name,
    ).first():
        raise HTTPException(status_code=409, detail=f"别名 '{cleaned_alias_name}' 已存在")

    old_alias_name = alias.alias_name
    alias.alias_name = cleaned_alias_name
    brand = db.query(BrandRecord).filter(BrandRecord.brand_code == brand_code).first()
    if brand and _clean_optional_text(brand.brand_alias_name) == old_alias_name:
        brand.brand_alias_name = cleaned_alias_name
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
    brand = db.query(BrandRecord).filter(BrandRecord.brand_code == brand_code).first()
    if brand and _clean_optional_text(brand.brand_alias_name) == alias.alias_name:
        brand.brand_alias_name = None
    db.delete(alias)
    db.commit()
