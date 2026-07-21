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
from sqlalchemy import text
from app.models.analytics_db import AnalyticsBase, analytics_engine, PublishedItemSpec
from app.services.correction_engine import apply_correction_rules

def _ensure_analytics_tables():
    """确保分析库表已创建（首次运行）"""
    AnalyticsBase.metadata.create_all(bind=analytics_engine)


def _count_unique_published_items(items: list[dict]) -> int:
    return len({(item["platform"], item["item_id"], item["month"]) for item in items})


def _build_published_item_params(r, clean_job_id: int, published_at: datetime) -> dict:
    base_corrected_qty = r["corrected_sales_qty"] if r["corrected_sales_qty"] is not None else r["sales_qty"]
    if r["sales_coefficient"] is not None:
        corrected_sales_qty = round(base_corrected_qty * r["sales_coefficient"])
    else:
        corrected_sales_qty = base_corrected_qty

    return {
        "publish_job_id":          0,   # 占位，稍后回填
        "clean_job_id":            clean_job_id,
        "match_result_id":         r["match_result_id"],
        "platform":                r["platform"],
        "month":                   r["month"],
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
        "corrected_sales_amount":  r["corrected_sales_amount"] if r["corrected_sales_amount"] is not None else r["sales_amount"],
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
            m.brand_name,
            m.model_code,
            m.model_name,
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

    # 2. 批量查 model_specs
    model_ids = list({r["model_id"] for r in rows})
    specs_map: dict[int, dict[str, str]] = {}
    if model_ids:
        placeholders = ",".join([f":id{i}" for i in range(len(model_ids))])
        specs_sql = text(f"SELECT model_id, spec_name, spec_value FROM model_specs WHERE model_id IN ({placeholders})")
        bind_params = {f"id{i}": mid for i, mid in enumerate(model_ids)}
        spec_rows = luotu_db.execute(specs_sql, bind_params).mappings().all()
        for sr in spec_rows:
            specs_map.setdefault(sr["model_id"], {})[sr["spec_name"]] = sr["spec_value"]

    # 2b. 批量查 match_result_attrs（按条目维度的属性，优先级高于 model_specs）
    match_result_ids = [r["match_result_id"] for r in rows]
    attrs_map: dict[int, dict[str, str]] = {}  # match_result_id → {attr_name: attr_value}
    if match_result_ids:
        placeholders = ",".join([f":mrid{i}" for i in range(len(match_result_ids))])
        attrs_sql = text(
            f"SELECT match_result_id, attr_name, attr_value FROM match_result_attrs "
            f"WHERE match_result_id IN ({placeholders})"
        )
        bind_params = {f"mrid{i}": mrid for i, mrid in enumerate(match_result_ids)}
        attr_rows = luotu_db.execute(attrs_sql, bind_params).mappings().all()
        for ar in attr_rows:
            attrs_map.setdefault(ar["match_result_id"], {})[ar["attr_name"]] = ar["attr_value"]

    # 3. 先删除同 clean_job_id 的旧发布数据（支持重复发布）
    old_ids_sql = text(
        "SELECT id FROM published_items WHERE clean_job_id = :cjid"
    )
    old_ids = [r[0] for r in analytics_db.execute(old_ids_sql, {"cjid": clean_job_id}).fetchall()]
    if old_ids:
        placeholders = ",".join([f":oid{i}" for i in range(len(old_ids))])
        bind_params = {f"oid{i}": oid for i, oid in enumerate(old_ids)}
        analytics_db.execute(
            text(f"DELETE FROM published_item_specs WHERE published_item_id IN ({placeholders})"),
            bind_params
        )
        analytics_db.execute(
            text("DELETE FROM published_items WHERE clean_job_id = :cjid"),
            {"cjid": clean_job_id}
        )

    # 4. 批量写入 published_items，使用 upsert（ON DUPLICATE KEY UPDATE）
    #    uq_published_item: UNIQUE(platform, item_id, month)
    upsert_sql = text("""
        INSERT INTO published_items
            (publish_job_id, clean_job_id, match_result_id, platform, month,
             category_lv0,
             category_lv1, category_lv2, category_lv3, category_lv4, category_lv5,
             item_id, item_name, item_image, item_url, ref_price, shop_name,
             sales_qty, sales_amount, price,
             brand_code, brand_name, model_code, model_name, category_name,
             calc_price, corrected_sales_qty, corrected_sales_amount,
             published_at)
        VALUES
            (:publish_job_id, :clean_job_id, :match_result_id, :platform, :month,
             :category_lv0,
             :category_lv1, :category_lv2, :category_lv3, :category_lv4, :category_lv5,
             :item_id, :item_name, :item_image, :item_url, :ref_price, :shop_name,
             :sales_qty, :sales_amount, :price,
             :brand_code, :brand_name, :model_code, :model_name, :category_name,
             :calc_price, :corrected_sales_qty, :corrected_sales_amount,
             :published_at)
        ON DUPLICATE KEY UPDATE
            publish_job_id         = VALUES(publish_job_id),
            clean_job_id           = VALUES(clean_job_id),
            match_result_id        = VALUES(match_result_id),
            item_name              = VALUES(item_name),
            item_image             = VALUES(item_image),
            item_url               = VALUES(item_url),
            ref_price              = VALUES(ref_price),
            shop_name              = VALUES(shop_name),
            sales_qty              = VALUES(sales_qty),
            sales_amount           = VALUES(sales_amount),
            price                  = VALUES(price),
            brand_code             = VALUES(brand_code),
            brand_name             = VALUES(brand_name),
            model_code             = VALUES(model_code),
            model_name             = VALUES(model_name),
            category_name          = VALUES(category_name),
            category_lv0           = VALUES(category_lv0),
            calc_price             = VALUES(calc_price),
            corrected_sales_qty    = VALUES(corrected_sales_qty),
            corrected_sales_amount = VALUES(corrected_sales_amount),
            published_at           = VALUES(published_at)
    """)

    items_to_insert = []
    for r in rows:
        items_to_insert.append(
            _build_published_item_params(r, clean_job_id, datetime.utcnow())
        )

    for item_dict in items_to_insert:
        analytics_db.execute(upsert_sql, item_dict)
    analytics_db.flush()

    # 5. 写入 published_item_specs
    #    upsert 后无法直接拿到 id，通过 (platform, item_id, month) 查回
    if specs_map or attrs_map:
        # 构建 (platform, item_id, month) → model_id 映射
        key_to_model: dict[tuple, int] = {
            (r["platform"], r["item_id"], r["month"]): r["model_id"]
            for r in rows
        }
        # 同时建立 (platform, item_id, month) → match_result_id 映射
        key_to_match_result: dict[tuple, int] = {
            (r["platform"], r["item_id"], r["month"]): r["match_result_id"]
            for r in rows
        }
        # 查回刚插入/更新的 published_item id
        placeholders = ",".join(
            f"(:p{i}, :ii{i}, :m{i})" for i in range(len(items_to_insert))
        )
        bind = {}
        for i, d in enumerate(items_to_insert):
            bind[f"p{i}"] = d["platform"]
            bind[f"ii{i}"] = d["item_id"]
            bind[f"m{i}"] = d["month"]
        id_rows = analytics_db.execute(
            text(f"SELECT id, platform, item_id, month FROM published_items "
                 f"WHERE (platform, item_id, month) IN ({placeholders})"),
            bind,
        ).fetchall()

        specs_to_insert = []
        for pub_id, platform, item_id, month in id_rows:
            model_id = key_to_model.get((platform, item_id, month))
            match_result_id = key_to_match_result.get((platform, item_id, month))
            if model_id is None:
                continue

            # model_specs 作为基础，match_result_attrs 覆盖（条目级属性优先）
            merged: dict[str, str] = dict(specs_map.get(model_id, {}))
            merged.update(attrs_map.get(match_result_id, {}))

            for spec_name, spec_value in merged.items():
                specs_to_insert.append(PublishedItemSpec(
                    published_item_id=pub_id,
                    spec_name=spec_name,
                    spec_value=spec_value,
                ))

        if specs_to_insert:
            analytics_db.add_all(specs_to_insert)

    analytics_db.commit()
    return {
        "published_count": _count_unique_published_items(items_to_insert),
        "skipped_pending_count": skipped_pending_count,
    }
