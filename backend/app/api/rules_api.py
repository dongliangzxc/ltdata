"""
规则引擎管理 API
- /api/rules/noise-words     干扰词库
- /api/rules/brand-aliases   品牌写法库
- /api/rules/match-rules     显式匹配规则
- /api/rules/filtered-items  干扰项存档（含恢复）
- /api/rules/attr-rules      属性关键词规则（含 P10 批量导入）
"""
import math
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.models.database import get_db
from app.models.schemas import (
    NoiseWord, FilteredItem, BrandAlias, MatchRule,
    AttrRule, MatchResultAttr,
    RawDataRecord, CleanedDataRecord, ModelRecord,
    AttrRuleIn, AttrRuleOut,
    Category, InterventionRule, InterventionRuleIn,
    InterventionRulePatch,
)
from app.services.import_helper import save_tmp_file, read_columns, find_best_template, col_fingerprint
from app.utils.time_utils import format_beijing_datetime

UPLOAD_DIR = os.environ.get("UPLOAD_DIR", "./uploads")

router = APIRouter(prefix="/api/rules", tags=["rules"])


ALLOWED_PRICE_OPS = {"gt", "gte", "lt", "lte", "between"}
ALLOWED_CONDITION_KEYS = {
    "brand_in",
    "item_name_contains_any",
    "item_name_not_contains_any",
    "reference_price",
}


def _clean_string_list(value: object) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise HTTPException(400, "条件值必须是数组")
    return [str(item).strip() for item in value if str(item).strip()]


def _parse_price_number(value: object) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise HTTPException(400, "reference_price 数值必须是有效数字")
    if not math.isfinite(number):
        raise HTTPException(400, "reference_price 数值必须是有效数字")
    return number


def _validate_intervention_conditions(conditions: dict) -> dict:
    if not isinstance(conditions, dict):
        raise HTTPException(400, "conditions 必须是对象")

    unknown_keys = [key for key in conditions if key not in ALLOWED_CONDITION_KEYS]
    if unknown_keys:
        raise HTTPException(400, f"不支持的干预条件: {unknown_keys[0]}")

    cleaned: dict = {}
    for key in ("brand_in", "item_name_contains_any", "item_name_not_contains_any"):
        values = _clean_string_list(conditions.get(key))
        if values:
            cleaned[key] = values

    price = conditions.get("reference_price")
    if price:
        if not isinstance(price, dict):
            raise HTTPException(400, "reference_price 必须是对象")
        op = price.get("op")
        if op not in ALLOWED_PRICE_OPS:
            raise HTTPException(400, "reference_price op 必须是 gt/gte/lt/lte/between")
        if op == "between":
            if price.get("min") is None or price.get("max") is None:
                raise HTTPException(400, "reference_price between 必须包含 min 和 max")
            min_price = _parse_price_number(price["min"])
            max_price = _parse_price_number(price["max"])
            if min_price > max_price:
                raise HTTPException(400, "reference_price between 最低价不能大于最高价")
            cleaned["reference_price"] = {"op": op, "min": min_price, "max": max_price}
        else:
            if price.get("value") is None:
                raise HTTPException(400, "reference_price 比较必须包含 value")
            cleaned["reference_price"] = {"op": op, "value": _parse_price_number(price["value"])}

    if not cleaned:
        raise HTTPException(400, "至少填写一个干预条件")
    return cleaned


def _validate_intervention_rule_payload(body: InterventionRuleIn | InterventionRulePatch, db: Session) -> dict:
    values = body.model_dump(exclude_unset=True)
    if "category_code" in values:
        values["category_code"] = (values["category_code"] or "").strip()
        if not values["category_code"]:
            raise HTTPException(400, "category_code 不能为空")
        if not db.query(Category).filter(Category.code == values["category_code"]).first():
            raise HTTPException(400, f"品类码 {values['category_code']} 不存在")
    if "name" in values:
        values["name"] = (values["name"] or "").strip()
        if not values["name"]:
            raise HTTPException(400, "规则名称不能为空")
    if "action" in values and values["action"] not in ("filter", "allow"):
        raise HTTPException(400, "action 必须是 filter 或 allow")
    if "is_active" in values and values["is_active"] not in (0, 1):
        raise HTTPException(400, "is_active 必须是 0 或 1")
    if "conditions" in values:
        values["conditions"] = _validate_intervention_conditions(values["conditions"])
    return values


