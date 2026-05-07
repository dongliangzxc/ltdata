"""
属性关键词匹配服务

对已确认型号的 match_result 运行属性规则，将命中的属性写入 match_result_attrs。

规则优先级：
  1. 品类规则（category_code 不为 NULL）优先于全局规则（category_code IS NULL）
  2. 同一品类内，priority 数字越小越先执行（先命中的 attr_name 胜出）
  3. 对同一 (match_result_id, attr_name)，执行 upsert（支持重跑）
"""
from sqlalchemy.orm import Session
from app.models.schemas import AttrRule, MatchResult, MatchResultAttr, RawDataRecord, ModelRecord


def run_attribute_matching(db: Session, match_result_ids: list[int]) -> dict:
    """
    对指定 match_result_ids 执行属性规则匹配。
    返回 {"matched_attrs": N, "items_processed": N}
    """
    if not match_result_ids:
        return {"matched_attrs": 0, "items_processed": 0}

    # 1. 加载 active 规则，按 priority 升序
    rules = (
        db.query(AttrRule)
        .filter(AttrRule.is_active == 1)
        .order_by(AttrRule.priority)
        .all()
    )
    if not rules:
        return {"matched_attrs": 0, "items_processed": len(match_result_ids)}

    # 2. 加载 match_results + raw_data + model（一次查询）
    rows = (
        db.query(MatchResult, RawDataRecord, ModelRecord)
        .join(RawDataRecord, MatchResult.raw_data_id == RawDataRecord.id)
        .outerjoin(ModelRecord, MatchResult.model_id == ModelRecord.id)
        .filter(MatchResult.id.in_(match_result_ids))
        .all()
    )

    # Pre-load existing attrs to avoid N+1 queries
    existing_attrs: dict[tuple[int, str], MatchResultAttr] = {}
    if rows:
        all_mr_ids = [mr.id for mr, rd, model in rows]
        for attr in db.query(MatchResultAttr).filter(MatchResultAttr.match_result_id.in_(all_mr_ids)).all():
            existing_attrs[(attr.match_result_id, attr.attr_name)] = attr

    total_attrs = 0
    items_processed = 0

    for mr, rd, model in rows:
        if mr.model_id is None:
            continue
        items_processed += 1
        category = model.category_name if model else None
        item_upper = (rd.item_name or "").upper()

        # 两路分别收集命中：品类规则 + 全局规则
        # key = attr_name, value = (attr_value, rule_id)
        # 品类规则优先；同优先级按 priority 顺序（rules 已升序），先命中的胜出
        category_hits: dict[str, tuple[str, int]] = {}
        global_hits: dict[str, tuple[str, int]] = {}

        for rule in rules:
            kw = rule.keyword.upper()
            if rule.match_type == "exact":
                hit = item_upper == kw
            else:
                hit = kw in item_upper
            if not hit:
                continue

            if rule.category_code is not None:
                if rule.category_code == category and rule.attr_name not in category_hits:
                    category_hits[rule.attr_name] = (rule.attr_value, rule.id)
            else:
                if rule.attr_name not in global_hits:
                    global_hits[rule.attr_name] = (rule.attr_value, rule.id)

        # 品类规则覆盖全局规则
        applied = {**global_hits, **category_hits}

        for attr_name, (attr_value, rule_id) in applied.items():
            key = (mr.id, attr_name)
            if key in existing_attrs:
                existing_attrs[key].attr_value = attr_value
                existing_attrs[key].rule_id = rule_id
            else:
                new_attr = MatchResultAttr(
                    match_result_id=mr.id,
                    attr_name=attr_name,
                    attr_value=attr_value,
                    rule_id=rule_id,
                )
                db.add(new_attr)
                existing_attrs[key] = new_attr
            total_attrs += 1

    db.commit()
    return {"matched_attrs": total_attrs, "items_processed": items_processed}
