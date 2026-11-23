"""Read-only data quality warnings for the upload confirmation UI."""
from pathlib import Path

import pandas as pd

from app.services.excel_parser import iter_source_chunks, upload_numeric_values


FIELD_LABELS = {
    "item_id": "商品 ID", "item_name": "商品名称", "platform": "平台",
    "month": "月份", "sales_qty": "销量", "sales_amount": "销售额",
    "price": "价格", "ref_price": "参考价格",
}
REQUIRED_FIELDS = set(FIELD_LABELS) - {"ref_price"}
MAX_WARNING_SAMPLES = 50


def inspect_upload_values(
    file_path: str | Path,
    mapping: dict,
    ignore_columns: list,
    *,
    filename_month: int | None = None,
    filename_platform: str | None = None,
) -> dict:
    """Scan all rows in bounded chunks; return counts and at most 50 examples.

    Warnings are informational. This never creates jobs, changes source files,
    or rejects a record because of a data quality issue.
    """
    result = {
        "total_rows": 0, "affected_rows": 0, "issue_count": 0,
        "counts": {"missing_required": 0, "invalid_number": 0, "invalid_month": 0},
        "samples": [], "truncated": False,
    }
    ignored = set(ignore_columns)
    for frame in iter_source_chunks(file_path, preserve_values=True):
        result["total_rows"] += len(frame)
        affected = pd.Series(False, index=frame.index)
        candidates = []
        sources = {}
        for column in frame.columns:
            target = mapping.get(column)
            if column not in ignored and target in FIELD_LABELS:
                sources.setdefault(target, column)

        def add_warning(mask: pd.Series, code: str, field: str, column, values: pd.Series, message: str):
            nonlocal affected
            count = int(mask.sum())
            if not count:
                return
            affected |= mask
            result["issue_count"] += count
            result["counts"][code] += count
            if len(result["samples"]) >= MAX_WARNING_SAMPLES:
                return
            for row_number in frame.index[mask][:MAX_WARNING_SAMPLES]:
                value = values.loc[row_number]
                candidates.append({
                    "row": int(row_number), "field": field, "column": column,
                    "value": None if pd.isna(value) else str(value)[:200],
                    "message": message,
                })

        for field, label in FIELD_LABELS.items():
            # The importer fills these from the filename before inserting.
            if (field == "month" and filename_month is not None) or (field == "platform" and filename_platform):
                continue
            column = sources.get(field)
            values = frame[column] if column is not None else pd.Series(None, index=frame.index, dtype=object)
            missing = values.isna() | values.fillna("").astype(str).str.strip().eq("")
            if field in REQUIRED_FIELDS:
                add_warning(missing, "missing_required", field, column, values, f"{label}为空")
            if field in {"sales_qty", "sales_amount", "price", "ref_price", "month"}:
                numbers = upload_numeric_values(values, field)
                if field == "month":
                    valid = numbers.between(100001, 999912) & numbers.mod(100).between(1, 12)
                    add_warning(~missing & ~valid, "invalid_month", field, column, values, "月份无效，应为 YYYYMM，如 202610")
                else:
                    description = "销量应为整数，且不能超出可保存范围" if field == "sales_qty" else f"{label}格式无效或超出可保存范围"
                    add_warning(~missing & numbers.isna(), "invalid_number", field, column, values, description)
        result["affected_rows"] += int(affected.sum())
        candidates.sort(key=lambda sample: (sample["row"], sample["field"]))
        result["samples"].extend(candidates[:MAX_WARNING_SAMPLES - len(result["samples"])])
    result["truncated"] = result["issue_count"] > len(result["samples"])
    return result
