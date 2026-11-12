"""
数据清洗服务：
1. 清洗干预规则（intervention_rules）→ 命中过滤规则写入 filtered_items，跳过
2. 干扰链接库（interference_links）→ 命中链接直接剔除（全平台生效）
3. 品牌写法标准化（brand_aliases）→ brand_raw 查表覆盖 brand_std
4. 去重（同 item_id + month + shop_name 保留第一条）
5. brand_std 兜底补全（无匹配时用 brand_raw）
"""
import logging
import time

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.models.schemas import (
    RawDataRecord, CleanedDataRecord, CleanJobRecord,
    FilteredItem, BrandAlias, InterventionRule, InterferenceLink,
)
from app.services.rawdata_cache import cached_value

logger = logging.getLogger(__name__)


# 规则表进程内缓存：品牌别名/干扰链接是几十万行的重表，每个任务都全量重查会打满
# RDS（实测并发任务时单次 brand_aliases 查询 5-25s）。规则变更少，TTL 兜底 + 写入时
# 显式失效（invalidate_rawdata_cache）。
_RULES_CACHE_TTL = 300.0


def _load_intervention_rules(db: Session, category_code: str | None = None) -> list[dict]:
    """返回指定分发品类的 active 干预规则；未指定品类时不应用规则。

    缓存里只放普通 dict：ORM 实例绑定在加载它的 Session 上，跨请求复用缓存时
    原 Session 已关闭，访问属性会触发 DetachedInstanceError（attribute refresh
    operation cannot proceed）。
    """
    if not category_code:
        return []
    return cached_value(
        "clean_rules", ("intervention_rules", category_code), _RULES_CACHE_TTL,
        lambda: _load_intervention_rules_uncached(db, category_code),
    )


def _load_intervention_rules_uncached(db: Session, category_code: str) -> list[dict]:
    rows = (
        db.query(
            InterventionRule.id,
            InterventionRule.name,
            InterventionRule.action,
            InterventionRule.conditions,
        )
        .filter(
            InterventionRule.is_active == 1,
            InterventionRule.category_code == category_code,
        )
        .order_by(InterventionRule.priority, InterventionRule.id)
        .all()
    )
    return [
        {"id": rule_id, "name": name, "action": action, "conditions": conditions or {}}
        for rule_id, name, action, conditions in rows
    ]


def _load_interference_links(db: Session) -> dict[str, dict[str, str]]:
    """返回 {品类码: {链接(小写去空格): 原文}}，按品类严格隔离。"""
    return cached_value(
        "clean_rules", ("interference_links",), _RULES_CACHE_TTL,
        lambda: _load_interference_links_uncached(db),
    )


def _load_interference_links_uncached(db: Session) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for row in db.query(InterferenceLink).all():
        normalized = (row.url or "").casefold().strip()
        if not normalized:
            continue
        bucket = result.setdefault(row.category_code, {})
        bucket[normalized] = row.url
    return result


# 干扰链接索引片段长度：长度 >= 该值的链接按末尾 N 个字符分组。
# 取末尾而非开头：链接开头基本都是 https://item.xxx.com/，末尾的商品 ID 区分度高。
_LINK_KEY_TAIL_LEN = 10


def _build_interference_link_index(
    links: dict[str, dict[str, str]],
    category_code: str | None,
) -> tuple[dict[str, list[tuple[int, str, str]]], list[tuple[int, str, str]]] | None:
    """把当前品类的干扰链接建成索引：(按末尾 N 字符分组, 短于 N 的链接)。

    元素为 (库中顺序, 规范化链接, 原文)。若某链接是商品链接的子串，其末尾 N 个字符
    必然是商品链接某个位置开始的 N 字符片段，因此按片段查索引不会漏掉命中；
    命中多条时取库中顺序最靠前的一条，与逐条遍历的返回结果一致。
    """
    if not category_code:
        return None
    bucket = links.get(category_code)
    if not bucket:
        return None
    by_tail: dict[str, list[tuple[int, str, str]]] = {}
    short: list[tuple[int, str, str]] = []
    for order, (key, original) in enumerate(bucket.items()):
        if not key:
            continue
        if len(key) >= _LINK_KEY_TAIL_LEN:
            by_tail.setdefault(key[-_LINK_KEY_TAIL_LEN:], []).append((order, key, original))
        else:
            short.append((order, key, original))
    return by_tail, short


