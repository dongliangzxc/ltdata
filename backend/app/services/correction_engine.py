"""
修正规则执行引擎

对某次清洗任务的所有 cleaned_data 记录，按 priority 升序链式叠加所有命中规则，
将计算结果写入 corrected_sales_qty / corrected_sales_amount。
"""
from sqlalchemy.orm import Session
from app.models.schemas import (
    CorrectionRule, CleanedDataRecord, MatchResult, ModelRecord, MatchResultAttr,
)


def apply_correction_rules(db: Session, clean_job_id: int) -> dict:
    """
    执行修正规则。返回 {"updated": N}。
    """
    # 加载全部活跃规则，按 priority 升序
    rules = (
        db.query(CorrectionRule)
        .filter(CorrectionRule.is_active == 1)
        .order_by(CorrectionRule.priority)
        .all()
    )
    if not rules:
        return {"updated": 0}

    # 加载 clean_job 的所有 cleaned_data
    cleaned_rows = (
        db.query(CleanedDataRecord)
        .filter(CleanedDataRecord.clean_job_id == clean_job_id)
        .all()
    )
    if not cleaned_rows:
        return {"updated": 0}

    # 预建索引：raw_data_id → (brand_code, model_id, category_code)
    # 通过 match_results 关联
    raw_ids = [c.raw_data_id for c in cleaned_rows]
    match_rows = (
        db.query(MatchResult, ModelRecord)
        .outerjoin(ModelRecord, MatchResult.model_id == ModelRecord.id)
        .filter(
            MatchResult.clean_job_id == clean_job_id,
            MatchResult.raw_data_id.in_(raw_ids),
        )
        .all()
    )
    # raw_data_id → {brand_code, model_id, category_code}
    match_index: dict[int, dict] = {}
    for mr, model in match_rows:
        match_index[mr.raw_data_id] = {
            "brand_code":    model.brand_code if model else None,
            "model_id":      mr.model_id,
            "category_code": model.category_code if model else None,
        }

    # 预建属性索引：match_result_id → {attr_name: attr_value}
    mr_ids = [mr.id for mr, _ in match_rows]
    attr_rows = db.query(MatchResultAttr).filter(MatchResultAttr.match_result_id.in_(mr_ids)).all() if mr_ids else []
    attr_index: dict[int, dict] = {}
    for a in attr_rows:
        attr_index.setdefault(a.match_result_id, {})[a.attr_name] = a.attr_value

    # raw_data_id → match_result_id（用于 attr 查找）
    raw_to_mr_id: dict[int, int] = {mr.raw_data_id: mr.id for mr, _ in match_rows}

    def _matches(rule: CorrectionRule, cd: CleanedDataRecord) -> bool:
        info = match_index.get(cd.raw_data_id, {})
        if rule.category_code and info.get("category_code") != rule.category_code:
            return False
        if rule.brand_code and info.get("brand_code") != rule.brand_code:
            return False
        if rule.model_id and info.get("model_id") != rule.model_id:
            return False
        if rule.attr_name:
            mr_id = raw_to_mr_id.get(cd.raw_data_id)
            attrs = attr_index.get(mr_id, {}) if mr_id else {}
            if attrs.get(rule.attr_name) != rule.attr_value:
                return False
        return True

    def _apply(value: float, rule: CorrectionRule) -> float:
        if rule.rule_type == "multiply":
            return round(value * float(rule.value), 4)
        else:  # offset
            return round(value + float(rule.value), 4)

    updated = 0
    for cd in cleaned_rows:
        qty = float(cd.corrected_sales_qty or 0)
        amt = float(cd.corrected_sales_amount or 0)
        changed = False

        for rule in rules:
            if not _matches(rule, cd):
                continue
            if rule.target in ("sales_qty", "both"):
                qty = _apply(qty, rule)
                changed = True
            if rule.target in ("sales_amount", "both"):
                amt = _apply(amt, rule)
                changed = True

        if changed:
            cd.corrected_sales_qty    = max(0, int(round(qty)))
            cd.corrected_sales_amount = max(0, round(amt, 2))
            updated += 1

    db.commit()
    return {"updated": updated}
