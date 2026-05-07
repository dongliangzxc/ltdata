"""
数据清洗服务：
1. 干扰词过滤（noise_words）→ 命中写入 filtered_items，跳过
2. 品牌写法标准化（brand_aliases）→ brand_raw 查表覆盖 brand_std
3. 去重（同 item_id + month + shop_name 保留第一条）
4. brand_std 兜底补全（无匹配时用 brand_raw）
"""
from sqlalchemy.orm import Session
from app.models.schemas import (
    RawDataRecord, CleanedDataRecord, CleanJobRecord,
    NoiseWord, FilteredItem, BrandAlias,
)


def _load_noise_words(db: Session) -> list[tuple[str, str]]:
    """返回 [(keyword_upper, match_field), ...] 只取 active"""
    rows = db.query(NoiseWord).filter(NoiseWord.is_active == 1).all()
    return [(r.keyword.upper(), r.match_field) for r in rows]


def _load_brand_alias_map(db: Session) -> dict[str, str]:
    """返回 {alias_name_upper: brand_code} 只取 active"""
    rows = db.query(BrandAlias).filter(BrandAlias.is_active == 1).all()
    return {r.alias_name.upper(): r.brand_code for r in rows}


def _check_noise(item_name: str | None, shop_name: str | None, brand_raw: str | None,
                 noise_words: list[tuple[str, str]]) -> str | None:
    """若命中干扰词返回该关键词，否则返回 None"""
    field_map = {
        "item_name": (item_name or "").upper(),
        "shop_name": (shop_name or "").upper(),
        "brand_raw": (brand_raw or "").upper(),
    }
    for keyword, field in noise_words:
        if keyword in field_map.get(field, ""):
            return keyword
    return None


def run_clean(db: Session, clean_job_id: int, file_ids: list[int], rules: dict) -> int:
    """执行清洗逻辑，返回写入 cleaned_data 的行数"""
    dedup: bool = rules.get("dedup", True)

    # ── 加载规则表 ─────────────────────────────────────────────
    noise_words = _load_noise_words(db)
    brand_alias_map = _load_brand_alias_map(db)

    records = db.query(RawDataRecord).filter(RawDataRecord.file_id.in_(file_ids)).all()

    cleaned: list[CleanedDataRecord] = []
    filtered: list[FilteredItem] = []
    seen_keys: set = set()

    for r in records:
        # ── Step 1: 干扰词过滤 ───────────────────────────────────
        hit_keyword = _check_noise(r.item_name, r.shop_name, r.brand_raw, noise_words)
        if hit_keyword is not None:
            filtered.append(FilteredItem(
                raw_data_id=r.id,
                clean_job_id=clean_job_id,
                matched_keyword=hit_keyword,
            ))
            continue

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

    db.commit()
    return len(cleaned)