def _matches_interference_links(
    record: RawDataRecord,
    link_index: tuple[dict[str, list[tuple[int, str, str]]], list[tuple[int, str, str]]] | None,
) -> str | None:
    """商品链接包含当前品类库中的任意链接时返回命中的库中链接原文，否则 None。"""
    if not link_index:
        return None
    url = (record.item_url or "").casefold().strip()
    if not url:
        return None
    by_tail, short = link_index
    best: tuple[int, str] | None = None
    for order, key, original in short:
        if key in url:
            best = (order, original)
            break
    n = _LINK_KEY_TAIL_LEN
    for pos in range(len(url) - n + 1):
        for order, key, original in by_tail.get(url[pos:pos + n], ()):
            if (best is None or order < best[0]) and key in url:
                best = (order, original)
    return best[1] if best else None


def _load_brand_alias_map(db: Session) -> dict[str, str]:
    """返回 {写法大写: brand_code}，只取 active。

    一条别名可写多个写法并用 `/` 分隔（如「汉王（Hanvon）/HANVON/汉王」），
    这里拆成「整串 + 每个分隔部分」分别作为 key，便于对原始品牌文本做精确匹配。
    """
    return cached_value(
        "clean_rules", ("brand_alias_map",), _RULES_CACHE_TTL,
        lambda: _load_brand_alias_map_uncached(db),
    )


def _alias_name_group_expr(db: Session):
    """按精确字符串分组；MySQL 默认排序规则大小写/全半角不敏感，会把不同写法合并。"""
    expr = BrandAlias.alias_name
    bind = db.get_bind()
    if bind is not None and bind.dialect.name != "sqlite":
        expr = expr.collate("utf8mb4_bin")
    return expr


def _load_brand_alias_map_uncached(db: Session) -> dict[str, str]:
    result = {}
    # 同一写法在表里可能有大量重复行（历史批量导入未去重，实测 28 万行只对应 3 千多个写法）。
    # 旧实现按 id 全量遍历、后写覆盖先写，等价于「每个写法只保留 id 最大的那行」；
    # 这里先用 SQL 收敛到每个写法的最新一行，返回结果与全量遍历完全一致，
    # 但行数从几十万降到几千。分组必须用 binary 排序规则，否则数据库的大小写/全半角
    # 不敏感排序会把不同写法的行合并，导致少 key。
    latest_alias_ids = (
        db.query(func.max(BrandAlias.id).label("mid"))
        .filter(BrandAlias.is_active == 1)
        .group_by(_alias_name_group_expr(db))
        .subquery()
    )
    rows = (
        db.query(BrandAlias.alias_name, BrandAlias.brand_code)
        .join(latest_alias_ids, BrandAlias.id == latest_alias_ids.c.mid)
        .order_by(BrandAlias.id)
        .all()
    )
    for r_alias_name, brand_code in rows:
        normalized = r_alias_name.strip().upper()
        candidates = [normalized]
        candidates.extend(part.strip() for part in normalized.split("/") if part.strip())
        for candidate in candidates:
            result[candidate] = brand_code
    return result


def auto_brand_std(raw: RawDataRecord, brand_alias_map: dict[str, str]) -> str | None:
    """清洗时 brand_std 的自动取值：原始 brand_std → 品牌写法库别名 → 原始 brand_raw。"""
    brand_std = raw.brand_std
    if raw.brand_raw:
        hit = brand_alias_map.get(raw.brand_raw.upper())
        if hit:
            brand_std = hit
    if not brand_std:
        brand_std = raw.brand_raw
    return brand_std


