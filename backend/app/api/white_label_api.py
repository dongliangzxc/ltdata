"""白牌/公模归类配置 API。

- /api/white-label/policies  品类级开关与模式
- /api/white-label/models    可选占位型号（无品牌/其他品牌下）
- /api/white-label/rules     关键词 → 占位型号规则
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.auth_deps import get_current_user
from app.core.permissions import visible_category_codes
from app.models.database import get_db
from app.models.schemas import Category, ModelRecord, User, WhiteLabelPolicy, WhiteLabelRule

router = APIRouter(prefix="/api/white-label", tags=["white-label"])

_GENERIC_BRAND_CODES = {
    "其他", "其他品牌", "无品牌", "未知品牌", "未知", "未识别品牌", "UNKNOWN", "OTHER",
}
_MODES = {"off", "suggest", "auto"}
_MATCH_TYPES = {"contains", "exact"}


def _visible_codes(db: Session, current_user: User) -> set[str] | None:
    all_codes = [code for code, in db.query(Category.code).all()]
    if not all_codes:
        return None
    return set(visible_category_codes(current_user, all_codes))


def _ensure_visible(db: Session, current_user: User, category_code: str) -> None:
    codes = _visible_codes(db, current_user)
    if codes is not None and category_code not in codes:
        raise HTTPException(status_code=403, detail="无权限访问该品类")


def _ensure_category(db: Session, category_code: str) -> Category:
    category = db.query(Category).filter(Category.code == category_code).first()
    if not category:
        raise HTTPException(status_code=404, detail=f"品类码 '{category_code}' 不存在")
    return category


def _validate_placeholder_model(db: Session, category_code: str, model_id: int) -> ModelRecord:
    model = db.query(ModelRecord).filter(ModelRecord.id == model_id).first()
    if not model:
        raise HTTPException(status_code=400, detail="型号不存在")
    if model.category_code != category_code:
        raise HTTPException(status_code=400, detail="型号不属于所选品类")
    if (model.brand_code or "").upper() not in {code.upper() for code in _GENERIC_BRAND_CODES}:
        raise HTTPException(status_code=400, detail="只能选择无品牌/其他品牌下的占位型号")
    return model


def _policy_payload(category: Category, policy: Optional[WhiteLabelPolicy]) -> dict:
    return {
        "category_code": category.code,
        "category_name": category.name,
        "enabled": bool(policy.enabled) if policy else False,
        "mode": policy.mode if policy else "off",
        "brand_code": policy.brand_code if policy else "无品牌",
        "unmatched_model_id": policy.unmatched_model_id if policy else None,
    }


class WhiteLabelPolicyIn(BaseModel):
    enabled: bool = False
    mode: str = "off"
    brand_code: str = "无品牌"
    unmatched_model_id: Optional[int] = None


class WhiteLabelRuleIn(BaseModel):
    category_code: str
    keyword: str
    match_type: str = "contains"
    model_id: int
    priority: int = 100
    is_active: bool = True


class WhiteLabelRulePatch(BaseModel):
    keyword: Optional[str] = None
    match_type: Optional[str] = None
    model_id: Optional[int] = None
    priority: Optional[int] = None
    is_active: Optional[bool] = None


def _rule_payload(rule: WhiteLabelRule, model: ModelRecord | None) -> dict:
    return {
        "id": rule.id,
        "category_code": rule.category_code,
        "keyword": rule.keyword,
        "match_type": rule.match_type,
        "model_id": rule.model_id,
        "model_code": model.model_code if model else None,
        "model_name": model.model_name if model else None,
        "brand_code": model.brand_code if model else None,
        "priority": rule.priority,
        "is_active": bool(rule.is_active),
    }


@router.get("/policies")
def list_policies(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    categories = (
        db.query(Category)
        .order_by(Category.sort_order, Category.name)
        .all()
    )
    policies = {p.category_code: p for p in db.query(WhiteLabelPolicy).all()}
    visible = _visible_codes(db, current_user)
    return [
        _policy_payload(category, policies.get(category.code))
        for category in categories
        if visible is None or category.code in visible
    ]


@router.put("/policies/{category_code}")
def upsert_policy(
    category_code: str,
    payload: WhiteLabelPolicyIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ensure_visible(db, current_user, category_code)
    _ensure_category(db, category_code)
    if payload.mode not in _MODES:
        raise HTTPException(status_code=400, detail="mode 只能是 off / suggest / auto")
    if payload.unmatched_model_id is not None:
        _validate_placeholder_model(db, category_code, payload.unmatched_model_id)

    policy = (
        db.query(WhiteLabelPolicy)
        .filter(WhiteLabelPolicy.category_code == category_code)
        .first()
    )
    if policy is None:
        policy = WhiteLabelPolicy(category_code=category_code)
        db.add(policy)
    policy.enabled = 1 if payload.enabled else 0
    policy.mode = payload.mode
    policy.brand_code = (payload.brand_code or "无品牌").strip() or "无品牌"
    policy.unmatched_model_id = payload.unmatched_model_id
    db.commit()
    db.refresh(policy)
    category = _ensure_category(db, category_code)
    return _policy_payload(category, policy)


@router.get("/models")
def list_placeholder_models(
    category_code: str = Query(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ensure_visible(db, current_user, category_code)
    _ensure_category(db, category_code)
    rows = (
        db.query(ModelRecord)
        .filter(ModelRecord.category_code == category_code)
        .order_by(ModelRecord.brand_code, ModelRecord.model_code)
        .all()
    )
    return [
        {
            "id": model.id,
            "brand_code": model.brand_code,
            "model_code": model.model_code,
            "model_name": model.model_name,
        }
        for model in rows
        if (model.brand_code or "").upper() in {code.upper() for code in _GENERIC_BRAND_CODES}
    ]


@router.get("/rules")
def list_rules(
    category_code: str = Query(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ensure_visible(db, current_user, category_code)
    rows = (
        db.query(WhiteLabelRule)
        .filter(WhiteLabelRule.category_code == category_code)
        .order_by(WhiteLabelRule.priority, WhiteLabelRule.id)
        .all()
    )
    model_ids = {row.model_id for row in rows}
    models = {
        model.id: model
        for model in db.query(ModelRecord).filter(ModelRecord.id.in_(model_ids)).all()
    } if model_ids else {}
    return [_rule_payload(row, models.get(row.model_id)) for row in rows]


@router.post("/rules", status_code=201)
def create_rule(
    payload: WhiteLabelRuleIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ensure_visible(db, current_user, payload.category_code)
    _ensure_category(db, payload.category_code)
    if payload.match_type not in _MATCH_TYPES:
        raise HTTPException(status_code=400, detail="match_type 只能是 contains 或 exact")
    keyword = (payload.keyword or "").strip()
    if not keyword:
        raise HTTPException(status_code=400, detail="关键词不能为空")
    model = _validate_placeholder_model(db, payload.category_code, payload.model_id)

    rule = WhiteLabelRule(
        category_code=payload.category_code,
        keyword=keyword,
        match_type=payload.match_type,
        model_id=payload.model_id,
        priority=payload.priority,
        is_active=1 if payload.is_active else 0,
    )
    db.add(rule)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="该品类下关键词与型号的组合已存在")
    db.refresh(rule)
    return _rule_payload(rule, model)


@router.patch("/rules/{rule_id}")
def update_rule(
    rule_id: int,
    payload: WhiteLabelRulePatch,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rule = db.query(WhiteLabelRule).filter(WhiteLabelRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="规则不存在")
    _ensure_visible(db, current_user, rule.category_code)

    if payload.match_type is not None and payload.match_type not in _MATCH_TYPES:
        raise HTTPException(status_code=400, detail="match_type 只能是 contains 或 exact")
    if payload.keyword is not None:
        keyword = payload.keyword.strip()
        if not keyword:
            raise HTTPException(status_code=400, detail="关键词不能为空")
        rule.keyword = keyword
    if payload.match_type is not None:
        rule.match_type = payload.match_type
    if payload.model_id is not None:
        _validate_placeholder_model(db, rule.category_code, payload.model_id)
        rule.model_id = payload.model_id
    if payload.priority is not None:
        rule.priority = payload.priority
    if payload.is_active is not None:
        rule.is_active = 1 if payload.is_active else 0
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="该品类下关键词与型号的组合已存在")
    db.refresh(rule)
    model = db.query(ModelRecord).filter(ModelRecord.id == rule.model_id).first()
    return _rule_payload(rule, model)


@router.delete("/rules/{rule_id}", status_code=204)
def delete_rule(
    rule_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rule = db.query(WhiteLabelRule).filter(WhiteLabelRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="规则不存在")
    _ensure_visible(db, current_user, rule.category_code)
    db.delete(rule)
    db.commit()
