"""
数据清洗服务：
1. 清洗干预规则（intervention_rules）→ 命中过滤规则写入 filtered_items，跳过
2. 品牌写法标准化（brand_aliases）→ brand_raw 查表覆盖 brand_std
3. 去重（同 item_id + month + shop_name 保留第一条）
4. brand_std 兜底补全（无匹配时用 brand_raw）
"""
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.schemas import (
    RawDataRecord, CleanedDataRecord, CleanJobRecord,
    FilteredItem, BrandAlias, InterventionRule,
)


def _load_intervention_rules(db: Session, category_code: str | None = None) -> list[InterventionRule]:
    """返回指定分发品类的 active 干预规则；未指定品类时不应用规则。"""
    if not category_code:
        return []
    return (
        db.query(InterventionRule)
        .filter(
            InterventionRule.is_active == 1,
            InterventionRule.category_code == category_code,
        )
        .order_by(InterventionRule.priority, InterventionRule.id)
        .all()
    )


def _load_brand_alias_map(db: Session) -> dict[str, str]:
    """返回 {alias_name_upper: brand_code} 只取 active"""
    rows = db.query(BrandAlias).filter(BrandAlias.is_active == 1).all()
    return {r.alias_name.upper(): r.brand_code for r in rows}


def _format_number(value: object) -> str:
    try:
        return f"{float(value):g}"
    except (TypeError, ValueError):
        return str(value)


def _stringify_list(values: list) -> list[str]:
    return [str(value) for value in values]


def _intervention_condition_summary(conditions: dict) -> str:
    parts = []
    if conditions.get("brand_in"):
        parts.append(f"品牌 in [{', '.join(_stringify_list(conditions['brand_in']))}]")
    if conditions.get("item_name_contains_any"):
        parts.append(f"商品名称包含 [{', '.join(_stringify_list(conditions['item_name_contains_any']))}]")
    if conditions.get("item_name_not_contains_any"):
        parts.append(f"商品名称不包含 [{', '.join(_stringify_list(conditions['item_name_not_contains_any']))}]")

    price = conditions.get("reference_price")
    if price:
        op = price.get("op")
        if op == "between":
            parts.append(f"参考价格 {_format_number(price.get('min'))} - {_format_number(price.get('max'))}")
        elif op in {"gt", "gte", "lt", "lte"}:
            op_label = {"gt": ">", "gte": ">=", "lt": "<", "lte": "<="}[op]
            parts.append(f"参考价格 {op_label} {_format_number(price.get('value'))}")
    return " 且 ".join(parts)


