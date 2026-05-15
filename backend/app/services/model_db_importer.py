"""
model_db_importer.py
从品类数据库 Excel 清洗并批量写入 models / model_specs / item_url_mappings。
"""
import re
from collections import defaultdict
from typing import Optional

from sqlalchemy.orm import Session

from app.models.schemas import Category, ModelRecord, ModelSpec, ItemUrlMapping

# Excel 属性列名 → model_specs.spec_name 映射
# 注意：当前映射为耳机品类（headphone）专用列名；
# 导入其他品类时需扩展此映射或改为按品类动态加载。
ATTR_COL_MAP: dict[str, str] = {
    "佩戴类型": "wearing_type",
    "In-ear Type": "inear_type",
    "开放式外观": "open_back",
    "Power Type": "power_type",
    "Bluetooth Version": "bluetooth_version",
    "Sport": "sport",
    "Gaming": "gaming",
    "HIFI": "hifi",
    "ANC": "anc",
    "ENC": "enc",
    "Fast Charging": "fast_charging",
    "IP Marking": "ip_marking",
    "Health Monitoring": "health_monitoring",
    "Touch Screen Monitor": "touch_screen",
    "骨传导": "bone_conduction",
    "AI": "ai",
    "AI+功能": "ai_features",
}

_NULL_VALUES = {"", "NULL", "nan", "None", "none"}


def is_dirty_model(model) -> bool:
    """型号脏数据检测：空 / 纯数字 / 长度≤2 / id:xxx 或 id=xxx 开头。"""
    if model is None:
        return True
    s = str(model).strip()
    if s in _NULL_VALUES:
        return True
    if len(s) <= 2:
        return True
    if s.isdigit():
        return True
    if re.match(r"id[:=]", s, re.IGNORECASE):
        return True
    return False


def is_dirty_brand(brand) -> bool:
    """品牌脏数据检测：空 / 长度≤2 / 中文字符数>8（店铺名）。"""
    if brand is None:
        return True
    s = str(brand).strip()
    if s in _NULL_VALUES:
        return True
    if len(s) <= 2:
        return True
    chinese_count = sum(1 for c in s if "\u4e00" <= c <= "\u9fff")
    if chinese_count > 8:
        return True
    return False


def normalize_platform(platform) -> str:
    """平台字段标准化为系统内部值。"""
    mapping = {
        "jd": "jd", "JD": "jd", "京东": "jd",
        "淘宝": "taobao", "taobao": "taobao",
        "天猫": "tmall", "tmall": "tmall",
    }
    raw = str(platform).strip()
    return mapping.get(raw, raw.lower())


def extract_item_id(url, platform: str) -> Optional[str]:
    """从商品链接提取 item_id；失败返回 None。"""
    if not url:
        return None
    s = str(url).strip()
    if platform == "jd":
        m = re.search(r"/(\d+)\.html", s)
        return m.group(1) if m else None
    else:
        m = re.search(r"[?&]id=(\d+)", s)
        return m.group(1) if m else None


def has_attributes(row: dict, attr_cols: list) -> bool:
    """至少有一个非空属性列则返回 True。"""
    for col in attr_cols:
        v = row.get(col)
        if v is not None and str(v).strip() not in _NULL_VALUES:
            return True
    return False


def import_model_db(
    excel_path: str,
    category_code: str,
    db: Session,
    dry_run: bool = False,
) -> dict:
    """
    从 Excel 文件读取、清洗并写入型号库。

    Returns:
        stats dict — 包含各类计数，供 CLI 输出报告。
    """
    import openpyxl

    # 校验品类存在
    if db.query(Category).filter(Category.code == category_code).first() is None:
        raise ValueError(f"Category '{category_code}' not found in database")

    wb = openpyxl.load_workbook(excel_path, read_only=True, data_only=True)
    ws = wb.active
    all_rows = list(ws.iter_rows(values_only=True))
    headers = list(all_rows[0])
    attr_cols = [c for c in headers if c in ATTR_COL_MAP]

    stats = {
        "total": len(all_rows) - 1,
        "skip_model": 0,
        "skip_brand": 0,
        "skip_url": 0,
        "skip_no_attr": 0,
        "valid_rows": 0,
        "unique_models": 0,
        "models_new": 0,
        "models_existing": 0,
        "specs_written": 0,
        "urls_new": 0,
        "url_extract_fail": 0,
    }

    # ── 收集有效行，按 (brand, model) 分组 ──────────────────────
    groups: dict[tuple, dict] = defaultdict(lambda: {"attrs_row": None, "urls": []})

    for raw in all_rows[1:]:
        row = dict(zip(headers, raw))
        brand = str(row.get("品牌") or "").strip()
        model = str(row.get("型号") or "").strip()
        url   = str(row.get("宝贝链接") or "").strip()
        platform = normalize_platform(row.get("平台", ""))

        if is_dirty_model(model):
            stats["skip_model"] += 1
            continue
        if is_dirty_brand(brand):
            stats["skip_brand"] += 1
            continue
        if not url or url in _NULL_VALUES:
            stats["skip_url"] += 1
            continue
        if not has_attributes(row, attr_cols):
            stats["skip_no_attr"] += 1
            continue

        stats["valid_rows"] += 1
        key = (brand, model)

        if groups[key]["attrs_row"] is None:
            groups[key]["attrs_row"] = row

        item_id = extract_item_id(url, platform)
        if item_id:
            groups[key]["urls"].append(
                {"platform": platform, "item_id": item_id, "item_url": url}
            )
        else:
            stats["url_extract_fail"] += 1

    stats["unique_models"] = len(groups)

    if dry_run:
        return stats

    # ── 写库 ────────────────────────────────────────────────────
    for (brand, model_code), group in groups.items():
        # 1. models — INSERT IGNORE 语义
        existing = db.query(ModelRecord).filter_by(
            brand_code=brand, model_code=model_code
        ).first()
        if existing:
            stats["models_existing"] += 1
            model_id = existing.id
        else:
            rec = ModelRecord(
                brand_code=brand,
                model_code=model_code,
                category_code=category_code,
            )
            db.add(rec)
            db.flush()
            model_id = rec.id
            stats["models_new"] += 1

        # 2. model_specs — 删旧插新（有意为之：简单实现保证幂等；
        #    当前 model_specs.id 无外键依赖，重跑安全）
        db.query(ModelSpec).filter(ModelSpec.model_id == model_id).delete()
        attrs_row = group["attrs_row"]
        for col, spec_name in ATTR_COL_MAP.items():
            if col not in attrs_row:
                continue
            v = attrs_row.get(col)
            if v is None or str(v).strip() in _NULL_VALUES:
                continue
            db.add(ModelSpec(
                model_id=model_id,
                spec_name=spec_name,
                spec_value=str(v).strip(),
            ))
            stats["specs_written"] += 1

        # 3. item_url_mappings — upsert
        for u in group["urls"]:
            existing_url = db.query(ItemUrlMapping).filter_by(
                platform=u["platform"], item_id=u["item_id"]
            ).first()
            if existing_url:
                existing_url.model_id = model_id
                existing_url.item_url = u["item_url"]
            else:
                db.add(ItemUrlMapping(
                    platform=u["platform"],
                    item_id=u["item_id"],
                    item_url=u["item_url"],
                    model_id=model_id,
                ))
                stats["urls_new"] += 1

    db.commit()
    return stats