def _intervention_condition_summary(conditions: dict) -> str:
    parts = []
    if conditions.get("brand_in"):
        parts.append(f"品牌 in [{', '.join(conditions['brand_in'])}]")
    if conditions.get("item_name_contains_any"):
        parts.append(f"商品名称包含 [{', '.join(conditions['item_name_contains_any'])}]")
    if conditions.get("item_name_not_contains_any"):
        parts.append(f"商品名称不包含 [{', '.join(conditions['item_name_not_contains_any'])}]")
    price = conditions.get("reference_price")
    if price:
        op_label = {"gt": ">", "gte": ">=", "lt": "<", "lte": "<=", "between": "区间"}[price["op"]]
        if price["op"] == "between":
            parts.append(f"参考价格 {price['min']} - {price['max']}")
        else:
            parts.append(f"参考价格 {op_label} {price['value']:g}")
    return " 且 ".join(parts)


def _intervention_rule_to_dict(rule: InterventionRule) -> dict:
    return {
        "id": rule.id,
        "name": rule.name,
        "category_code": rule.category_code,
        "action": rule.action,
        "priority": rule.priority,
        "conditions": rule.conditions,
        "summary": _intervention_condition_summary(rule.conditions or {}),
        "is_active": rule.is_active,
        "created_at": format_beijing_datetime(rule.created_at),
        "updated_at": format_beijing_datetime(rule.updated_at),
    }


