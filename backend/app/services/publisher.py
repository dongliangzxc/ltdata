"""
publisher.py — 将已匹配/已确认数据发布到 luotu_analytics 分析库

逻辑：
1. 查 match_results WHERE clean_job_id=? AND match_status IN ('matched', 'confirmed')
2. JOIN raw_data 取基础字段，JOIN models 取品牌/型号/品类信息
3. 批量查 model_specs → {model_id: {spec_name: spec_value}}
4. 写入 luotu_analytics.published_items + published_item_specs
5. 记录 luotu.publish_jobs
"""

from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import text, tuple_
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from app.models.analytics_db import AnalyticsBase, analytics_engine, PublishedItem, PublishedItemSpec
from app.models.schemas import ModelSpec, MatchResultAttr
from app.services.correction_engine import apply_correction_rules

PUBLISH_BATCH_SIZE = 1000


def _chunks(rows):
    for start in range(0, len(rows), PUBLISH_BATCH_SIZE):
        yield rows[start:start + PUBLISH_BATCH_SIZE]


def _upsert_published_items(db, items):
    """Use bounded multi-value writes; the caller commits the whole publication."""
    mysql = db.get_bind().dialect.name == "mysql"
    for batch in _chunks(items):
        stmt = (mysql_insert if mysql else sqlite_insert)(PublishedItem.__table__).values(batch)
        incoming = stmt.inserted if mysql else stmt.excluded
        # Keep the existing duplicate-publication field/overwrite policy.
        fields = (
            "publish_job_id", "clean_job_id", "match_result_id", "item_name", "item_image",
            "item_url", "ref_price", "shop_name", "sales_qty", "sales_amount", "price",
            "brand_code", "brand_name", "model_code", "model_name", "category_name",
            "category_lv0", "calc_price", "corrected_sales_qty", "corrected_sales_amount", "published_at",
        )
        updates = {name: getattr(incoming, name) for name in fields}
        stmt = stmt.on_duplicate_key_update(**updates) if mysql else stmt.on_conflict_do_update(
            index_elements=["platform", "item_id", "month", "week_of_month"], set_=updates,
        )
        db.execute(stmt)


def _ensure_analytics_tables():
    """确保分析库表已创建（首次运行）"""
    AnalyticsBase.metadata.create_all(bind=analytics_engine)


def _count_unique_published_items(items: list[dict]) -> int:
    return len({(item["platform"], item["item_id"], item["month"], item.get("week_of_month", 0)) for item in items})


def delete_published_data(analytics_db: Session, clean_job_id: int) -> None:
    """删除指定清洗任务在分析库中的已发布数据（含属性表）。"""
    old_ids = [row.id for row in analytics_db.query(PublishedItem.id).filter_by(clean_job_id=clean_job_id)]
    for batch in _chunks(old_ids):
        analytics_db.query(PublishedItemSpec).filter(
            PublishedItemSpec.published_item_id.in_(batch),
        ).delete(synchronize_session=False)
    if old_ids:
        analytics_db.query(PublishedItem).filter_by(clean_job_id=clean_job_id).delete(synchronize_session=False)


