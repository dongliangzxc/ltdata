"""
model_db_importer.py
从品类数据库 Excel 清洗并批量写入 models / model_specs / item_url_mappings。
"""
import re
from typing import Optional

from sqlalchemy.orm import Session

from app.models.schemas import Category, ModelRecord, ModelSpec, ItemUrlMapping

# Excel 属性列名 → model_specs.spec_name 映射
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
