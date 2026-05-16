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
    _PLATFORM_NORM = {"京东": "jd", "天猫": "tmall", "淘宝": "taobao", "苏宁": "suning", "抖音": "douyin"}
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


# ─── P9: mapping-based parse ─────────────────────────────────

#: Standard field names that can be targeted by mapping
STANDARD_FIELD_SET = set(STANDARD_FIELDS)

#: Platform keyword → lowercase standard code
_PLATFORM_NORM = {"京东": "jd", "天猫": "tmall", "淘宝": "taobao", "苏宁": "suning", "抖音": "douyin"}


def parse_with_mapping(
    file_path,
    mapping: dict,
    ignore_columns: list,
) -> tuple:
    """
    Parse an Excel/CSV file using a user-defined column mapping.

    Args:
        file_path: Path to the Excel/CSV file
        mapping: {"original_col": "standard_field | __ext__"}
                 Columns not in mapping and not ignored go to extra_data automatically
        ignore_columns: These columns are discarded entirely

    Returns:
        (records, platform, month_range)
        Each record has standard fields + "extra_data": {"col": value}
    """
    import math
    from pathlib import Path as _Path

    fp = _Path(file_path)
    suffix = fp.suffix.lower()
    if suffix == ".csv":
        try:
            df = pd.read_csv(fp, dtype=str, encoding="utf-8-sig")
        except (UnicodeDecodeError, Exception):
            df = pd.read_csv(fp, dtype=str, encoding="gbk")
    else:
        df = pd.read_excel(fp, sheet_name=0, dtype=str)
    df.columns = [str(c).strip() for c in df.columns]

    ignore_set = set(ignore_columns)

    # Categorise columns
    std_rename: dict = {}   # original col → standard field name
    ext_cols: list = []     # original col → extra_data

    for col in df.columns:
        if col in ignore_set:
            continue
        target = mapping.get(col)
        if target and target != "__ext__" and target in STANDARD_FIELD_SET:
            std_rename[col] = target
        else:
            # unmapped or explicitly __ext__
            ext_cols.append(col)

    # Build standard fields dataframe
    if std_rename:
        df_std = df[list(std_rename.keys())].rename(columns=std_rename)
    else:
        df_std = pd.DataFrame(index=df.index)

    # Ensure all standard fields exist
    for field in STANDARD_FIELDS:
        if field not in df_std.columns:
            df_std[field] = None

    # Type conversions
    for num_col in ["sales_qty"]:
        df_std[num_col] = pd.to_numeric(df_std[num_col], errors="coerce").astype("Int64")
    for float_col in ["ref_price", "sales_amount", "price"]:
        df_std[float_col] = pd.to_numeric(df_std[float_col], errors="coerce")
    for str_col in ["item_id", "platform", "brand_raw", "brand_std", "model_std", "shop_name"]:
        df_std[str_col] = df_std[str_col].where(df_std[str_col].notna(), None)
    df_std["month"] = pd.to_numeric(df_std["month"], errors="coerce").astype("Int64")

    # Normalize platform — derive file-level label and per-row lowercase value
    platform_label = "UNKNOWN"
    if df_std["platform"].notna().any():
        first_val = str(df_std["platform"].dropna().iloc[0])
        for kw, std in _PLATFORM_NORM.items():
            if kw in first_val:
                platform_label = std.upper()
                break

        def _norm_platform(v):
            if v is None:
                return None
            s = str(v)
            for kw, std_val in _PLATFORM_NORM.items():
                if kw in s:
                    return std_val
            return v

        df_std["platform"] = df_std["platform"].apply(_norm_platform)

    # month_range
    months = df_std["month"].dropna().unique().tolist()
    months_sorted = sorted([int(m) for m in months])
    if len(months_sorted) > 1:
        month_range = f"{months_sorted[0]}-{months_sorted[-1]}"
    elif months_sorted:
        month_range = str(months_sorted[0])
    else:
        month_range = ""

    # Build extra_data
    df_ext = df[ext_cols] if ext_cols else pd.DataFrame(index=df.index)

    def _clean(v):
        if v is None:
            return None
        # pandas NA / numpy nan → None（最初にチェック）
        try:
            if pd.isna(v):
                return None
        except (TypeError, ValueError):
            pass
        try:
            if isinstance(v, float) and math.isnan(v):
                return None
        except (TypeError, ValueError):
            pass
        # numpy.int64 / numpy.float64 / pandas Int64 → Python ネイティブ型
        try:
            return v.item()
        except AttributeError:
            pass
        return v

    records = []
    for i in range(len(df_std)):
        row = {k: _clean(v) for k, v in df_std.iloc[i].items()}
        extra = {}
        if ext_cols:
            extra = {col: _clean(df_ext.iloc[i][col]) for col in ext_cols}
            extra = {k: v for k, v in extra.items() if v is not None}
        row["extra_data"] = extra if extra else None
        records.append(row)

    return records, platform_label, month_range