def _to_float(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _matches_price_condition(ref_price: object, condition: dict) -> bool:
    if ref_price is None:
        return False
    price = _to_float(ref_price)
    if price is None:
        return False

    op = condition.get("op")
    if op in {"gt", "gte", "lt", "lte"}:
        value = _to_float(condition.get("value"))
        if value is None:
            return False
        if op == "gt":
            return price > value
        if op == "gte":
            return price >= value
        if op == "lt":
            return price < value
        if op == "lte":
            return price <= value
    if op == "between":
        min_value = _to_float(condition.get("min"))
        max_value = _to_float(condition.get("max"))
        if min_value is None or max_value is None:
            return False
        return min_value <= price <= max_value
    return False


def _matches_intervention_rule(
    record: RawDataRecord,
    rule: InterventionRule,
    brand_alias_map: dict[str, str] | None = None,
) -> bool:
    """所有已配置条件均需满足，且至少一个已识别条件匹配。"""
    conditions = rule.conditions or {}
    brand_raw = (record.brand_raw or "").strip()
    item_name = (record.item_name or "").casefold()
    has_recognized_condition = False

    brand_values = conditions.get("brand_in")
    if brand_values:
        has_recognized_condition = True
        brand_candidates = {brand_raw.casefold()} if brand_raw else set()
        normalized_brand = (brand_alias_map or {}).get(brand_raw.upper()) if brand_raw else None
        if normalized_brand:
            brand_candidates.add(normalized_brand.casefold())
        if not brand_candidates.intersection({str(value).casefold() for value in brand_values}):
            return False

    contains_values = conditions.get("item_name_contains_any")
    if contains_values:
        has_recognized_condition = True
        if not any(str(value).casefold() in item_name for value in contains_values):
            return False

    not_contains_values = conditions.get("item_name_not_contains_any")
    if not_contains_values:
        has_recognized_condition = True
        if any(str(value).casefold() in item_name for value in not_contains_values):
            return False

    price_condition = conditions.get("reference_price")
    if price_condition:
        has_recognized_condition = True
        if not _matches_price_condition(record.ref_price, price_condition):
            return False

    return has_recognized_condition


def _first_matching_intervention_rule(
    record: RawDataRecord,
    intervention_rules: list[InterventionRule],
    brand_alias_map: dict[str, str] | None = None,
) -> InterventionRule | None:
    for rule in intervention_rules:
        if _matches_intervention_rule(record, rule, brand_alias_map):
            return rule
    return None


def run_clean(
    db: Session,
    clean_job_id: int,
    file_ids: list[int],
    rules: dict,
    dispatch_batch_id: int | None = None,
    dispatch_category_code: str | None = None,
    commit: bool = True,
) -> int:
    """执行清洗逻辑，返回写入 cleaned_data 的行数"""
    dedup: bool = rules.get("dedup", True)

    # ── 加载规则表 ─────────────────────────────────────────────
    intervention_rules = _load_intervention_rules(db, dispatch_category_code)
    brand_alias_map = _load_brand_alias_map(db)

    # ── 数据源选取 ─────────────────────────────────────────────
    from app.models.schemas import CleanJobItemRecord
    records = (
        db.query(RawDataRecord)
        .join(CleanJobItemRecord, CleanJobItemRecord.raw_data_id == RawDataRecord.id)
        .filter(CleanJobItemRecord.clean_job_id == clean_job_id)
        .order_by(CleanJobItemRecord.id)
        .all()
    )
    if not records:
        if dispatch_batch_id and dispatch_category_code:
            from app.models.schemas import DispatchItem
            raw_data_ids = select(DispatchItem.raw_data_id).filter(
                DispatchItem.batch_id == dispatch_batch_id,
                DispatchItem.category_code == dispatch_category_code,
            )
            records = db.query(RawDataRecord).filter(RawDataRecord.id.in_(raw_data_ids)).all()
        else:
            records = db.query(RawDataRecord).filter(RawDataRecord.file_id.in_(file_ids)).all()

    cleaned: list[CleanedDataRecord] = []
    filtered: list[FilteredItem] = []
    seen_keys: set = set()

    for r in records:
        # ── Step 1: 清洗干预规则 ─────────────────────────────────
        matched_rule = _first_matching_intervention_rule(r, intervention_rules, brand_alias_map)
        if matched_rule is not None:
            if matched_rule.action == "filter":
                filtered.append(FilteredItem(
                    raw_data_id=r.id,
                    clean_job_id=clean_job_id,
                    matched_keyword=matched_rule.name,
                    intervention_rule_id=matched_rule.id,
                    intervention_rule_name=matched_rule.name,
                    matched_reason=(
                        f"命中规则「{matched_rule.name}」："
                        f"{_intervention_condition_summary(matched_rule.conditions or {})}"
                    ),
                ))
                continue
            if matched_rule.action == "allow":
                pass

        # ── Step 2: 去重 ─────────────────────────────────────────
        if dedup:
            key = (r.item_id, r.month, r.shop_name)
            if key in seen_keys:
                continue
            seen_keys.add(key)

        # ── Step 3: 品牌写法标准化 ───────────────────────────────
        brand_std = r.brand_std  # 原始已有标准品牌码（上传时从 Excel 读取）
        if r.brand_raw:
            alias_hit = brand_alias_map.get(r.brand_raw.upper())
            if alias_hit:
                brand_std = alias_hit
        if not brand_std:
            brand_std = r.brand_raw  # 兜底

        cleaned.append(CleanedDataRecord(
            raw_data_id=r.id,
            clean_job_id=clean_job_id,
            platform=r.platform,
            month=r.month,
            week=r.week,
            category_lv1=r.category_lv1,
            category_lv2=r.category_lv2,
            category_lv3=r.category_lv3,
            category_lv4=r.category_lv4,
            category_lv5=r.category_lv5,
            item_id=r.item_id,
            item_url=r.item_url,
            item_name=r.item_name,
            item_image=r.item_image,
            ref_price=r.ref_price,
            brand_raw=r.brand_raw,
            shop_name=r.shop_name,
            sales_qty=r.sales_qty,
            sales_amount=r.sales_amount,
            price=r.price,
            brand_std=brand_std,
            model_std=r.model_std,
            category_lv0=r.category_lv0,
            calc_price=(
                round(float(r.sales_amount) / int(r.sales_qty), 2)
                if r.sales_amount is not None
                and r.sales_qty is not None
                and int(r.sales_qty) > 0
                else None
            ),
            corrected_sales_qty=r.sales_qty,
            corrected_sales_amount=r.sales_amount,
        ))

    # ── 批量写入 ──────────────────────────────────────────────
    if filtered:
        db.bulk_save_objects(filtered)
    if cleaned:
        db.bulk_save_objects(cleaned)

    # ── 更新 job 统计 ─────────────────────────────────────────
    job = db.query(CleanJobRecord).filter(CleanJobRecord.id == clean_job_id).first()
    if job:
        job.row_in = len(records)
        job.row_out = len(cleaned)
        job.row_filtered = len(filtered)

    if commit:
        db.commit()
    return len(cleaned)