def manual_brand_std(
    cleaned: "CleanedDataRecord | None",
    raw: RawDataRecord,
    brand_alias_map: dict[str, str],
) -> str | None:
    """「只清洗品牌」人工设置的品牌：cleaned.brand_std 与自动算出的值不同即为人工值。

    不加标记列时的判定方式；未人工设置（或人工值恰好等于自动值）返回 None。
    """
    if cleaned is None or not cleaned.brand_std:
        return None
    if cleaned.brand_std != auto_brand_std(raw, brand_alias_map):
        return cleaned.brand_std
    return None



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
    if conditions.get("shop_name_in"):
        parts.append(f"店铺名称 in [{', '.join(_stringify_list(conditions['shop_name_in']))}]")
    if conditions.get("item_name_contains_any"):
        parts.append(f"商品名称包含 [{', '.join(_stringify_list(conditions['item_name_contains_any']))}]")
    if conditions.get("item_name_not_contains_any"):
        parts.append(f"商品名称不包含 [{', '.join(_stringify_list(conditions['item_name_not_contains_any']))}]")
    if conditions.get("category_name_contains_any"):
        parts.append(f"类目名称包含 [{', '.join(_stringify_list(conditions['category_name_contains_any']))}]")

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
    rule: dict,
    brand_alias_map: dict[str, str] | None = None,
) -> bool:
    """所有已配置条件均需满足，且至少一个已识别条件匹配。"""
    conditions = rule.get("conditions") or {}
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

    shop_values = conditions.get("shop_name_in")
    if shop_values:
        has_recognized_condition = True
        shop_name = (record.shop_name or "").casefold().strip()
        if not shop_name or shop_name not in {str(value).casefold().strip() for value in shop_values}:
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

    category_contains_values = conditions.get("category_name_contains_any")
    if category_contains_values:
        has_recognized_condition = True
        category_text = "\n".join(
            str(value).casefold()
            for value in (
                record.category_lv0,
                record.category_lv1,
                record.category_lv2,
                record.category_lv3,
                record.category_lv4,
                record.category_lv5,
            )
            if value
        )
        if not any(str(value).casefold() in category_text for value in category_contains_values):
            return False

    price_condition = conditions.get("reference_price")
    if price_condition:
        has_recognized_condition = True
        price_for_rule = record.ref_price if record.ref_price is not None else record.price
        if not _matches_price_condition(price_for_rule, price_condition):
            return False

    return has_recognized_condition


