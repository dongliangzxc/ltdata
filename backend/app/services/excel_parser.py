"""
Excel 解析服务：将原始上传的 Excel 文件统一解析为标准字段结构。
支持京东/天猫/淘宝以及海外 Amazon / Shopee 平台的原始数据格式差异。

大文件使用分块读取：
- CSV: pandas ``chunksize``
- XLSX: openpyxl ``read_only=True`` 逐行读取
- XLS: pandas 全量读取（.xls 本身最多 6.5 万行，风险可控）

原有 ``parse_raw_excel`` / ``parse_with_mapping`` 接口保持不变；
上传流程可以改用 ``iter_raw_chunks`` / ``iter_mapped_chunks`` 流式处理。
"""
import math
from datetime import date, datetime
from pathlib import Path
from typing import Iterator, Optional

import pandas as pd


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

#: Standard field names that can be targeted by mapping
STANDARD_FIELD_SET = set(STANDARD_FIELDS)

#: Platform keyword → lowercase standard code
_PLATFORM_NORM = {
    "京东": "jd", "天猫": "tmall", "淘宝": "taobao", "苏宁": "suning", "抖音": "douyin",
    "亚马逊": "amazon", "amazon": "amazon", "amz": "amazon",
    "西皮": "shopee", "虾皮": "shopee", "shopee": "shopee",
}

DEFAULT_CHUNK_SIZE = 5000


def detect_platform(columns: list[str]) -> str:
    """根据列名特征推断平台类型"""
    col_set = set(columns)
    if "Lv0类目名称(逐月固定)" in col_set:
        return "JD"
    if "天猫" in str(columns):
        return "TM"
    return "TB"


# ─── 通用工具 ─────────────────────────────────────────────────


def _clean(v):
    """pandas NA / numpy nan / numpy scalar → Python 原生值。"""
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(v, float) and math.isnan(v):
        return None
    try:
        return v.item()
    except AttributeError:
        return v


def _stringify_cell(v):
    """把 openpyxl 读出的值转成与 pandas dtype=str 接近的字符串。"""
    if v is None:
        return None
    if isinstance(v, str):
        return v
    if isinstance(v, (datetime, date)):
        return v.isoformat(sep=" ") if isinstance(v, datetime) else v.isoformat()
    return str(v)


def _dedupe_columns(columns: list[str]) -> list[str]:
    """模拟 pandas 对重复列名的处理：a, a.1, a.2 ..."""
    seen: dict[str, int] = {}
    out: list[str] = []
    for col in columns:
        name = str(col).strip() if col is not None else ""
        if name in seen:
            seen[name] += 1
            out.append(f"{name}.{seen[name]}")
        else:
            seen[name] = 0
            out.append(name)
    return out


def _detect_csv_encoding(file_path: Path) -> str:
    head = file_path.open("rb").read(65536)
    try:
        head.decode("utf-8-sig")
        return "utf-8-sig"
    except UnicodeDecodeError:
        return "gbk"


# ─── 分块读取 ─────────────────────────────────────────────────


def _iter_dataframe_chunks(file_path: str | Path, chunk_size: int = DEFAULT_CHUNK_SIZE) -> Iterator[pd.DataFrame]:
    """按行分块读取 CSV/XLSX/XLS，返回 DataFrame 块。"""
    fp = Path(file_path)
    suffix = fp.suffix.lower()

    if suffix == ".csv":
        encoding = _detect_csv_encoding(fp)
        reader = pd.read_csv(
            fp,
            dtype=str,
            encoding=encoding,
            chunksize=chunk_size,
        )
        for df in reader:
            df.columns = [str(c).strip() for c in df.columns]
            yield df
        return

    if suffix in (".xlsx", ".xlsm"):
        import openpyxl

        workbook = openpyxl.load_workbook(fp, read_only=True, data_only=True)
        try:
            sheet = workbook.active
            rows = sheet.iter_rows(values_only=True)
            header = next(rows, None)
            if header is None:
                return
            columns = _dedupe_columns(list(header))
            width = len(columns)
            batch: list[list] = []

            for row in rows:
                values = list(row[:width])
                if len(values) < width:
                    values.extend([None] * (width - len(values)))
                if all(v is None or (isinstance(v, str) and not v.strip()) for v in values):
                    continue
                batch.append([_stringify_cell(v) for v in values])
                if len(batch) >= chunk_size:
                    yield pd.DataFrame(batch, columns=columns, dtype=object)
                    batch = []
            if batch:
                yield pd.DataFrame(batch, columns=columns, dtype=object)
        finally:
            workbook.close()
        return

    # .xls：pandas 全量读取，按块切分（文件本身最多 65536 行）
    df = pd.read_excel(fp, sheet_name=0, dtype=str)
    df.columns = [str(c).strip() for c in df.columns]
    for start in range(0, len(df), chunk_size):
        yield df.iloc[start:start + chunk_size].copy()


