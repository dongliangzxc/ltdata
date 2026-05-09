"""
Excel 解析服务：将原始上传的 Excel 文件统一解析为标准字段结构。
支持京东/天猫/淘宝三种原始数据格式差异。
"""
import pandas as pd
from pathlib import Path
from typing import Optional


# 京东原始数据列映射
JD_COLUMN_MAP = {
    "平台": "platform",
    "月": "month",
    "Lv0类目名称(逐月固定)": "category_lv0",
    "Lv1类目名称(逐月固定)": "category_lv1",
    "Lv2类目名称(逐月固定)": "category_lv2",
    "宝贝ID": "item_id",
    "宝贝名称": "item_name",
    "宝贝图片": "item_image",
    "宝贝链接": "item_url",
    "参考价格": "ref_price",
    "宝贝品牌(bid)": "brand_raw",
    "宝贝店铺名称": "shop_name",
    "销量": "sales_qty",
    "销售额": "sales_amount",
    "价格": "price",
    "品牌": "brand_std",
    "机型": "model_std",
}

# 天猫/淘宝原始数据列映射（Lv 结构不同）
TM_TB_COLUMN_MAP = {
    "平台": "platform",
    "月": "month",
    "Lv1类目名称(逐月固定)": "category_lv1",
    "Lv2类目名称(逐月固定)": "category_lv2",
    "Lv3类目名称(逐月固定)": "category_lv3",
    "Lv4类目名称(逐月固定)": "category_lv4",
    "Lv5类目名称(逐月固定)": "category_lv5",
    "宝贝ID": "item_id",
    "宝贝名称": "item_name",
    "宝贝图片": "item_image",
    "宝贝链接": "item_url",
    "参考价格": "ref_price",
    "宝贝品牌": "brand_raw",
    "宝贝店铺名称": "shop_name",
    "销量": "sales_qty",
    "销售额": "sales_amount",
    "价格": "price",
    "品牌": "brand_std",
    "机型": "model_std",
}

STANDARD_FIELDS = [
    "platform", "month",
    "category_lv0", "category_lv1", "category_lv2",
    "category_lv3", "category_lv4", "category_lv5",
    "item_id", "item_name", "item_image", "item_url",
    "ref_price", "brand_raw", "shop_name",
    "sales_qty", "sales_amount", "price",
    "brand_std", "model_std",
]


def detect_platform(columns: list[str]) -> str:
    """根据列名特征推断平台类型"""
    col_set = set(columns)
    if "Lv0类目名称(逐月固定)" in col_set:
        return "JD"
    if "天猫" in str(columns):
        return "TM"
    return "TB"


def parse_raw_excel(file_path: str | Path) -> tuple[list[dict], str, str]:
    """
    解析原始数据 Excel 文件。
    返回: (records, platform, month_range)
    """
    suffix = Path(file_path).suffix.lower()
    if suffix == ".csv":
        try:
            df = pd.read_csv(file_path, dtype=str, encoding="utf-8-sig")
        except (UnicodeDecodeError, pd.errors.ParserError):
            df = pd.read_csv(file_path, dtype=str, encoding="gbk")
    else:
        df = pd.read_excel(file_path, sheet_name=0, dtype=str)
    df.columns = [str(c).strip() for c in df.columns]

    # 推断平台并选择列映射
    platform = detect_platform(list(df.columns))
    col_map = JD_COLUMN_MAP if platform == "JD" else TM_TB_COLUMN_MAP

    # 只保留识别到的列
    rename_map = {k: v for k, v in col_map.items() if k in df.columns}
    df = df.rename(columns=rename_map)

    # 补全缺失标准字段
    for field in STANDARD_FIELDS:
        if field not in df.columns:
            df[field] = None

    df = df[STANDARD_FIELDS].copy()

    # 类型转换
    for num_col in ["sales_qty"]:
        df[num_col] = pd.to_numeric(df[num_col], errors="coerce").astype("Int64")
    for float_col in ["ref_price", "sales_amount", "price"]:
        df[float_col] = pd.to_numeric(df[float_col], errors="coerce")
    for str_col in ["item_id", "platform", "brand_raw", "brand_std", "model_std", "shop_name"]:
        df[str_col] = df[str_col].where(df[str_col].notna(), None)

    # month 转整型
    df["month"] = pd.to_numeric(df["month"], errors="coerce").astype("Int64")

    # 推断 month_range
    months = df["month"].dropna().unique().tolist()
    months_sorted = sorted([int(m) for m in months])
    if months_sorted:
        month_range = f"{months_sorted[0]}-{months_sorted[-1]}" if len(months_sorted) > 1 else str(months_sorted[0])
    else:
        month_range = ""

    # 推断并标准化 platform 值（从数据中读取，统一写成小写标准值）
    _PLATFORM_NORM = {"京东": "jd", "天猫": "tmall", "淘宝": "taobao", "苏宁": "suning"}
    if "platform" in df.columns and df["platform"].notna().any():
        platform_val = df["platform"].dropna().iloc[0]
        platform_str = str(platform_val)
        for kw, std in _PLATFORM_NORM.items():
            if kw in platform_str:
                platform = std.upper()   # 文件级别沿用大写（JD/TM/TB 约定）
                break
        # 每行的 platform 字段也标准化为小写（jd/tmall/taobao）
        def _norm_platform(v):
            if v is None:
                return None
            s = str(v)
            for kw, std in _PLATFORM_NORM.items():
                if kw in s:
                    return std
            return v
        df["platform"] = df["platform"].apply(_norm_platform)

    raw_records = df.where(df.notna(), None).to_dict(orient="records")

    # MySQL 不支持 float nan，全部转成 None
    import math

    def clean_val(v):
        if v is None:
            return None
        try:
            if isinstance(v, float) and math.isnan(v):
                return None
        except (TypeError, ValueError):
            pass
        # pandas Int64 NA
        try:
            import pandas as pd
            if pd.isna(v):
                return None
        except (TypeError, ValueError):
            pass
        return v

    records = [{k: clean_val(v) for k, v in row.items()} for row in raw_records]
    return records, platform, month_range