def _first_matching_intervention_rule(
    record: RawDataRecord,
    intervention_rules: list[dict],
    brand_alias_map: dict[str, str] | None = None,
) -> dict | None:
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
    raw_data_ids: list[int] | None = None,
) -> int:
    """执行清洗逻辑，返回写入 cleaned_data 的行数。

    ``raw_data_ids`` 非空时只清洗这些原始行（用于补充数据增量处理），
    并会预载任务已有清洗结果参与去重，避免与历史数据重复。
    """
    dedup: bool = rules.get("dedup", True)
    _t0 = time.perf_counter()

    # ── 加载规则表 ─────────────────────────────────────────────
    intervention_rules = _load_intervention_rules(db, dispatch_category_code)
    brand_alias_map = _load_brand_alias_map(db)
    interference_link_index = _build_interference_link_index(
        _load_interference_links(db), dispatch_category_code,
    )
    _t1 = time.perf_counter()

    # ── 数据源选取 ─────────────────────────────────────────────
    from app.models.schemas import CleanJobItemRecord
    records_query = (
        db.query(RawDataRecord)
        .join(CleanJobItemRecord, CleanJobItemRecord.raw_data_id == RawDataRecord.id)
        .filter(CleanJobItemRecord.clean_job_id == clean_job_id)
    )
    if raw_data_ids is not None:
        records_query = records_query.filter(RawDataRecord.id.in_(raw_data_ids))
    records = records_query.order_by(CleanJobItemRecord.id).all()
    if not records:
        if dispatch_batch_id and dispatch_category_code:
            from app.models.schemas import DispatchItem
            raw_data_ids_in_batch = select(DispatchItem.raw_data_id).filter(
                DispatchItem.batch_id == dispatch_batch_id,
                DispatchItem.category_code == dispatch_category_code,
            )
            records = db.query(RawDataRecord).filter(RawDataRecord.id.in_(raw_data_ids_in_batch)).all()
        elif raw_data_ids is None:
            records = db.query(RawDataRecord).filter(RawDataRecord.file_id.in_(file_ids)).all()
    _t2 = time.perf_counter()

    cleaned: list[dict] = []
    filtered: list[dict] = []
    seen_keys: set = set()
    if dedup and raw_data_ids is not None:
        seen_keys = {
            (item_id, month, shop_name)
            for item_id, month, shop_name in db.query(
                CleanedDataRecord.item_id,
                CleanedDataRecord.month,
                CleanedDataRecord.shop_name,
            ).filter(CleanedDataRecord.clean_job_id == clean_job_id).all()
        }

    for r in records:
        # ── Step 1: 干扰链接库（按品类剔除）────────────────────────
        hit_link = _matches_interference_links(r, interference_link_index)
        if hit_link is not None:
            filtered.append(dict(
                raw_data_id=r.id,
                clean_job_id=clean_job_id,
                matched_keyword="干扰链接库",
                intervention_rule_id=None,
                intervention_rule_name="干扰链接库",
                matched_reason=f"命中干扰链接库：{hit_link}",
            ))
            continue

        # ── Step 2: 清洗干预规则 ─────────────────────────────────
        matched_rule = _first_matching_intervention_rule(r, intervention_rules, brand_alias_map)
        if matched_rule is not None:
            if matched_rule["action"] == "filter":
                filtered.append(dict(
                    raw_data_id=r.id,
                    clean_job_id=clean_job_id,
                    matched_keyword=matched_rule["name"],
                    intervention_rule_id=matched_rule["id"],
                    intervention_rule_name=matched_rule["name"],
                    matched_reason=(
                        f"命中规则「{matched_rule['name']}」："
                        f"{_intervention_condition_summary(matched_rule.get('conditions') or {})}"
                    ),
                ))
                continue
            if matched_rule["action"] == "allow":
                pass

        # ── Step 3: 去重 ─────────────────────────────────────────
        if dedup:
            key = (r.item_id, r.month, r.shop_name)
            if key in seen_keys:
                continue
            seen_keys.add(key)

        # ── Step 4: 品牌写法标准化 ───────────────────────────────
        brand_std = r.brand_std  # 原始已有标准品牌码（上传时从 Excel 读取）
        if r.brand_raw:
            alias_hit = brand_alias_map.get(r.brand_raw.upper())
            if alias_hit:
                brand_std = alias_hit
        if not brand_std:
            brand_std = r.brand_raw  # 兜底

        cleaned.append(dict(
            raw_data_id=r.id,
            clean_job_id=clean_job_id,
            country_code=r.country_code,
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
    _t3 = time.perf_counter()

    # ── 批量写入 ──────────────────────────────────────────────
    # 直接按字典批量插入，省去逐行构造 ORM 对象；列默认值（created_at/is_recovered）照常填充
    if filtered:
        db.bulk_insert_mappings(FilteredItem, filtered)
    if cleaned:
        db.bulk_insert_mappings(CleanedDataRecord, cleaned)

    # ── 更新 job 统计 ─────────────────────────────────────────
    job = db.query(CleanJobRecord).filter(CleanJobRecord.id == clean_job_id).first()
    if job:
        job.row_in = len(records)
        job.row_out = len(cleaned)
        job.row_filtered = len(filtered)

    if commit:
        db.commit()
    logger.info(
        "run_clean job=%s rows=%d cleaned=%d filtered=%d rules=%.1fs query=%.1fs loop=%.1fs write=%.1fs total=%.1fs",
        clean_job_id, len(records), len(cleaned), len(filtered),
        _t1 - _t0, _t2 - _t1, _t3 - _t2, time.perf_counter() - _t3, time.perf_counter() - _t0,
    )
    return len(cleaned)
