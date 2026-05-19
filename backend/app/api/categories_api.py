# backend/app/api/categories_api.py
"""品类管理 API — /api/categories"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.models.database import get_db
from app.models.schemas import Category, ModelRecord, MetadataSpec, CategoryOut, CategoryCreate

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


@router.get("/tree", response_model=list[CategoryTreeNode])
def get_category_tree(db: Session = Depends(get_db)):
    """返回品类嵌套树，父→子结构。"""
    cats = db.query(Category).order_by(Category.sort_order, Category.name).all()
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


@router.get("", response_model=list[CategoryOut])
def list_categories(db: Session = Depends(get_db)):
    return db.query(Category).order_by(Category.sort_order, Category.name).all()


@router.post("", response_model=CategoryOut, status_code=201)
def create_category(payload: CategoryCreate, db: Session = Depends(get_db)):
    if db.query(Category).filter(Category.code == payload.code).first():
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
def update_category(category_id: int, payload: CategoryUpdate, db: Session = Depends(get_db)):
    cat = db.query(Category).filter(Category.id == category_id).first()
    if not cat:
        raise HTTPException(status_code=404, detail="品类不存在")
    if "name" in payload.model_fields_set and payload.name is not None:
        cat.name = payload.name.strip()
    if "parent_code" in payload.model_fields_set:
        cat.parent_code = payload.parent_code   # handles null → None correctly
        # Cycle check: walk up from the proposed parent, ensure we never reach cat.code
        if payload.parent_code:
            all_cats = {c.code: c for c in db.query(Category).all()}
            cursor = payload.parent_code
            visited: set = set()
            while cursor:
                if cursor == cat.code:
                    db.rollback()
                    raise HTTPException(status_code=422, detail="不能将品类设为自身的后代")
                if cursor in visited:
                    break
                visited.add(cursor)
                parent = all_cats.get(cursor)
                cursor = parent.parent_code if parent else None
    if "sort_order" in payload.model_fields_set:
        cat.sort_order = payload.sort_order
    db.commit()
    db.refresh(cat)
    return cat


@router.delete("/{category_id}", status_code=204)
def delete_category(category_id: int, db: Session = Depends(get_db)):
    cat = db.query(Category).filter(Category.id == category_id).first()
    if not cat:
        raise HTTPException(status_code=404, detail="品类不存在")
    model_count = db.query(ModelRecord).filter(ModelRecord.category_code == cat.code).count()
    if model_count:
        raise HTTPException(status_code=409, detail=f"品类下存在 {model_count} 个型号，请先处理")
    spec_count = db.query(MetadataSpec).filter(MetadataSpec.category_code == cat.code).count()
    if spec_count:
        raise HTTPException(status_code=409, detail=f"品类下存在 {spec_count} 条元数据规格，请先处理")
    db.delete(cat)
    db.commit()
