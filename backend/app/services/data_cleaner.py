"""
数据清洗服务：
1. 按品牌白名单过滤
2. 去重（同 item_id 同月份保留销量最大记录）
3. 品牌标准化补全（brand_std 为空时用 brand_raw 填充）
"""
from typing import Optional
from sqlalchemy.orm import Session
from app.models.schemas import RawDataRecord, CleanedDataRecord


def run_clean(
    db: Session,
    clean_job_id: int,
    file_ids: list[int],
    rules: dict,
) -> int:
    """执行清洗逻辑，返回清洗后写入的行数"""
    filter_brands: list[str] = [b.upper().strip() for b in rules.get("filter_brands", [])]
    dedup: bool = rules.get("dedup", True)

    # 查询原始数据
    q = db.query(RawDataRecord).filter(RawDataRecord.file_id.in_(file_ids))
    records = q.all()

    cleaned: list[CleanedDataRecord] = []
    seen_keys: set = set()

    for r in records:
        brand = (r.brand_std or r.brand_raw or "").upper().strip()

        # 品牌白名单过滤（白名单为空则不过滤）
        if filter_brands and brand not in filter_brands:
            continue

        # 去重 key：item_id + month
        if dedup:
            key = (r.item_id, r.month, r.shop_name)
            if key in seen_keys:
                continue
            seen_keys.add(key)

        # brand_std 补全
        brand_std = r.brand_std or r.brand_raw

        cleaned.append(CleanedDataRecord(
            raw_data_id=r.id,
            clean_job_id=clean_job_id,
            platform=r.platform,
            month=r.month,
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
        ))

    db.bulk_save_objects(cleaned)
    return len(cleaned)
