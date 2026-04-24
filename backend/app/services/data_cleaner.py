"""
数据清洗服务：
1. 去重（同 item_id + month + shop_name 保留第一条）
2. brand_std 补全（brand_std 为空时用 brand_raw 填充）
"""
from sqlalchemy.orm import Session
from app.models.schemas import RawDataRecord, CleanedDataRecord


def run_clean(
    db: Session,
    clean_job_id: int,
    file_ids: list[int],
    rules: dict,
) -> int:
    """执行清洗逻辑，返回清洗后写入的行数"""
    dedup: bool = rules.get("dedup", True)

    records = db.query(RawDataRecord).filter(RawDataRecord.file_id.in_(file_ids)).all()

    cleaned: list[CleanedDataRecord] = []
    seen_keys: set = set()

    for r in records:
        # 去重 key：item_id + month + shop_name
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