def _build_published_item_params(r, clean_job_id: int, published_at: datetime) -> dict:
    base_corrected_qty = r["corrected_sales_qty"] if r["corrected_sales_qty"] is not None else r["sales_qty"]
    base_corrected_amount = (
        r["corrected_sales_amount"]
        if r["corrected_sales_amount"] is not None
        else r["sales_amount"]
    )
    if r["sales_coefficient"] is not None:
        corrected_sales_qty = round(base_corrected_qty * r["sales_coefficient"])
        corrected_sales_amount = (
            round(base_corrected_amount * r["sales_coefficient"], 2)
            if base_corrected_amount is not None
            else None
        )
    else:
        corrected_sales_qty = base_corrected_qty
        corrected_sales_amount = base_corrected_amount

    return {
        "publish_job_id":          0,   # 占位，稍后回填
        "clean_job_id":            clean_job_id,
        "match_result_id":         r["match_result_id"],
        "platform":                r["platform"],
        "month":                   r["month"],
        "week_of_month":           r.get("week_of_month", 0),
        "category_lv0":            r["category_lv0"],
        "category_lv1":            r["category_lv1"],
        "category_lv2":            r["category_lv2"],
        "category_lv3":            r["category_lv3"],
        "category_lv4":            r["category_lv4"],
        "category_lv5":            r["category_lv5"],
        "item_id":                 r["item_id"],
        "item_name":               r["item_name"],
        "item_image":              r["item_image"],
        "item_url":                r["item_url"],
        "ref_price":               r["ref_price"],
        "shop_name":               r["shop_name"],
        "sales_qty":               r["sales_qty"],
        "sales_amount":            r["sales_amount"],
        "price":                   r["price"],
        "brand_code":              r["brand_code"],
        "brand_name":              r["brand_name"],
        "model_code":              r["model_code"],
        "model_name":              r["model_name"],
        "category_name":           r["category_name"],
        "calc_price":              r["calc_price"],  # NULL when no cleaned_data row (pre-P1 data or unmatched) — intentional
        "corrected_sales_qty":     corrected_sales_qty,
        "corrected_sales_amount":  corrected_sales_amount,
        "published_at":            published_at,
    }