@router.get("/intervention-rules")
def list_intervention_rules(
    category_code: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    q = db.query(InterventionRule).order_by(InterventionRule.priority, InterventionRule.id)
    if category_code:
        q = q.filter(InterventionRule.category_code == category_code)
    return [_intervention_rule_to_dict(rule) for rule in q.all()]


@router.post("/intervention-rules", status_code=201)
def create_intervention_rule(body: InterventionRuleIn, db: Session = Depends(get_db)):
    values = _validate_intervention_rule_payload(body, db)
    if "category_code" not in values or not values["category_code"]:
        raise HTTPException(400, "category_code 不能为空")
    rule = InterventionRule(**values)
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return _intervention_rule_to_dict(rule)


@router.patch("/intervention-rules/{rule_id}")
def update_intervention_rule(rule_id: int, body: InterventionRulePatch, db: Session = Depends(get_db)):
    rule = db.query(InterventionRule).filter(InterventionRule.id == rule_id).first()
    if not rule:
        raise HTTPException(404, "干预规则不存在")
    values = _validate_intervention_rule_payload(body, db)
    for field, value in values.items():
        setattr(rule, field, value)
    db.commit()
    db.refresh(rule)
    return _intervention_rule_to_dict(rule)


@router.delete("/intervention-rules/{rule_id}", status_code=204)
def delete_intervention_rule(rule_id: int, db: Session = Depends(get_db)):
    rule = db.query(InterventionRule).filter(InterventionRule.id == rule_id).first()
    if not rule:
        raise HTTPException(404, "干预规则不存在")
    db.delete(rule)
    db.commit()


# ═══════════════════════════════════════════════════════════
# 干扰词库
# ═══════════════════════════════════════════════════════════

class NoiseWordIn(BaseModel):
    keyword: str
    match_field: str = "item_name"  # item_name / shop_name / brand_raw
    category_code: Optional[str] = None


@router.get("/noise-words")
def list_noise_words(
    category_code: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    q = db.query(NoiseWord).order_by(NoiseWord.created_at.desc())
    if category_code:
        q = q.filter(NoiseWord.category_code == category_code)
    rows = q.all()
    return [
        {
            "id": r.id,
            "keyword": r.keyword,
            "match_field": r.match_field,
            "is_active": r.is_active,
            "created_at": format_beijing_datetime(r.created_at),
            "category_code": r.category_code,
        }
        for r in rows
    ]


@router.post("/noise-words", status_code=201)
def create_noise_word(body: NoiseWordIn, db: Session = Depends(get_db)):
    if body.match_field not in ("item_name", "shop_name", "brand_raw"):
        raise HTTPException(400, "match_field 必须是 item_name / shop_name / brand_raw")
    existing = db.query(NoiseWord).filter(
        NoiseWord.keyword == body.keyword, NoiseWord.match_field == body.match_field
    ).first()
    if existing:
        raise HTTPException(400, "该关键词已存在")
    row = NoiseWord(
        keyword=body.keyword,
        match_field=body.match_field,
        category_code=body.category_code or None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "keyword": row.keyword, "match_field": row.match_field, "is_active": row.is_active}


@router.patch("/noise-words/{nw_id}")
def toggle_noise_word(nw_id: int, db: Session = Depends(get_db)):
    row = db.query(NoiseWord).filter(NoiseWord.id == nw_id).first()
    if not row:
        raise HTTPException(404, "干扰词不存在")
    row.is_active = 0 if row.is_active else 1
    db.commit()
    return {"id": row.id, "is_active": row.is_active}


@router.delete("/noise-words/{nw_id}", status_code=204)
def delete_noise_word(nw_id: int, db: Session = Depends(get_db)):
    row = db.query(NoiseWord).filter(NoiseWord.id == nw_id).first()
    if not row:
        raise HTTPException(404, "干扰词不存在")
    db.delete(row)
    db.commit()


# ═══════════════════════════════════════════════════════════
# 品牌写法库
# ═══════════════════════════════════════════════════════════

class BrandAliasIn(BaseModel):
    alias_name: str
    brand_code: str


@router.get("/brand-aliases")
def list_brand_aliases(db: Session = Depends(get_db)):
    rows = db.query(BrandAlias).order_by(BrandAlias.alias_name).all()
    return [
        {"id": r.id, "alias_name": r.alias_name, "brand_code": r.brand_code,
         "is_active": r.is_active, "created_at": format_beijing_datetime(r.created_at)}
        for r in rows
    ]


@router.post("/brand-aliases", status_code=201)
def create_brand_alias(body: BrandAliasIn, db: Session = Depends(get_db)):
    if db.query(BrandAlias).filter(BrandAlias.alias_name == body.alias_name).first():
        raise HTTPException(400, "该写法已存在")
    row = BrandAlias(alias_name=body.alias_name.strip(), brand_code=body.brand_code.strip().upper())
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "alias_name": row.alias_name, "brand_code": row.brand_code}


@router.post("/brand-aliases/import")
async def import_brand_aliases(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Excel 批量导入，需两列：alias_name / brand_code"""
    try:
        df = pd.read_excel(file.file, dtype=str)
    except Exception as e:
        raise HTTPException(400, f"Excel 解析失败：{e}")

    df.columns = [c.strip().lower() for c in df.columns]
    if "alias_name" not in df.columns or "brand_code" not in df.columns:
        raise HTTPException(400, "Excel 必须包含列：alias_name、brand_code")

    imported, skipped = 0, 0
    for _, row in df.iterrows():
        alias = str(row["alias_name"]).strip()
        brand = str(row["brand_code"]).strip().upper()
        if not alias or not brand:
            skipped += 1
            continue
        existing = db.query(BrandAlias).filter(BrandAlias.alias_name == alias).first()
        if existing:
            existing.brand_code = brand  # 已存在则更新
        else:
            db.add(BrandAlias(alias_name=alias, brand_code=brand))
        imported += 1

    db.commit()
    return {"imported": imported, "skipped": skipped}


@router.delete("/brand-aliases/{ba_id}", status_code=204)
def delete_brand_alias(ba_id: int, db: Session = Depends(get_db)):
    row = db.query(BrandAlias).filter(BrandAlias.id == ba_id).first()
    if not row:
        raise HTTPException(404, "品牌写法不存在")
    db.delete(row)
    db.commit()


# ═══════════════════════════════════════════════════════════
# 显式匹配规则
# ═══════════════════════════════════════════════════════════

class MatchRuleIn(BaseModel):
    keyword: str
    match_type: str = "contains"  # contains / exact
    model_id: int
    priority: int = 100


class MatchRuleUpdate(BaseModel):
    keyword: Optional[str] = None
    match_type: Optional[str] = None
    model_id: Optional[int] = None
    priority: Optional[int] = None
    is_active: Optional[int] = None


@router.get("/match-rules")
def list_match_rules(db: Session = Depends(get_db)):
    rows = db.query(MatchRule, ModelRecord).join(
        ModelRecord, MatchRule.model_id == ModelRecord.id
    ).order_by(MatchRule.priority).all()
    return [
        {
            "id": mr.id, "keyword": mr.keyword, "match_type": mr.match_type,
            "model_id": mr.model_id, "priority": mr.priority, "is_active": mr.is_active,
            "brand_code": m.brand_code, "model_code": m.model_code,
            "model_name": m.model_name, "created_at": format_beijing_datetime(mr.created_at),
        }
        for mr, m in rows
    ]


@router.post("/match-rules", status_code=201)
def create_match_rule(body: MatchRuleIn, db: Session = Depends(get_db)):
    if body.match_type not in ("contains", "exact"):
        raise HTTPException(400, "match_type 必须是 contains 或 exact")
    if not db.query(ModelRecord).filter(ModelRecord.id == body.model_id).first():
        raise HTTPException(404, "型号不存在")
    if db.query(MatchRule).filter(MatchRule.keyword == body.keyword).first():
        raise HTTPException(400, "该关键词规则已存在")
    row = MatchRule(
        keyword=body.keyword.strip(),
        match_type=body.match_type,
        model_id=body.model_id,
        priority=body.priority,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "keyword": row.keyword, "match_type": row.match_type,
            "model_id": row.model_id, "priority": row.priority}


@router.patch("/match-rules/{rule_id}")
def update_match_rule(rule_id: int, body: MatchRuleUpdate, db: Session = Depends(get_db)):
    row = db.query(MatchRule).filter(MatchRule.id == rule_id).first()
    if not row:
        raise HTTPException(404, "规则不存在")
    if body.keyword is not None:
        row.keyword = body.keyword.strip()
    if body.match_type is not None:
        if body.match_type not in ("contains", "exact"):
            raise HTTPException(400, "match_type 必须是 contains 或 exact")
        row.match_type = body.match_type
    if body.model_id is not None:
        if not db.query(ModelRecord).filter(ModelRecord.id == body.model_id).first():
            raise HTTPException(404, "型号不存在")
        row.model_id = body.model_id
    if body.priority is not None:
        row.priority = body.priority
    if body.is_active is not None:
        row.is_active = body.is_active
    db.commit()
    return {"id": row.id, "keyword": row.keyword, "priority": row.priority, "is_active": row.is_active}


@router.delete("/match-rules/{rule_id}", status_code=204)
def delete_match_rule(rule_id: int, db: Session = Depends(get_db)):
    row = db.query(MatchRule).filter(MatchRule.id == rule_id).first()
    if not row:
        raise HTTPException(404, "规则不存在")
    db.delete(row)
    db.commit()


# ═══════════════════════════════════════════════════════════
# 干扰项存档
# ═══════════════════════════════════════════════════════════

@router.get("/filtered-items")
def list_filtered_items(
    clean_job_id: Optional[int] = Query(None),
    keyword: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    q = (
        db.query(FilteredItem, RawDataRecord)
        .join(RawDataRecord, FilteredItem.raw_data_id == RawDataRecord.id)
        .filter(FilteredItem.is_recovered == 0)
    )
    if clean_job_id:
        q = q.filter(FilteredItem.clean_job_id == clean_job_id)
    if keyword:
        q = q.filter(
            (FilteredItem.matched_keyword.ilike(f"%{keyword}%")) |
            (FilteredItem.intervention_rule_name.ilike(f"%{keyword}%")) |
            (FilteredItem.matched_reason.ilike(f"%{keyword}%"))
        )

    total = q.count()
    rows = q.order_by(FilteredItem.id.desc()).offset((page - 1) * page_size).limit(page_size).all()

    items = [
        {
            "id": fi.id,
            "raw_data_id": fi.raw_data_id,
            "clean_job_id": fi.clean_job_id,
            "matched_keyword": fi.matched_keyword,
            "intervention_rule_id": fi.intervention_rule_id,
            "intervention_rule_name": fi.intervention_rule_name,
            "matched_reason": fi.matched_reason,
            "item_name": rd.item_name,
            "item_url": rd.item_url,
            "item_image": rd.item_image,
            "brand_raw": rd.brand_raw,
            "shop_name": rd.shop_name,
            "platform": rd.platform,
            "item_id": rd.item_id,
            "price": float(rd.price) if rd.price is not None else None,
            "sales_qty": rd.sales_qty,
            "sales_amount": float(rd.sales_amount) if rd.sales_amount is not None else None,
            "created_at": format_beijing_datetime(fi.created_at),
        }
        for fi, rd in rows
    ]
    return {"total": total, "page": page, "page_size": page_size, "items": items}


def _recover_one(fi: FilteredItem, db: Session) -> None:
    """将单条 filtered_item 恢复写回 cleaned_data，标记 is_recovered=1"""
    raw = db.query(RawDataRecord).filter(RawDataRecord.id == fi.raw_data_id).first()
    if not raw:
        raise HTTPException(404, f"raw_data_id={fi.raw_data_id} 不存在")

    db.add(CleanedDataRecord(
        raw_data_id=raw.id,
        clean_job_id=fi.clean_job_id,
        platform=raw.platform,
        month=raw.month,
        category_lv1=raw.category_lv1,
        category_lv2=raw.category_lv2,
        category_lv3=raw.category_lv3,
        category_lv4=raw.category_lv4,
        category_lv5=raw.category_lv5,
        item_id=raw.item_id,
        item_url=raw.item_url,
        item_name=raw.item_name,
        item_image=raw.item_image,
        ref_price=raw.ref_price,
        brand_raw=raw.brand_raw,
        shop_name=raw.shop_name,
        sales_qty=raw.sales_qty,
        sales_amount=raw.sales_amount,
        price=raw.price,
        brand_std=raw.brand_std or raw.brand_raw,
        model_std=raw.model_std,
        is_recovered=1,
    ))

    fi.is_recovered = 1
    fi.recovered_at = datetime.utcnow()


class BatchRecoverIn(BaseModel):
    ids: list[int]


@router.post("/filtered-items/recover-batch")
def recover_filtered_items_batch(body: BatchRecoverIn, db: Session = Depends(get_db)):
    rows = db.query(FilteredItem).filter(
        FilteredItem.id.in_(body.ids), FilteredItem.is_recovered == 0
    ).all()
    for fi in rows:
        _recover_one(fi, db)
    db.commit()
    return {"recovered": len(rows)}


@router.post("/filtered-items/{fi_id}/recover")
def recover_filtered_item(fi_id: int, db: Session = Depends(get_db)):
    fi = db.query(FilteredItem).filter(FilteredItem.id == fi_id, FilteredItem.is_recovered == 0).first()
    if not fi:
        raise HTTPException(404, "干扰项不存在或已恢复")
    _recover_one(fi, db)
    db.commit()
    return {"recovered": 1}


# ═══════════════════════════════════════════════════════════
# 属性关键词规则
# ═══════════════════════════════════════════════════════════

@router.get("/attr-rules/categories")
def list_attr_rule_categories(db: Session = Depends(get_db)):
    """返回 categories 表列表，供前端属性规则品类下拉使用"""
    rows = db.query(Category).order_by(Category.name).all()
    return [{"code": r.code, "name": r.name} for r in rows]


class AttrRulePatch(BaseModel):
    keyword:       Optional[str] = None
    match_type:    Optional[str] = None
    attr_name:     Optional[str] = None
    attr_value:    Optional[str] = None
    category_code: Optional[str] = None
    priority:      Optional[int] = None
    is_active:     Optional[int] = None


@router.post("/attr-rules/apply")
def apply_attr_rules(payload: dict, db: Session = Depends(get_db)):
    """对指定 match_job 的所有 matched/confirmed 结果重跑属性匹配"""
    from app.services.attribute_matcher import run_attribute_matching
    from app.models.schemas import MatchResult as MR

    match_job_id = payload.get("match_job_id")
    if not match_job_id:
        raise HTTPException(400, "match_job_id 不能为空")

    ids = [
        r.id for r in db.query(MR).filter(
            MR.clean_job_id == match_job_id,
            MR.match_status.in_(["matched", "confirmed", "url_matched"]),
        ).all()
    ]
    result = run_attribute_matching(db, ids)
    return result


@router.get("/attr-rules")
def list_attr_rules(
    category_code: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    q = db.query(AttrRule).order_by(AttrRule.priority, AttrRule.id)
    if category_code == "__global__":
        q = q.filter(AttrRule.category_code.is_(None))
    elif category_code:
        q = q.filter(AttrRule.category_code == category_code)
    rows = q.all()
    return [
        {
            "id": r.id, "keyword": r.keyword, "match_type": r.match_type,
            "attr_name": r.attr_name, "attr_value": r.attr_value,
            "category_code": r.category_code, "priority": r.priority,
            "is_active": r.is_active, "created_at": format_beijing_datetime(r.created_at),
        }
        for r in rows
    ]


@router.post("/attr-rules", status_code=201)
def create_attr_rule(body: AttrRuleIn, db: Session = Depends(get_db)):
    if body.match_type not in ("contains", "exact"):
        raise HTTPException(400, "match_type 必须是 contains 或 exact")
    if body.category_code:
        if not db.query(Category).filter(Category.code == body.category_code).first():
            raise HTTPException(400, f"品类码 {body.category_code} 不存在")
    existing = db.query(AttrRule).filter(
        AttrRule.keyword == body.keyword,
        AttrRule.attr_name == body.attr_name,
        AttrRule.category_code == body.category_code,
    ).first()
    if existing:
        raise HTTPException(400, "该关键词+属性名+品类组合已存在")
    row = AttrRule(
        keyword=body.keyword,
        match_type=body.match_type,
        attr_name=body.attr_name,
        attr_value=body.attr_value,
        category_code=body.category_code or None,
        priority=body.priority,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "keyword": row.keyword, "attr_name": row.attr_name,
            "attr_value": row.attr_value, "category_code": row.category_code,
            "priority": row.priority, "is_active": row.is_active}


@router.patch("/attr-rules/{rule_id}")
def update_attr_rule(rule_id: int, body: AttrRulePatch, db: Session = Depends(get_db)):
    row = db.query(AttrRule).filter(AttrRule.id == rule_id).first()
    if not row:
        raise HTTPException(404, "规则不存在")
    if body.category_code:
        if not db.query(Category).filter(Category.code == body.category_code).first():
            raise HTTPException(400, f"品类码 {body.category_code} 不存在")
    for field in ("keyword", "match_type", "attr_name", "attr_value", "priority", "is_active"):
        val = getattr(body, field)
        if val is not None:
            setattr(row, field, val)
    # category_code can be explicitly set to None (= global rule)
    if "category_code" in body.model_fields_set:
        row.category_code = body.category_code or None
    db.commit()
    return {"id": row.id, "keyword": row.keyword, "attr_name": row.attr_name,
            "attr_value": row.attr_value, "category_code": row.category_code,
            "priority": row.priority, "is_active": row.is_active}


@router.delete("/attr-rules/{rule_id}", status_code=204)
def delete_attr_rule(rule_id: int, db: Session = Depends(get_db)):
    row = db.query(AttrRule).filter(AttrRule.id == rule_id).first()
    if not row:
        raise HTTPException(404, "规则不存在")
    db.delete(row)
    db.commit()


# ─── P10: Attr-Rules Import ──────────────────────────────────────────────────

@router.post("/attr-rules/headers")
async def attr_rules_headers(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Step 1: save temp file, read columns, suggest mapping template."""
    temp_file_id, save_path, filename = await save_tmp_file(file, UPLOAD_DIR)
    columns = read_columns(save_path)
    best_tmpl, score = find_best_template(columns, "attr", db)
    return {
        "temp_file_id": temp_file_id,
        "filename": filename,
        "columns": columns,
        "suggested_template": {
            "id": best_tmpl.id,
            "name": best_tmpl.name,
            "mapping": best_tmpl.mapping,
            "ignore_columns": best_tmpl.ignore_columns or [],
        } if best_tmpl else None,
        "match_score": score,
    }


class AttrRulesConfirmPayload(BaseModel):
    temp_file_id: str
    mapping: dict
    ignore_columns: list = []
    category_code: str
    save_template_name: Optional[str] = None


@router.post("/attr-rules/confirm")
def attr_rules_confirm(
    payload: AttrRulesConfirmPayload,
    db: Session = Depends(get_db),
):
    """Step 2: parse file using mapping, insert attr_rules rows."""
    tmp_dir = Path(UPLOAD_DIR) / "tmp"
    # temp_file_id is the UUID prefix; find the actual file via glob
    matches = list(tmp_dir.glob(f"{payload.temp_file_id}_*"))
    if not matches:
        raise HTTPException(status_code=404, detail="临时文件不存在或已过期，请重新上传")
    file_path = matches[0]

    # Read file
    suffix = file_path.suffix.lower()
    if suffix == ".csv":
        try:
            df = pd.read_csv(file_path, dtype=str, encoding="utf-8-sig")
        except Exception:
            df = pd.read_csv(file_path, dtype=str, encoding="gbk")
    else:
        df = pd.read_excel(file_path, sheet_name=0, dtype=str)
    df.columns = [str(c).strip() for c in df.columns]

    # Apply column mapping (skip ignored columns)
    ignore_set = set(payload.ignore_columns)
    rename_map = {
        col: target
        for col, target in payload.mapping.items()
        if col in df.columns and col not in ignore_set
    }
    df = df.rename(columns=rename_map)

    inserted = 0
    skipped = 0
    errors = []

    for i, row in enumerate(df.itertuples(index=False), start=2):
        row_dict = row._asdict()

        keyword = str(row_dict.get("keyword") or "").strip()
        attr_name = str(row_dict.get("attr_name") or "").strip()
        attr_value = str(row_dict.get("attr_value") or "").strip()

        if not keyword or not attr_name or not attr_value:
            errors.append(f"Row {i}: missing required field (keyword/attr_name/attr_value)")
            skipped += 1
            continue

        # Dedup: skip if (keyword, attr_name, category_code) already exists
        existing = (
            db.query(AttrRule)
            .filter(
                AttrRule.keyword == keyword,
                AttrRule.attr_name == attr_name,
                AttrRule.category_code == payload.category_code,
            )
            .first()
        )
        if existing:
            skipped += 1
            continue

        match_type = str(row_dict.get("match_type") or "contains").strip() or "contains"
        priority_raw = row_dict.get("priority")
        try:
            priority = int(priority_raw) if priority_raw not in (None, "nan", "") else 0
        except (ValueError, TypeError):
            priority = 0

        db.add(AttrRule(
            keyword=keyword,
            match_type=match_type,
            attr_name=attr_name,
            attr_value=attr_value,
            category_code=payload.category_code,
            priority=priority,
        ))
        inserted += 1

    if inserted > 0:
        db.commit()

    # Save template if requested
    if payload.save_template_name and inserted > 0:
        from app.models.schemas import ColumnTemplate
        tmpl = ColumnTemplate(
            name=payload.save_template_name,
            module="attr",
            mapping=payload.mapping,
            ignore_columns=payload.ignore_columns,
            col_fingerprint=col_fingerprint(list(payload.mapping.keys())),
        )
        db.add(tmpl)
        try:
            db.commit()
        except Exception:
            db.rollback()

    return {"inserted": inserted, "skipped": skipped, "errors": errors}