def count_data_rows(file_path: str | Path) -> Optional[int]:
    """快速估算数据行数，仅用于进度展示；失败返回 None。"""
    fp = Path(file_path)
    suffix = fp.suffix.lower()
    try:
        if suffix == ".csv":
            with fp.open("rb") as f:
                lines = sum(1 for _ in f)
            return max(lines - 1, 0)
        if suffix in (".xlsx", ".xlsm"):
            import openpyxl

            workbook = openpyxl.load_workbook(fp, read_only=True, data_only=True)
            try:
                return max((workbook.active.max_row or 1) - 1, 0)
            finally:
                workbook.close()
        df = pd.read_excel(fp, sheet_name=0, dtype=str)
        return int(len(df))
    except Exception:
        return None


# ─── 原始数据（无 mapping）────────────────────────────────────


def _normalize_raw_df(df: pd.DataFrame, rename_map: dict) -> tuple[list[dict], list[int], Optional[str]]:
    df = df.rename(columns=rename_map)
    for field in STANDARD_FIELDS:
        if field not in df.columns:
            df[field] = None
    df = df[STANDARD_FIELDS].copy()

    for num_col in ["sales_qty"]:
        df[num_col] = pd.to_numeric(df[num_col], errors="coerce").astype("Int64")
    for float_col in ["ref_price", "sales_amount", "price"]:
        df[float_col] = pd.to_numeric(df[float_col], errors="coerce")
    for str_col in ["item_id", "platform", "brand_raw", "brand_std", "model_std", "shop_name"]:
        df[str_col] = df[str_col].where(df[str_col].notna(), None)
    df["month"] = pd.to_numeric(df["month"], errors="coerce").astype("Int64")

    months = [int(m) for m in df["month"].dropna().unique().tolist()]

    first_platform = None
    if df["platform"].notna().any():
        first_platform = _clean(df["platform"].dropna().iloc[0])

        def _norm_platform(v):
            if v is None:
                return None
            s = str(v)
            s_lower = s.lower()
            for kw, std in _PLATFORM_NORM.items():
                if kw.lower() in s_lower:
                    return std
            return v

        df["platform"] = df["platform"].apply(_norm_platform)

    std_columns = list(df.columns)
    records = [
        {k: _clean(v) for k, v in zip(std_columns, values)}
        for values in df.itertuples(index=False, name=None)
    ]
    return records, months, first_platform


