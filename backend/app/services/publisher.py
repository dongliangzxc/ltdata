"""
publisher.py — 将已匹配/已确认数据发布到 luotu_analytics 分析库

逻辑：
1. 查 match_results WHERE clean_job_id=? AND match_status IN ('matched', 'confirmed')
2. JOIN raw_data 取基础字段，JOIN models 取品牌/型号/品类信息
3. 批量查 model_specs → {model_id: {spec_name: spec_value}}
4. 写入 luotu_analytics.published_items + published_item_specs
5. 记录 luotu.publish_jobs
"""

from sqlalchemy.orm import Session
from sqlalchemy import text
from app.models.analytics_db import AnalyticsBase, analytics_engine, PublishedItem, PublishedItemSpec

def _ensure_analytics_tables():
    """确保分析库表已创建（首次运行）"""
    AnalyticsBase.metadata.create_all(bind=analytics_engine)


def run_publish(luotu_db: Session, analytics_db: Session, clean_job_id: int) -> dict:
    """
    执行发布：从 luotu 读取匹配结果，写入 luotu_analytics。
    支持重复执行（先删除同 clean_job_id 的旧数据）。
    返回 {"published_count": N}
    """
    _ensure_analytics_tables()

    # 1. 查询已匹配/已确认的 match_results，JOIN raw_data + models
    sql = text("""
        SELECT
            mr.id           AS match_result_id,
            rd.platform,
            rd.month,
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
            m.category_name,
            m.id            AS model_id
        FROM match_results mr
        JOIN raw_data rd  ON rd.id = mr.raw_data_id
        JOIN models m     ON m.id  = mr.model_id
        WHERE mr.clean_job_id = :clean_job_id
          AND mr.match_status IN ('matched', 'confirmed')
    """)
    rows = luotu_db.execute(sql, {"clean_job_id": clean_job_id}).mappings().all()

    if not rows:
        return {"published_count": 0}

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

    # 4. 批量写入 published_items（暂不带 publish_job_id，稍后回填）
    items_to_insert = []
    for r in rows:
        items_to_insert.append(PublishedItem(
            publish_job_id=0,        # 占位，稍后回填
            clean_job_id=clean_job_id,
            match_result_id=r["match_result_id"],
            platform=r["platform"],
            month=r["month"],
            category_lv1=r["category_lv1"],
            category_lv2=r["category_lv2"],
            category_lv3=r["category_lv3"],
            category_lv4=r["category_lv4"],
            category_lv5=r["category_lv5"],
            item_id=r["item_id"],
            item_name=r["item_name"],
            item_image=r["item_image"],
            item_url=r["item_url"],
            ref_price=r["ref_price"],
            shop_name=r["shop_name"],
            sales_qty=r["sales_qty"],
            sales_amount=r["sales_amount"],
            price=r["price"],
            brand_code=r["brand_code"],
            brand_name=r["brand_name"],
            model_code=r["model_code"],
            model_name=r["model_name"],
            category_name=r["category_name"],
        ))

    analytics_db.add_all(items_to_insert)
    analytics_db.flush()  # 获取自增 id

    # 5. 写入 published_item_specs
    specs_to_insert = []
    for item_obj, r in zip(items_to_insert, rows):
        model_specs = specs_map.get(r["model_id"], {})
        for spec_name, spec_value in model_specs.items():
            specs_to_insert.append(PublishedItemSpec(
                published_item_id=item_obj.id,
                spec_name=spec_name,
                spec_value=spec_value,
            ))

    if specs_to_insert:
        analytics_db.add_all(specs_to_insert)

    analytics_db.commit()
    return {"published_count": len(items_to_insert)}
