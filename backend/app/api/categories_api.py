# backend/app/api/categories_api.py
"""品类管理 API — /api/categories"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.core.auth_deps import get_current_user
from app.core.permissions import visible_category_codes
from app.models.database import get_db
from app.models.schemas import (
    Category, ModelRecord, MetadataSpec, CategoryOut, CategoryCreate,
    CategoryCustomField, CategoryCustomFieldIn, CategoryCustomFieldOut,
    CategoryCustomFieldPatch,
)

router = APIRouter(prefix="/api/categories", tags=["categories"])


class CategoryUpdate(BaseModel):
    name:        Optional[str] = None
    parent_code: Optional[str] = None
    sort_order:  Optional[int] = None


class CategoryTreeNode(BaseModel):
    id:          int
    code:        str
    name:        str
    parent_code: Optional[str] = None
    sort_order:  int = 0
    children:    list["CategoryTreeNode"] = []

    model_config = {"from_attributes": True}

CategoryTreeNode.model_rebuild()


def _category_scope_codes(db: Session, current_user) -> list[str] | None:
    all_codes = [code for code, in db.query(Category.code).order_by(Category.sort_order, Category.name).all()]
    if not all_codes:
        return None
    return visible_category_codes(current_user, all_codes)


def _ensure_category_in_scope(db: Session, current_user, category_code: str) -> None:
    scoped_codes = _category_scope_codes(db, current_user)
    if scoped_codes is not None and category_code not in scoped_codes:
        raise HTTPException(status_code=403, detail="无权限访问该品类")


@router.get("/tree", response_model=list[CategoryTreeNode])
def get_category_tree(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    """返回品类嵌套树，父→子结构。"""
    scoped_codes = _category_scope_codes(db, current_user)
    query = db.query(Category).order_by(Category.sort_order, Category.name)
    if scoped_codes is not None:
        query = query.filter(Category.code.in_(scoped_codes))
    cats = query.all()
    by_code: dict = {c.code: {
        "id": c.id,
        "code": c.code,
        "name": c.name,
        "parent_code": c.parent_code,
        "sort_order": c.sort_order,
        "children": [],
    } for c in cats}
    roots = []
    for c in cats:
        node = by_code[c.code]
        if c.parent_code and c.parent_code in by_code:
            by_code[c.parent_code]["children"].append(node)
        else:
            roots.append(node)
    return roots


@router.get("/all", response_model=list[CategoryOut])
def list_all_categories(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    return db.query(Category).order_by(Category.sort_order, Category.name).all()


def _optional_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _apply_custom_field_payload(row: CategoryCustomField, payload) -> None:
    if "field_label" in payload.model_fields_set and payload.field_label is not None:
        label = str(payload.field_label).strip()
        if not label:
            raise HTTPException(status_code=422, detail="字段展示名不能为空")
        row.field_label = label
    if "field_type" in payload.model_fields_set and payload.field_type is not None:
        field_type = str(payload.field_type).strip()
        if field_type not in {"enum", "text", "bool", "number"}:
            raise HTTPException(status_code=422, detail="字段类型仅支持 enum/text/bool/number")
        row.field_type = field_type
    for field in ("options", "default_value", "auto_keywords", "auto_value"):
        if field in payload.model_fields_set:
            setattr(row, field, _optional_text(getattr(payload, field)))
    for field in ("required", "export", "is_active"):
        if field in payload.model_fields_set and getattr(payload, field) is not None:
            setattr(row, field, 1 if getattr(payload, field) else 0)
    if "sort_order" in payload.model_fields_set and payload.sort_order is not None:
        row.sort_order = payload.sort_order


@router.get("/custom-fields", response_model=list[CategoryCustomFieldOut])
def list_custom_fields(
    category_code: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """品类清洗扩展字段配置列表。"""
    if category_code:
        _ensure_category_in_scope(db, current_user, category_code)
    rows = db.query(CategoryCustomField)
    if category_code:
        rows = rows.filter(CategoryCustomField.category_code == category_code)
    rows = rows.order_by(
        CategoryCustomField.category_code,
        CategoryCustomField.sort_order,
        CategoryCustomField.id,
    ).all()
    scoped_codes = _category_scope_codes(db, current_user)
    if scoped_codes is not None:
        rows = [row for row in rows if row.category_code in scoped_codes]
    return rows


@router.post("/custom-fields", response_model=CategoryCustomFieldOut, status_code=201)
def create_custom_field(
    payload: CategoryCustomFieldIn,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """为指定品类新增一个清洗扩展字段。"""
    category_code = payload.category_code.strip()
    if not db.query(Category).filter(Category.code == category_code).first():
        raise HTTPException(status_code=404, detail=f"品类码 '{category_code}' 不存在")
    _ensure_category_in_scope(db, current_user, category_code)
    if db.query(CategoryCustomField).filter(
        CategoryCustomField.category_code == category_code,
        CategoryCustomField.field_key == payload.field_key,
    ).first():
        raise HTTPException(status_code=409, detail="该品类下字段键已存在")

    row = CategoryCustomField(
        category_code=category_code,
        field_key=payload.field_key,
        field_label=payload.field_label.strip(),
        field_type=payload.field_type,
        options=_optional_text(payload.options),
        default_value=_optional_text(payload.default_value),
        auto_keywords=_optional_text(payload.auto_keywords),
        auto_value=_optional_text(payload.auto_value),
        required=1 if payload.required else 0,
        export=1 if payload.export else 0,
        sort_order=payload.sort_order,
        is_active=1 if payload.is_active else 0,
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="该品类下字段键已存在")
    db.refresh(row)
    return row


@router.patch("/custom-fields/{field_id}", response_model=CategoryCustomFieldOut)
def update_custom_field(
    field_id: int,
    payload: CategoryCustomFieldPatch,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    row = db.query(CategoryCustomField).filter(CategoryCustomField.id == field_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="扩展字段不存在")
    _ensure_category_in_scope(db, current_user, row.category_code)
    _apply_custom_field_payload(row, payload)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/custom-fields/{field_id}", status_code=204)
def delete_custom_field(
    field_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    row = db.query(CategoryCustomField).filter(CategoryCustomField.id == field_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="扩展字段不存在")
    _ensure_category_in_scope(db, current_user, row.category_code)
    db.delete(row)
    db.commit()


@router.get("", response_model=list[CategoryOut])
def list_categories(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    scoped_codes = _category_scope_codes(db, current_user)
    query = db.query(Category).order_by(Category.sort_order, Category.name)
    if scoped_codes is not None:
        query = query.filter(Category.code.in_(scoped_codes))
    return query.all()


@router.post("", response_model=CategoryOut, status_code=201)
def create_category(payload: CategoryCreate, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    if db.query(Category).filter(Category.code == payload.code).first():
        raise HTTPException(status_code=409, detail=f"品类码 {payload.code} 已存在")
    if payload.parent_code:
        if not db.query(Category).filter(Category.code == payload.parent_code).first():
            raise HTTPException(status_code=404, detail=f"父品类码 '{payload.parent_code}' 不存在")
        _ensure_category_in_scope(db, current_user, payload.parent_code)
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
def update_category(category_id: int, payload: CategoryUpdate, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    cat = db.query(Category).filter(Category.id == category_id).first()
    if not cat:
        raise HTTPException(status_code=404, detail="品类不存在")
    _ensure_category_in_scope(db, current_user, cat.code)
    if "name" in payload.model_fields_set and payload.name is not None:
        cat.name = payload.name.strip()
    if "parent_code" in payload.model_fields_set:
        # Validate proposed parent exists BEFORE cycle check
        if payload.parent_code:
            if not db.query(Category).filter(Category.code == payload.parent_code).first():
                raise HTTPException(status_code=404, detail=f"父品类码 '{payload.parent_code}' 不存在")
            _ensure_category_in_scope(db, current_user, payload.parent_code)
        # Cycle check BEFORE assignment (uses clean DB state)
        if payload.parent_code:
            all_cats = {c.code: c for c in db.query(Category).all()}
            cursor = payload.parent_code
            visited: set = set()
            while cursor:
                if cursor == cat.code:
                    raise HTTPException(status_code=422, detail="不能将品类设为自身的后代")
                if cursor in visited:
                    break
                visited.add(cursor)
                parent = all_cats.get(cursor)
                cursor = parent.parent_code if parent else None
        # Only assign after cycle check passes
        cat.parent_code = payload.parent_code
    if "sort_order" in payload.model_fields_set:
        cat.sort_order = payload.sort_order
    db.commit()
    db.refresh(cat)
    return cat


@router.delete("/{category_id}", status_code=204)
def delete_category(category_id: int, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    cat = db.query(Category).filter(Category.id == category_id).first()
    if not cat:
        raise HTTPException(status_code=404, detail="品类不存在")
    _ensure_category_in_scope(db, current_user, cat.code)
    child_count = db.query(Category).filter(Category.parent_code == cat.code).count()
    if child_count:
        raise HTTPException(status_code=409, detail=f"品类下存在 {child_count} 个子品类，请先处理")
    model_count = db.query(ModelRecord).filter(ModelRecord.category_code == cat.code).count()
    if model_count:
        raise HTTPException(status_code=409, detail=f"品类下存在 {model_count} 个型号，请先处理")
    spec_count = db.query(MetadataSpec).filter(MetadataSpec.category_code == cat.code).count()
    if spec_count:
        raise HTTPException(status_code=409, detail=f"品类下存在 {spec_count} 条元数据规格，请先处理")
    db.delete(cat)
    db.commit()