def run_publish(luotu_db: Session, analytics_db: Session, clean_job_id: int) -> dict:
    """
    执行发布：从 luotu 读取匹配结果，写入 luotu_analytics。
    支持重复执行（先删除同 clean_job_id 的旧数据）。
    返回 {"published_count": N, "skipped_pending_count": N}
    """
    _ensure_analytics_tables()

    # 发布前重新应用修正规则，确保 corrected 字段是最新值
    apply_correction_rules(luotu_db, clean_job_id)

    # 统计本次被跳过的 pending 条目数
    pending_count_sql = text(
        "SELECT COUNT(*) FROM match_results "
        "WHERE clean_job_id = :clean_job_id AND match_status = 'pending'"
    )
    skipped_pending_count: int = luotu_db.execute(
        pending_count_sql, {"clean_job_id": clean_job_id}
    ).scalar() or 0

    # 1. 查询已匹配/已确认的 match_results，JOIN raw_data + models + cleaned_data
    sql = text("""
        SELECT
            mr.id           AS match_result_id,
            rd.platform,
            rd.month,
            rd.week_of_month,
            rd.category_lv0,
            rd.category_lv1,
            rd.category_lv2,
            rd.category_lv3,
            rd.category_lv4,
            rd.category_lv5,
            rd.item_id,
            rd.item_name,
            rd.item_image,
            rd.item_url,
            rd.ref_price,
            rd.shop_name,
            rd.sales_qty,
            rd.sales_amount,
            rd.price,
            m.brand_code,
            COALESCE(NULLIF(m.brand_name, ''), m.brand_code) AS brand_name,
            m.model_code,
            COALESCE(NULLIF(m.model_name, ''), m.model_code) AS model_name,
            COALESCE(c.name, '') AS category_name,
            m.id            AS model_id,
            cd.calc_price,
            cd.corrected_sales_qty,
            cd.corrected_sales_amount,
            mr.sales_coefficient
        FROM match_results mr
        JOIN raw_data rd  ON rd.id = mr.raw_data_id
        JOIN models m     ON m.id  = mr.model_id
        LEFT JOIN categories c ON c.code = m.category_code
        LEFT JOIN cleaned_data cd ON cd.raw_data_id = rd.id
                                  AND cd.clean_job_id = :clean_job_id
        WHERE mr.clean_job_id = :clean_job_id
          AND mr.match_status IN ('url_matched', 'matched', 'confirmed')
          AND mr.is_disabled = 0
    """)
    rows = luotu_db.execute(sql, {"clean_job_id": clean_job_id}).mappings().all()

    if not rows:
        return {"published_count": 0, "skipped_pending_count": skipped_pending_count}

    # 2. Read specifications/attributes with bounded IN lists.
    specs_map: dict[int, dict[str, str]] = {}
    for batch in _chunks(list({r["model_id"] for r in rows})):
        for sr in luotu_db.query(ModelSpec.model_id, ModelSpec.spec_name, ModelSpec.spec_value).filter(
            ModelSpec.model_id.in_(batch),
        ):
            specs_map.setdefault(sr.model_id, {})[sr.spec_name] = sr.spec_value

    attrs_map: dict[int, dict[str, str]] = {}
    for batch in _chunks([r["match_result_id"] for r in rows]):
        for ar in luotu_db.query(MatchResultAttr.match_result_id, MatchResultAttr.attr_name, MatchResultAttr.attr_value).filter(
            MatchResultAttr.match_result_id.in_(batch),
        ):
            attrs_map.setdefault(ar.match_result_id, {})[ar.attr_name] = ar.attr_value

    # 3. 先删除同 clean_job_id 的旧发布数据（支持重复发布）
    delete_published_data(analytics_db, clean_job_id)

    # 4. Write all item batches in the same transaction.
    items_to_insert = [
        _build_published_item_params(r, clean_job_id, datetime.utcnow()) for r in rows
    ]
    _upsert_published_items(analytics_db, items_to_insert)

    # 5. 写入 published_item_specs
    #    upsert 后无法直接拿到 id，通过 (platform, item_id, month, week_of_month) 查回
    if specs_map or attrs_map:
        # 构建 (platform, item_id, month, week_of_month) → model_id 映射
        key_to_model: dict[tuple, int] = {
            (r["platform"], r["item_id"], r["month"], r.get("week_of_month", 0)): r["model_id"]
            for r in rows
        }
        # 同时建立 (platform, item_id, month, week_of_month) → match_result_id 映射
        key_to_match_result: dict[tuple, int] = {
            (r["platform"], r["item_id"], r["month"], r.get("week_of_month", 0)): r["match_result_id"]
            for r in rows
        }
        # Query back IDs in bounded batches, once per persisted item even when
        # input keys repeat or the database collation merges different spellings.
        keys = list(dict.fromkeys((d["platform"], d["item_id"], d["month"], d.get("week_of_month", 0)) for d in items_to_insert))
        seen_pub_ids = set()
        specs_to_insert = []
        for batch in _chunks(keys):
            id_rows = analytics_db.query(
                PublishedItem.id, PublishedItem.platform, PublishedItem.item_id, PublishedItem.month, PublishedItem.week_of_month,
            ).filter(tuple_(PublishedItem.platform, PublishedItem.item_id, PublishedItem.month, PublishedItem.week_of_month).in_(batch)).all()
            for pub_id, platform, item_id, month, week in id_rows:
                if pub_id in seen_pub_ids:
                    continue
                seen_pub_ids.add(pub_id)
                model_id = key_to_model.get((platform, item_id, month, week))
                match_result_id = key_to_match_result.get((platform, item_id, month, week))
                if model_id is None:
                    continue
                merged = dict(specs_map.get(model_id, {}))
                merged.update(attrs_map.get(match_result_id, {}))
                for spec_name, spec_value in merged.items():
                    specs_to_insert.append(dict(
                        published_item_id=pub_id, spec_name=spec_name, spec_value=spec_value,
                    ))
                    if len(specs_to_insert) >= PUBLISH_BATCH_SIZE:
                        analytics_db.execute(PublishedItemSpec.__table__.insert(), specs_to_insert)
                        specs_to_insert = []
        if specs_to_insert:
            analytics_db.execute(PublishedItemSpec.__table__.insert(), specs_to_insert)

    analytics_db.commit()
    return {
        "published_count": _count_unique_published_items(items_to_insert),
        "skipped_pending_count": skipped_pending_count,
    }