def iter_raw_chunks(
    file_path: str | Path,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> Iterator[tuple[list[dict], str, list[int]]]:
    """流式解析原始数据：逐块返回 (records, platform, months)。"""
    platform_label = "TB"
    first_chunk = True
    rename_map: dict = {}
    first_platform_seen = False

    for df in _iter_dataframe_chunks(file_path, chunk_size):
        if first_chunk:
            platform_label = detect_platform(list(df.columns))
            col_map = JD_COLUMN_MAP if platform_label == "JD" else TM_TB_COLUMN_MAP
            rename_map = {k: v for k, v in col_map.items() if k in df.columns}
            first_chunk = False

        records, months, first_platform = _normalize_raw_df(df, rename_map)
        if not first_platform_seen and first_platform is not None:
            first_platform_seen = True
            first_str = str(first_platform).lower()
            for kw, std in _PLATFORM_NORM.items():
                if kw.lower() in first_str:
                    platform_label = std.upper()
                    break
        yield records, platform_label, months

    if first_chunk:
        # 空文件/空表：仍然返回一个稳定的平台标签
        yield [], platform_label, []


def parse_raw_excel(file_path: str | Path) -> tuple[list[dict], str, str]:
    """兼容旧接口：一次性返回全部 records。新代码建议用 iter_raw_chunks。"""
    records: list[dict] = []
    platform = "TB"
    months: set[int] = set()
    for chunk, label, chunk_months in iter_raw_chunks(file_path):
        records.extend(chunk)
        platform = label
        months.update(chunk_months)
    month_range = _month_range(months)
    return records, platform, month_range


# ─── mapping 解析 ─────────────────────────────────────────────


def _prepare_mapped_columns(df: pd.DataFrame, mapping: dict, ignore_columns: list):
    ignore_set = set(ignore_columns)
    std_rename: dict = {}
    ext_cols: list = []
    for col in df.columns:
        if col in ignore_set:
            continue
        target = mapping.get(col)
        if target and target != "__ext__" and target in STANDARD_FIELD_SET:
            std_rename[col] = target
        else:
            ext_cols.append(col)
    return std_rename, ext_cols


def _normalize_mapped_df(
    df: pd.DataFrame,
    mapping: dict,
    ignore_columns: list,
) -> tuple[list[dict], Optional[str], list[int]]:
    std_rename, ext_cols = _prepare_mapped_columns(df, mapping, ignore_columns)

    if std_rename:
        df_std = df[list(std_rename.keys())].rename(columns=std_rename)
    else:
        df_std = pd.DataFrame(index=df.index)

    for field in STANDARD_FIELDS:
        if field not in df_std.columns:
            df_std[field] = None

    for num_col in ["sales_qty"]:
        df_std[num_col] = pd.to_numeric(df_std[num_col], errors="coerce").astype("Int64")
    for float_col in ["ref_price", "sales_amount", "price"]:
        df_std[float_col] = pd.to_numeric(df_std[float_col], errors="coerce")
    for str_col in ["item_id", "platform", "brand_raw", "brand_std", "model_std", "shop_name"]:
        df_std[str_col] = df_std[str_col].where(df_std[str_col].notna(), None)
    df_std["month"] = pd.to_numeric(df_std["month"], errors="coerce").astype("Int64")

    first_platform = None
    if df_std["platform"].notna().any():
        first_platform = _clean(df_std["platform"].dropna().iloc[0])

        def _norm_platform(v):
            if v is None:
                return None
            s = str(v)
            s_lower = s.lower()
            for kw, std_val in _PLATFORM_NORM.items():
                if kw.lower() in s_lower:
                    return std_val
            return v

        df_std["platform"] = df_std["platform"].apply(_norm_platform)

    months = [int(m) for m in df_std["month"].dropna().unique().tolist()]

    df_ext = df[ext_cols] if ext_cols else pd.DataFrame(index=df.index)
    std_columns = list(df_std.columns)
    std_rows = df_std.itertuples(index=False, name=None)
    ext_rows = df_ext.itertuples(index=False, name=None) if ext_cols else None
    records: list[dict] = []
    empty_ext = ()
    for values, ext_values in zip(
        std_rows,
        ext_rows if ext_rows is not None else (empty_ext for _ in range(len(df_std))),
    ):
        row = {k: _clean(v) for k, v in zip(std_columns, values)}
        if ext_cols:
            extra = {
                col: value
                for col, value in (
                    (col, _clean(value)) for col, value in zip(ext_cols, ext_values)
                )
                if value is not None
            }
            row["extra_data"] = extra or None
        else:
            row["extra_data"] = None
        records.append(row)

    return records, first_platform, months


def iter_mapped_chunks(
    file_path,
    mapping: dict,
    ignore_columns: list,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> Iterator[tuple[list[dict], str, list[int]]]:
    """流式解析 mapping 上传：逐块返回 (records, platform, months)。"""
    platform_label = "UNKNOWN"
    label_locked = False

    for df in _iter_dataframe_chunks(file_path, chunk_size):
        records, first_platform, months = _normalize_mapped_df(df, mapping, ignore_columns)
        if not label_locked and first_platform is not None:
            first_str = str(first_platform).lower()
            for kw, std in _PLATFORM_NORM.items():
                if kw.lower() in first_str:
                    platform_label = std.upper()
                    label_locked = True
                    break
        yield records, platform_label, months


def parse_with_mapping(
    file_path,
    mapping: dict,
    ignore_columns: list,
) -> tuple:
    """兼容旧接口：一次性返回全部 records。新代码建议用 iter_mapped_chunks。"""
    records: list[dict] = []
    platform = "UNKNOWN"
    months: set[int] = set()
    for chunk, label, chunk_months in iter_mapped_chunks(file_path, mapping, ignore_columns):
        records.extend(chunk)
        platform = label
        months.update(chunk_months)
    month_range = _month_range(months)
    return records, platform, month_range


def _month_range(months) -> str:
    months_sorted = sorted(int(m) for m in months)
    if len(months_sorted) > 1:
        return f"{months_sorted[0]}-{months_sorted[-1]}"
    if months_sorted:
        return str(months_sorted[0])
    return ""
