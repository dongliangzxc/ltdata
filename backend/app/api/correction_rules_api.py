"""修正规则 CRUD API"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.core.auth_deps import get_current_user
from app.core.permissions import visible_category_codes
from app.models.database import get_db
from app.models.schemas import Category, CorrectionRule, CorrectionRuleIn, CorrectionRuleOut, User
from app.services.correction_engine import apply_correction_rules

router = APIRouter(prefix="/api/correction-rules", tags=["correction-rules"])


def _visible_correction_category_codes(db: Session, current_user: User) -> set[str] | None:
    if getattr(current_user, "is_admin", 0) == 1:
        return None
    if not getattr(current_user, "category_permissions", None):
        return None
    all_codes = [code for code, in db.query(Category.code).order_by(Category.sort_order, Category.name).all()]
    if not all_codes:
        return None
    return set(visible_category_codes(current_user, all_codes))


def _ensure_correction_category_visible(db: Session, current_user: User, category_code: str | None) -> None:
    if not category_code:
        return
    visible_codes = _visible_correction_category_codes(db, current_user)
    if visible_codes is not None and category_code not in visible_codes:
        raise HTTPException(status_code=403, detail="无权限访问该品类")


@router.get("", response_model=list[CorrectionRuleOut])
def list_rules(
    category_code: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ensure_correction_category_visible(db, current_user, category_code)
    q = db.query(CorrectionRule).order_by(CorrectionRule.priority, CorrectionRule.id)
    visible_codes = _visible_correction_category_codes(db, current_user)
    if visible_codes is not None:
        q = q.filter(CorrectionRule.category_code.in_(visible_codes))
    if category_code:
        q = q.filter(CorrectionRule.category_code == category_code)
    return q.all()


@router.post("", response_model=CorrectionRuleOut, status_code=201)
def create_rule(
    payload: CorrectionRuleIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ensure_correction_category_visible(db, current_user, payload.category_code)
    rule = CorrectionRule(**payload.model_dump())
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


@router.put("/{rule_id}", response_model=CorrectionRuleOut)
def update_rule(
    rule_id: int,
    payload: CorrectionRuleIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rule = db.query(CorrectionRule).filter(CorrectionRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="规则不存在")
    _ensure_correction_category_visible(db, current_user, rule.category_code)
    values = payload.model_dump()
    _ensure_correction_category_visible(db, current_user, values.get("category_code"))
    for k, v in values.items():
        setattr(rule, k, v)
    db.commit()
    db.refresh(rule)
    return rule


@router.delete("/{rule_id}", status_code=204)
def delete_rule(
    rule_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rule = db.query(CorrectionRule).filter(CorrectionRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="规则不存在")
    _ensure_correction_category_visible(db, current_user, rule.category_code)
    db.delete(rule)
    db.commit()


@router.post("/apply/{clean_job_id}")
def apply_rules(clean_job_id: int, db: Session = Depends(get_db)):
    """手动对某清洗任务重跑修正规则"""
    result = apply_correction_rules(db, clean_job_id)
    return {"clean_job_id": clean_job_id, **result}
