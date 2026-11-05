"""历史库管理 API
- POST   /api/historical/import           Excel 导入历史确认结果（同步，兼容旧调用）
- POST   /api/historical/jobs             创建后台导入任务（支持多文件合并）
- GET    /api/historical/jobs/{job_id}    查询后台导入任务进度
- POST   /api/historical/export/jobs      创建后台导出任务（大批次）
- GET    /api/historical/export/jobs/{id} 查询后台导出任务进度
- GET    /api/historical/export/download/{token}  下载后台导出的 Excel
- GET    /api/historical/batches          查询所有批次名称列表
- GET    /api/historical/mappings         分页查询映射（platform / import_batch 筛选）
- GET    /api/historical/export           按批次同步导出历史数据 Excel（兼容旧调用）
- POST   /api/historical/mappings/batch/merge  合并多个导入批次
- DELETE /api/historical/mappings/batch   按批次批量删除（静态路由，必须在 /{id} 之前）
- DELETE /api/historical/mappings/{id}    删除单条映射
"""
import io
import pickle
import re
import threading
import uuid
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Callable, Iterable, Optional
from urllib.parse import quote
from uuid import UUID

import pandas as pd
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse
from openpyxl import Workbook, load_workbook
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, tuple_
from sqlalchemy.orm import Session

from app.core.auth_deps import get_current_user
from app.core.config import settings
from app.core.permissions import visible_category_codes
from app.models.database import SessionLocal, get_db
from app.models.schemas import (
    Category,
    CategoryExtraField,
    HistoricalExportJob,
    HistoricalImportJob,
    HistoricalMapping,
    ModelRecord,
    User,
)
from app.services.export_guards import MAX_SYNC_EXPORT_ROWS, ensure_export_row_limit
from app.services.import_helper import save_tmp_file
from app.utils.time_utils import format_beijing_datetime
from app.utils.url_utils import extract_item_id

router = APIRouter(prefix="/api/historical", tags=["historical"])

PREVIEW_SAMPLE_ROWS = 5000


class BatchDeleteIn(BaseModel):
    import_batch: str


class BatchMergeIn(BaseModel):
    batches: list[str] = Field(min_length=1)
    target_batch: Optional[str] = None


class HistoricalImportJobFile(BaseModel):
    temp_file_id: str
    sheet_name: str
    mapping: dict[str, str]
    category_code: Optional[str] = None


class HistoricalImportJobIn(BaseModel):
    files: list[HistoricalImportJobFile] = Field(min_length=1)
    import_batch: Optional[str] = None


class HistoricalExportJobIn(BaseModel):
    import_batch: Optional[str] = None


class HistoricalConfirmIn(BaseModel):
    temp_file_id: str
    sheet_name: str
    mapping: dict[str, str]
    category_code: Optional[str] = None


class HistoricalPreviewIn(BaseModel):
    temp_file_id: str
    sheet_name: str
    mapping: dict[str, str]
    category_code: Optional[str] = None


def _visible_historical_category_codes(db: Session, current_user: User) -> set[str] | None:
    all_codes = [code for code, in db.query(Category.code).order_by(Category.sort_order, Category.name).all()]
    if not all_codes:
        return None
    return set(visible_category_codes(current_user, all_codes))


def _filter_historical_visible_categories(query, db: Session, current_user: User):
    visible_codes = _visible_historical_category_codes(db, current_user)
    if visible_codes is None:
        return query
    return query.filter(HistoricalMapping.category_code.in_(visible_codes))


def _ensure_historical_category_visible(db: Session, current_user: User, category_code: Optional[str]) -> None:
    if not category_code:
        return
    visible_codes = _visible_historical_category_codes(db, current_user)
    if visible_codes is not None and category_code not in visible_codes:
        raise HTTPException(status_code=403, detail="无权限访问该品类")


HISTORICAL_STANDARD_FIELDS = {
    "year": "年",
    "month_num": "月",
    "week": "周",
    "report_type": "报告类型",
    "channel": "渠道",
    "platform": "商场",
    "category_name_raw": "品类",
    "brand_raw": "品牌",
    "model_text": "型号",
    "model_type": "机型/系列",
    "category_code_raw": "品类码",
    "brand_code_raw": "品牌码",
    "model_code_raw": "型号码",
    "item_name": "标题",
    "sales_amount": "销额",
    "sales_qty": "销量",
    "price": "单价",
    "item_url": "网址",
}

HISTORICAL_REQUIRED_FIELDS = {"platform", "item_name", "year", "month_num"}

HISTORICAL_FIELD_ALIASES = {
    "year": {"年", "年度"},
    "month_num": {"月", "月度", "时间维度"},
    "week": {"周", "周度"},
    "report_type": {"报告类型"},
    "channel": {"渠道", "渠道类型"},
    "platform": {"商场", "平台", "五大电商"},
    "category_name_raw": {"品类", "类目", "产品品类"},
    "brand_raw": {"品牌"},
    "model_text": {"型号", "品牌+系列", "品牌产品系列", "机型"},
    "model_type": {"系列/机型", "产品系列", "系列"},
    "category_code_raw": {"品类码"},
    "brand_code_raw": {"品牌码"},
    "model_code_raw": {"型号码"},
    "item_name": {"标题", "商品名称", "宝贝名称"},
    "sales_amount": {"销额", "销售额", "原始额"},
    "sales_qty": {"销量", "原始量"},
    "price": {"单价", "成交价"},
    "item_url": {"网址", "商品网址", "宝贝链接", "URL"},
}

HISTORICAL_ALIAS_TO_FIELD = {
    alias: field
    for field, aliases in HISTORICAL_FIELD_ALIASES.items()
    for alias in aliases
}


def _clean_value(value) -> Optional[str]:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.lower() == "nan":
        return None
    if text.endswith(".0"):
        try:
            return str(int(float(text)))
        except ValueError:
            return text
    return text


def _is_unusable_identity_value(value: Optional[str]) -> bool:
    text = _clean_value(value)
    if text is None:
        return True
    return text.strip().upper() in {"-", "—", "–", "UNKNOWN", "UNKNOWN BRAND", "未知"}


def _usable_identity_value(value: Optional[str]) -> Optional[str]:
    text = _clean_value(value)
    return None if _is_unusable_identity_value(text) else text


def _is_unknown_brand(value: Optional[str]) -> bool:
    return _is_unusable_identity_value(value)


def _clean_int(value) -> Optional[int]:
    text = _clean_value(value)
    if text is None:
        return None
    try:
        number = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    if number != number.to_integral_value():
        return None
    return int(number)


def _parse_year(value) -> Optional[int]:
    year = _clean_int(value)
    if year is None:
        return None
    if 0 <= year < 100:
        return 2000 + year
    return year


def _parse_month(value) -> Optional[int]:
    text = _clean_value(value)
    if text is None:
        return None
    month = _clean_int(text)
    if month is not None:
        if 1 <= month <= 12:
            return month
        if text.isdigit() and len(text) == 6:
            month_part = month % 100
            return month_part if 1 <= month_part <= 12 else month
        return month

    normalized = text.replace("年", ".").replace("月", "").replace("-", ".").replace("/", ".")
    if "." not in normalized:
        return None
    year_text, month_text = normalized.split(".", 1)
    if len(year_text.strip()) != 4:
        return None
    return _clean_int(month_text)


def _parse_time_dimension(value) -> tuple[Optional[int], Optional[int]]:
    text = _clean_value(value)
    if text is None:
        return None, None
    normalized = text.replace("年", ".").replace("月", "").replace("-", ".").replace("/", ".")
    if "." not in normalized:
        return None, None
    year_text, month_text = normalized.split(".", 1)
    year = _parse_year(year_text)
    month = _clean_int(month_text)
    return year, month


def _clean_decimal(value) -> Optional[Decimal]:
    text = _clean_value(value)
    if text is None:
        return None
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


def _normalize_platform(value: Optional[str]) -> Optional[str]:
    text = _clean_value(value)
    if not text:
        return None
    mapping = {
        "亚马逊": "amazon", "amazon": "amazon",
        "西皮": "shopee", "虾皮": "shopee", "shopee": "shopee",
    }
    return mapping.get(text.lower(), text.lower())


def _normalize_item_name(value: Optional[str]) -> Optional[str]:
    text = _clean_value(value)
    return " ".join(text.upper().split()) if text else None


def _get(row: dict, key: str):
    return row.get(key)


def _row_value(row: dict, mapping: dict[str, str], field: str):
    source = mapping.get(field)
    if source is None:
        return None
    return row.get(source)


def _build_mapping(columns: list[str]) -> dict[str, str]:
    mapping = {}
    used = set()
    for col in columns:
        field = HISTORICAL_ALIAS_TO_FIELD.get(col)
        if field and field not in used:
            mapping[field] = col
            used.add(field)
        elif field == "item_url" and col == "网址":
            mapping[field] = col
    return mapping


def _read_sheet_preview(
    xls: pd.ExcelFile,
    sheet_name: str,
    nrows: Optional[int] = None,
    usecols: Optional[list[str]] = None,
) -> pd.DataFrame:
    df = pd.read_excel(xls, sheet_name=sheet_name, nrows=nrows, usecols=usecols)
    df.columns = [str(col).strip() for col in df.columns]
    return df


def _iter_sheet_rows_streaming(
    path: Path,
    sheet_name: str,
    *,
    columns: list[str],
    usecols: Optional[list[str]] = None,
):
    selected = set(usecols or columns)
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        if sheet_name not in workbook.sheetnames:
            raise HTTPException(400, "选择的 sheet 不存在")
        sheet = workbook[sheet_name]
        rows_iter = sheet.iter_rows(values_only=True)
        header = next(rows_iter, None)
        if header is None:
            return
        header_values = [str(col).strip() if col is not None else "" for col in header]
        selected_indexes = [(index, col) for index, col in enumerate(header_values) if col in selected]
        for row in rows_iter:
            yield {col: row[index] if index < len(row) else None for index, col in selected_indexes}
    finally:
        workbook.close()


def _read_sheet_streaming(
    path: Path,
    sheet_name: str,
    *,
    columns: list[str],
    nrows: Optional[int] = None,
    usecols: Optional[list[str]] = None,
) -> pd.DataFrame:
    rows = []
    for row in _iter_sheet_rows_streaming(path, sheet_name, columns=columns, usecols=usecols):
        rows.append(row)
        if nrows is not None and len(rows) >= nrows:
            break
    return pd.DataFrame(rows, columns=usecols or columns)


def _sheet_total_rows_streaming(path: Path, sheet_name: str) -> int:
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        if sheet_name not in workbook.sheetnames:
            raise HTTPException(400, "选择的 sheet 不存在")
        sheet = workbook[sheet_name]
        return max((sheet.max_row or 1) - 1, 0)
    finally:
        workbook.close()


def _mapped_columns(mapping: dict[str, str], columns: list[str]) -> list[str]:
    column_set = set(columns)
    return list(dict.fromkeys(source for source in mapping.values() if source in column_set))


def _score_sheet(columns: list[str]) -> int:
    mapping = _build_mapping(columns)
    score = len(mapping)
    score += sum(5 for field in HISTORICAL_REQUIRED_FIELDS if field in mapping)
    if "item_url" in mapping:
        score += 3
    if "sales_qty" in mapping or "sales_amount" in mapping:
        score += 2
    return score


def _detect_sheet_and_mapping(xls: pd.ExcelFile) -> tuple[str, list[str], dict[str, str]]:
    candidates = []
    for sheet_name in xls.sheet_names:
        try:
            df = _read_sheet_preview(xls, sheet_name, nrows=0)
        except Exception:
            continue
        columns = [str(col).strip() for col in df.columns]
        candidates.append((_score_sheet(columns), sheet_name, columns, _build_mapping(columns)))
    if not candidates:
        raise HTTPException(400, "Excel 文件没有可读取的工作表")
    rawdata = [item for item in candidates if item[1] == "rawdata"]
    if rawdata:
        _, sheet_name, columns, mapping = rawdata[0]
        return sheet_name, columns, mapping
    candidates.sort(key=lambda item: item[0], reverse=True)
    _, sheet_name, columns, mapping = candidates[0]
    return sheet_name, columns, mapping


LEGACY_FILENAME_CATEGORY_ALIASES = {
    "door_lock": ("门锁",),
    "smart_lock": ("门锁",),
}


def _infer_category_code(filename: str, db: Session) -> Optional[str]:
    categories = db.query(Category).all()
    for category in categories:
        aliases = LEGACY_FILENAME_CATEGORY_ALIASES.get(category.code, ())
        if any(alias in filename for alias in aliases):
            return category.code
        if category.name and category.name in filename:
            return category.code
        if category.code and category.code in filename:
            return category.code
    return None


def _standardize_historical_row(row: dict, mapping: dict[str, str], category_code: Optional[str]) -> dict:
    year_value = _row_value(row, mapping, "year")
    month_value = _row_value(row, mapping, "month_num")
    year = _parse_year(year_value)
    month_num = _parse_month(month_value)
    if (year is None or month_num is None) and mapping.get("month_num") in {"时间维度", "月度"}:
        dimension_year, dimension_month = _parse_time_dimension(month_value)
        year = year if year is not None else dimension_year
        month_num = month_num if month_num is not None else dimension_month
    return {
        "年": year,
        "月": month_num,
        "周": _clean_value(_row_value(row, mapping, "week")),
        "报告类型": _clean_value(_row_value(row, mapping, "report_type")),
        "渠道": _clean_value(_row_value(row, mapping, "channel")),
        "商场": _clean_value(_row_value(row, mapping, "platform")),
        "品类": _clean_value(_row_value(row, mapping, "category_name_raw")),
        "品牌": _clean_value(_row_value(row, mapping, "brand_raw")),
        "型号": _clean_value(_row_value(row, mapping, "model_text")),
        "机型": _clean_value(_row_value(row, mapping, "model_type")),
        "品类码": _clean_value(_row_value(row, mapping, "category_code_raw")) or category_code,
        "品牌码": _clean_value(_row_value(row, mapping, "brand_code_raw")),
        "型号码": _clean_value(_row_value(row, mapping, "model_code_raw")),
        "标题": _clean_value(_row_value(row, mapping, "item_name")),
        "销额": _clean_value(_row_value(row, mapping, "sales_amount")),
        "销量": _clean_value(_row_value(row, mapping, "sales_qty")),
        "单价": _clean_value(_row_value(row, mapping, "price")),
        "网址": _clean_value(_row_value(row, mapping, "item_url")),
    }


def _standardize_historical_df(df: pd.DataFrame, mapping: dict[str, str], category_code: Optional[str]) -> pd.DataFrame:
    rows = []
    for _, raw_row in df.iterrows():
        rows.append(_standardize_historical_row(raw_row.to_dict(), mapping, category_code))
    return pd.DataFrame(rows)


def _preview_rows(df: pd.DataFrame, limit: int = 20) -> list[dict]:
    rows = []
    for _, row in df.head(limit).iterrows():
        rows.append(_json_safe_row(row.to_dict()))
    return rows


def _normalize_mapping_for_columns(mapping: dict[str, str], columns: list[str]) -> dict[str, str]:
    column_set = set(columns)
    normalized = {field: source for field, source in mapping.items() if source in column_set}
    defaults = _build_mapping(columns)
    for field, source in defaults.items():
        normalized.setdefault(field, source)
    return normalized


def _mapping_issues(mapping: dict[str, str], category_code: Optional[str], columns: Optional[list[str]] = None) -> list[str]:
    issues = []
    column_set = set(columns) if columns is not None else None
    for field, source in mapping.items():
        if column_set is not None and source not in column_set:
            label = HISTORICAL_STANDARD_FIELDS.get(field, field)
            issues.append(f"字段映射不存在：{label} -> {source}")
    for field in sorted(HISTORICAL_REQUIRED_FIELDS):
        if field == "year" and mapping.get("month_num") == "时间维度":
            continue
        if field not in mapping:
            issues.append(f"缺少必填字段映射：{HISTORICAL_STANDARD_FIELDS[field]}")
    if not category_code and "category_code_raw" not in mapping and "category_name_raw" not in mapping:
        issues.append("未识别品类，确认导入前需要选择品类")
    return issues


def _row_required_errors(row: dict) -> list[str]:
    errors = []
    platform = _normalize_platform(_get(row, "商场")) or _normalize_platform(_get(row, "渠道"))
    item_name = _clean_value(_get(row, "标题"))
    year = _parse_year(_get(row, "年"))
    month_num = _parse_month(_get(row, "月"))
    if month_num is None:
        _dimension_year, dimension_month = _parse_time_dimension(_get(row, "月"))
        month_num = dimension_month
    if not platform:
        errors.append("商场/渠道不能为空")
    if not item_name:
        errors.append("标题不能为空")
    if year is None:
        errors.append("年不能为空")
    if month_num is None:
        errors.append("月不能为空")
    elif month_num < 1 or month_num > 12:
        errors.append("月必须为 1-12")
    return errors


def _effective_brand_code(brand_code_raw: Optional[str], brand_raw: Optional[str]) -> Optional[str]:
    if not _is_unknown_brand(brand_code_raw):
        return brand_code_raw
    if not _is_unknown_brand(brand_raw):
        return brand_raw
    return None


def _preview_stats(db: Session, standardized_df: pd.DataFrame) -> dict:
    return _preview_stats_for_rows(db, (raw_row.to_dict() for _, raw_row in standardized_df.iterrows()))


def _preview_stats_for_rows(db: Session, rows: Iterable[dict]) -> dict:
    materialized_rows = list(rows)
    model_code_values = {_clean_value(_get(row, "型号码")) for row in materialized_rows}
    model_text_values = {_clean_value(_get(row, "型号")) for row in materialized_rows}
    models_by_code, models_by_code_unbranded, models_by_name = _load_preview_models(db, model_code_values, model_text_values)
    ambiguous_model_codes = _ambiguous_model_codes_from_rows(materialized_rows, models_by_code_unbranded)
    series_codes = _series_category_codes(db)
    models_by_series = _load_series_models(db, series_codes)
    return _calculate_preview_stats_for_rows(
        materialized_rows,
        models_by_code=models_by_code,
        models_by_code_unbranded=models_by_code_unbranded,
        models_by_name=models_by_name,
        ambiguous_model_codes=ambiguous_model_codes,
        series_codes=series_codes,
        models_by_series=models_by_series,
    )


def _load_preview_models(db: Session, model_code_values: set[str | None], model_text_values: set[str | None]):
    model_code_values.discard(None)
    model_text_values.discard(None)
    all_codes = model_code_values | model_text_values

    models_by_code = {}
    models_by_code_unbranded = {}
    if all_codes:
        for model in db.query(ModelRecord).filter(ModelRecord.model_code.in_(all_codes)).all():
            models_by_code[(model.brand_code, model.model_code)] = model
            models_by_code_unbranded.setdefault(model.model_code, []).append(model)

    models_by_name = {}
    if model_text_values:
        for model in db.query(ModelRecord).filter(ModelRecord.model_name.in_(model_text_values)).all():
            models_by_name.setdefault(model.model_name, []).append(model)

    return models_by_code, models_by_code_unbranded, models_by_name


def _series_category_codes(db: Session) -> set[str]:
    """配置了「产品系列」扩展字段的品类码（如智能平板/学习平板）。"""
    rows = (
        db.query(CategoryExtraField.category_code)
        .filter(CategoryExtraField.field_key == "series")
        .all()
    )
    return {code for (code,) in rows if code}


def _series_model_key(
    brand_code: Optional[str],
    category_code: Optional[str],
    series: Optional[str],
    model_code: Optional[str],
) -> tuple[str, str, str, str]:
    return (
        (brand_code or "").strip(),
        (category_code or "").strip(),
        (series or "").strip(),
        (model_code or "").strip(),
    )


def _load_series_models(
    db: Session, series_codes: set[str]
) -> dict[tuple[str, str, str, str], ModelRecord]:
    """预加载系列品类型号，键为 (品牌码, 品类码, 产品系列, 型号码)。"""
    if not series_codes:
        return {}
    result: dict[tuple[str, str, str, str], ModelRecord] = {}
    for model in db.query(ModelRecord).filter(ModelRecord.category_code.in_(series_codes)).all():
        result[_series_model_key(model.brand_code, model.category_code, model.series, model.model_code)] = model
    return result


def _calculate_preview_stats_for_rows(
    rows: Iterable[dict],
    *,
    models_by_code: dict[tuple[str, str], ModelRecord],
    models_by_code_unbranded: dict[str, list[ModelRecord]],
    models_by_name: dict[str, list[ModelRecord]],
    ambiguous_model_codes: set[str],
    series_codes: Optional[set[str]] = None,
    models_by_series: Optional[dict[tuple[str, str, str, str], ModelRecord]] = None,
) -> dict:
    series_codes = series_codes or set()
    models_by_series = models_by_series or {}
    total_rows = 0
    missing_required_rows = 0
    missing_model_rows = 0
    auto_create_keys: set[tuple] = set()

    for row in rows:
        total_rows += 1
        if _row_required_errors(row):
            missing_required_rows += 1
            continue
        model_code_raw = _clean_value(_get(row, "型号码"))
        model_text = _clean_value(_get(row, "型号"))
        model_type_raw = _clean_value(_get(row, "机型"))
        category_code = _clean_value(_get(row, "品类码"))
        brand_raw = _clean_value(_get(row, "品牌"))
        brand_code_raw = _clean_value(_get(row, "品牌码"))
        effective_brand_code = _effective_brand_code(brand_code_raw, brand_raw)
        if not (model_code_raw or model_text):
            if model_type_raw:
                missing_model_rows += 1
            continue
        model, reason = _resolve_model(
            model_code_raw=model_code_raw,
            model_text=model_text,
            brand_code_raw=effective_brand_code,
            models_by_code=models_by_code,
            models_by_code_unbranded=models_by_code_unbranded,
            models_by_name=models_by_name,
            ambiguous_model_codes=ambiguous_model_codes,
            model_type_raw=model_type_raw,
            category_code=category_code,
            series_codes=series_codes,
            models_by_series=models_by_series,
        )
        if model is None:
            missing_model_rows += 1
            if reason and ("匹配到多个型号" in reason or "匹配到多个品牌" in reason):
                continue
            values = _model_identity_values(
                brand_code_raw=effective_brand_code,
                brand_raw=brand_raw,
                model_code_raw=model_code_raw,
                model_text=model_text,
                category_code=category_code,
            )
            if values is not None:
                auto_create_keys.add(
                    (
                        values["brand_code"],
                        category_code,
                        _usable_identity_value(model_type_raw) if category_code in series_codes else None,
                        values["model_code"],
                    )
                )

    return {
        "total_rows": total_rows,
        "importable_rows": total_rows - missing_required_rows,
        "missing_required_rows": missing_required_rows,
        "missing_model_rows": missing_model_rows,
        "auto_create_model_count": len(auto_create_keys),
    }


def _resolve_model(
    *,
    model_code_raw: Optional[str],
    model_text: Optional[str],
    brand_code_raw: Optional[str],
    models_by_code: dict[tuple[str, str], ModelRecord],
    models_by_code_unbranded: dict[str, list[ModelRecord]],
    models_by_name: dict[str, list[ModelRecord]],
    ambiguous_model_codes: Optional[set[str]] = None,
    model_type_raw: Optional[str] = None,
    category_code: Optional[str] = None,
    series_codes: Optional[set[str]] = None,
    models_by_series: Optional[dict[tuple[str, str, str, str], ModelRecord]] = None,
):
    ambiguous_model_codes = ambiguous_model_codes or set()
    series_codes = series_codes or set()
    models_by_series = models_by_series or {}

    model_code_raw = _usable_identity_value(model_code_raw)
    model_text = _usable_identity_value(model_text)

    # 系列品类（智能平板/学习平板）：只按「品牌 + 产品系列 + 型号码(存储)」定位；
    # 系列或存储缺失（如「-」/空）时按待补导入，不再回退名称匹配。
    if category_code and category_code in series_codes:
        if not (brand_code_raw and not _is_unknown_brand(brand_code_raw)):
            return None, None
        series = _usable_identity_value(model_type_raw)
        series_code = model_code_raw or model_text
        if series and series_code:
            key = _series_model_key(brand_code_raw, category_code, series, series_code)
            model = models_by_series.get(key)
            if model:
                return model, None
            return None, f"型号码「{series_code}」在型号库中不存在"
        return None, None

    if not model_code_raw and not model_text:
        return None, None

    if model_code_raw:
        if not brand_code_raw and model_code_raw in ambiguous_model_codes:
            return None, f"型号码「{model_code_raw}」匹配到多个品牌，请填写品牌码"
        if brand_code_raw:
            model = models_by_code.get((brand_code_raw, model_code_raw))
            if model:
                return model, None
        else:
            models_by_code_list = models_by_code_unbranded.get(model_code_raw, [])
            if len(models_by_code_list) == 1:
                return models_by_code_list[0], None
            if len(models_by_code_list) > 1:
                return None, f"型号码「{model_code_raw}」匹配到多个品牌，请填写品牌码"
        return None, f"型号码「{model_code_raw}」在型号库中不存在"

    if not model_text:
        return None, None

    if not brand_code_raw and model_text in ambiguous_model_codes:
        return None, f"型号码「{model_text}」匹配到多个品牌，请填写品牌码"

    if brand_code_raw:
        model_by_code = models_by_code.get((brand_code_raw, model_text))
        if model_by_code:
            return model_by_code, None
    else:
        models_by_code_list = models_by_code_unbranded.get(model_text, [])
        if len(models_by_code_list) == 1:
            return models_by_code_list[0], None
        if len(models_by_code_list) > 1:
            return None, f"型号码「{model_text}」匹配到多个品牌，请填写品牌码"

    models_by_name_list = models_by_name.get(model_text, [])
    if len(models_by_name_list) == 1:
        if not brand_code_raw or models_by_name_list[0].brand_code == brand_code_raw:
            return models_by_name_list[0], None
    if len(models_by_name_list) > 1:
        if brand_code_raw:
            matched = [m for m in models_by_name_list if m.brand_code == brand_code_raw]
            if len(matched) == 1:
                return matched[0], None
        return None, f"型号名称「{model_text}」匹配到多个型号，请填写型号码"

    return None, f"型号「{model_text}」在型号库中不存在"


def _match_key_type(item_id: Optional[str], item_url: Optional[str], item_name_norm: str) -> str:
    if item_id:
        return "item_id"
    if item_url:
        return "item_url"
    return "item_name"


def _period_filter(query, *, year: int, month_num: int, week: Optional[str]):
    query = query.filter(
        HistoricalMapping.year == year,
        HistoricalMapping.month_num == month_num,
    )
    if week:
        query = query.filter(HistoricalMapping.week == week)
    else:
        query = query.filter(HistoricalMapping.week.is_(None))
    return query


def _history_identity_key(
    *,
    platform: str,
    item_id: Optional[str],
    item_url: Optional[str],
    item_name_norm: str,
    year: int,
    month_num: int,
    week: Optional[str],
) -> tuple[str, str, int, int, Optional[str], str]:
    if item_id:
        return platform, "item_id", year, month_num, week, item_id
    if item_url:
        return platform, "item_url", year, month_num, week, item_url
    return platform, "item_name", year, month_num, week, item_name_norm


def _chunks(values: set[tuple], size: int = 1000):
    batch = []
    for value in values:
        batch.append(value)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def _preload_existing_history(db: Session, keys: set[tuple[str, str, int, int, Optional[str], str]]) -> dict[tuple[str, str, int, int, Optional[str], str], HistoricalMapping]:
    if not keys:
        return {}

    item_keys = {(platform, year, month_num, value) for platform, key_type, year, month_num, week, value in keys if key_type == "item_id"}
    url_keys = {(platform, year, month_num, value) for platform, key_type, year, month_num, week, value in keys if key_type == "item_url"}
    name_keys = {(platform, year, month_num, value) for platform, key_type, year, month_num, week, value in keys if key_type == "item_name"}

    existing = {}

    def add_rows(rows, key_type: str, value_attr: str):
        for row in rows:
            value = getattr(row, value_attr)
            key = (row.platform, key_type, row.year, row.month_num, row.week, value)
            existing[key] = row

    for batch in _chunks(item_keys):
        rows = db.query(HistoricalMapping).filter(
            tuple_(HistoricalMapping.platform, HistoricalMapping.year, HistoricalMapping.month_num, HistoricalMapping.item_id).in_(batch)
        ).all()
        add_rows(rows, "item_id", "item_id")
    for batch in _chunks(url_keys):
        rows = db.query(HistoricalMapping).filter(
            tuple_(HistoricalMapping.platform, HistoricalMapping.year, HistoricalMapping.month_num, HistoricalMapping.item_url).in_(batch)
        ).all()
        add_rows(rows, "item_url", "item_url")
    for batch in _chunks(name_keys):
        rows = db.query(HistoricalMapping).filter(
            tuple_(HistoricalMapping.platform, HistoricalMapping.year, HistoricalMapping.month_num, HistoricalMapping.item_name_norm).in_(batch)
        ).all()
        add_rows(rows, "item_name", "item_name_norm")
    return existing


def _json_safe_row(row: dict) -> dict:
    result = {}
    for key, value in row.items():
        cleaned = _clean_value(value)
        result[key] = cleaned
    return result


def _sum_optional_int(left: Optional[int], right: Optional[int]) -> Optional[int]:
    if left is None:
        return right
    if right is None:
        return left
    return left + right


def _sum_optional_decimal(left: Optional[Decimal], right: Optional[Decimal]) -> Optional[Decimal]:
    if left is None:
        return right
    if right is None:
        return left
    return left + right


def _merge_duplicate_history_values(current: dict, incoming: dict, row_nums: list[int]) -> None:
    sales_qty = _sum_optional_int(current.get("sales_qty"), incoming.get("sales_qty"))
    sales_amount = _sum_optional_decimal(current.get("sales_amount"), incoming.get("sales_amount"))
    current.update(incoming)
    current["sales_qty"] = sales_qty
    current["sales_amount"] = sales_amount
    raw_payload = dict(current.get("raw_payload") or {})
    raw_payload["_merge_note"] = f"同一导入批次内发现 {len(row_nums)} 条相同历史键记录，销量和销额已累加"
    raw_payload["_merged_rows"] = row_nums
    current["raw_payload"] = raw_payload


def _preload_categories(db: Session) -> tuple[dict[str, str], dict[str, str]]:
    by_code = {}
    by_name = {}
    for category in db.query(Category).all():
        by_code[category.code] = category.code
        by_name[category.name] = category.code
    return by_code, by_name


def _resolve_category_code(
    *,
    category_code_raw: Optional[str],
    category_name_raw: Optional[str],
    categories_by_code: dict[str, str],
    categories_by_name: dict[str, str],
) -> Optional[str]:
    if category_code_raw and category_code_raw in categories_by_code:
        return categories_by_code[category_code_raw]
    if category_name_raw and category_name_raw in categories_by_name:
        return categories_by_name[category_name_raw]
    return None


def _pending_model_identity(category_code: Optional[str]) -> tuple[str, str]:
    suffix = category_code or "unknown"
    return f"待补型号-{suffix}", "待补型号"


def _model_identity_values(
    *,
    brand_code_raw: Optional[str],
    brand_raw: Optional[str],
    model_code_raw: Optional[str],
    model_text: Optional[str],
    category_code: Optional[str],
    allow_pending_model: bool = False,
) -> Optional[dict]:
    brand_code = _effective_brand_code(brand_code_raw, brand_raw)
    if _is_unknown_brand(brand_code):
        return None
    model_code = _usable_identity_value(model_code_raw)
    model_name = _usable_identity_value(model_text)
    if not model_code and not model_name:
        if not allow_pending_model:
            return None
        model_code, model_name = _pending_model_identity(category_code)
    else:
        model_code = model_code or model_name
        model_name = model_name or model_code
    return {
        "brand_code": brand_code,
        "model_code": model_code,
        "model_name": model_name,
        "brand_name": _usable_identity_value(brand_raw) or brand_code,
        "category_code": category_code,
    }


def _get_or_create_model(
    db: Session,
    *,
    model_code_raw: Optional[str],
    model_text: Optional[str],
    brand_code_raw: Optional[str],
    brand_raw: Optional[str],
    category_code: Optional[str],
    models_by_code: dict[tuple[str, str], ModelRecord],
    models_by_code_unbranded: dict[str, list[ModelRecord]],
    models_by_name: dict[str, list[ModelRecord]],
    ambiguous_model_codes: Optional[set[str]] = None,
    model_type_raw: Optional[str] = None,
    series_codes: Optional[set[str]] = None,
    models_by_series: Optional[dict[tuple[str, str, str, str], ModelRecord]] = None,
) -> tuple[Optional[ModelRecord], Optional[str]]:
    series_codes = series_codes or set()
    models_by_series = models_by_series or {}
    model, reason = _resolve_model(
        model_code_raw=model_code_raw,
        model_text=model_text,
        brand_code_raw=brand_code_raw,
        models_by_code=models_by_code,
        models_by_code_unbranded=models_by_code_unbranded,
        models_by_name=models_by_name,
        ambiguous_model_codes=ambiguous_model_codes,
        model_type_raw=model_type_raw,
        category_code=category_code,
        series_codes=series_codes,
        models_by_series=models_by_series,
    )
    if model:
        return model, None
    if not reason:
        return None, None
    if "匹配到多个型号" in reason or "匹配到多个品牌" in reason:
        return None, reason

    values = _model_identity_values(
        brand_code_raw=brand_code_raw,
        brand_raw=brand_raw,
        model_code_raw=model_code_raw,
        model_text=model_text,
        category_code=category_code,
    )
    if values is None:
        return None, None

    is_series_category = bool(category_code and category_code in series_codes)
    series_value = _usable_identity_value(model_type_raw) if is_series_category else None
    if is_series_category:
        values["series"] = series_value

    existing_query = db.query(ModelRecord).filter(
        ModelRecord.brand_code == values["brand_code"],
        ModelRecord.model_code == values["model_code"],
    )
    if is_series_category:
        existing_query = existing_query.filter(ModelRecord.series == series_value)
    existing = existing_query.first()
    if existing:
        models_by_code[(existing.brand_code, existing.model_code)] = existing
        if existing not in models_by_code_unbranded.setdefault(existing.model_code, []):
            models_by_code_unbranded[existing.model_code].append(existing)
        if existing.model_name and existing not in models_by_name.setdefault(existing.model_name, []):
            models_by_name[existing.model_name].append(existing)
        if is_series_category:
            models_by_series[_series_model_key(existing.brand_code, existing.category_code, existing.series, existing.model_code)] = existing
        return existing, None

    new_model = ModelRecord(**values)
    db.add(new_model)
    db.flush()
    models_by_code[(new_model.brand_code, new_model.model_code)] = new_model
    models_by_code_unbranded.setdefault(new_model.model_code, []).append(new_model)
    models_by_name.setdefault(new_model.model_name, []).append(new_model)
    if is_series_category:
        models_by_series[_series_model_key(new_model.brand_code, new_model.category_code, new_model.series, new_model.model_code)] = new_model
    return new_model, None


def _find_tmp_file(temp_file_id: str) -> Path:
    try:
        safe_id = str(UUID(temp_file_id))
    except ValueError:
        raise HTTPException(400, "无效的临时文件 ID")
    tmp_dir = Path(settings.UPLOAD_DIR) / "tmp"
    matches = list(tmp_dir.glob(f"{safe_id}_*"))
    if not matches:
        raise HTTPException(404, "临时文件不存在或已过期，请重新上传")
    return matches[0]


def _original_filename_from_tmp(path: Path, temp_file_id: str) -> str:
    prefix = f"{temp_file_id}_"
    if path.name.startswith(prefix):
        return path.name[len(prefix):]
    return path.name


def _validate_excel_file(file: UploadFile):
    filename = file.filename or ""
    if not filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(400, "仅支持 Excel 文件（.xlsx/.xls）")


def _historical_preview_response(
    *,
    temp_file_id: str,
    filename: str,
    xls: pd.ExcelFile,
    path: Path,
    sheet_name: str,
    columns: list[str],
    mapping: dict[str, str],
    category_code: Optional[str],
    db: Session,
) -> dict:
    raw_issues = _mapping_issues(mapping, category_code, columns)
    normalized_mapping = _normalize_mapping_for_columns(mapping, columns)
    normalized_issues = _mapping_issues(normalized_mapping, category_code, columns)
    issues = list(dict.fromkeys(raw_issues + normalized_issues))
    usecols = _mapped_columns(normalized_mapping, columns)
    if path.suffix.lower() == ".xls":
        df_preview = _read_sheet_preview(xls, sheet_name, nrows=20, usecols=usecols)
        standardized_preview = _standardize_historical_df(df_preview, normalized_mapping, category_code)
        full_df = _standardize_historical_df(_read_sheet_preview(xls, sheet_name, usecols=usecols), normalized_mapping, category_code)
        stats = _preview_stats(db, full_df)
        total_rows = stats["total_rows"]
        stats["sample_rows"] = total_rows
        stats["sampled"] = False
        preview_rows = _preview_rows(standardized_preview)
    else:
        preview_rows = []
        sampled_rows: list[dict] = []
        for raw_row in _iter_sheet_rows_streaming(path, sheet_name, columns=columns, usecols=usecols):
            standardized = _standardize_historical_row(raw_row, normalized_mapping, category_code)
            if len(sampled_rows) < PREVIEW_SAMPLE_ROWS:
                sampled_rows.append(standardized)
            if len(preview_rows) < 20:
                preview_rows.append(_json_safe_row(standardized))
            if len(sampled_rows) >= PREVIEW_SAMPLE_ROWS:
                break
        model_code_values = {_clean_value(_get(row, "型号码")) for row in sampled_rows}
        model_text_values = {_clean_value(_get(row, "型号")) for row in sampled_rows}
        models_by_code, models_by_code_unbranded, models_by_name = _load_preview_models(db, model_code_values, model_text_values)
        ambiguous_model_codes = _ambiguous_model_codes_from_rows(sampled_rows, models_by_code_unbranded)
        series_codes = _series_category_codes(db)
        models_by_series = _load_series_models(db, series_codes)
        stats = _calculate_preview_stats_for_rows(
            sampled_rows,
            models_by_code=models_by_code,
            models_by_code_unbranded=models_by_code_unbranded,
            models_by_name=models_by_name,
            ambiguous_model_codes=ambiguous_model_codes,
            series_codes=series_codes,
            models_by_series=models_by_series,
        )
        total_rows = _sheet_total_rows_streaming(path, sheet_name)
        stats["sample_rows"] = len(sampled_rows)
        stats["sampled"] = total_rows > len(sampled_rows)
        stats["total_rows"] = total_rows
    return {
        "temp_file_id": temp_file_id,
        "filename": filename,
        "sheets": xls.sheet_names,
        "sheet_name": sheet_name,
        "columns": columns,
        "standard_fields": HISTORICAL_STANDARD_FIELDS,
        "mapping": normalized_mapping,
        "category_code": category_code,
        "issues": issues,
        "total_rows": total_rows,
        "stats": stats,
        "preview": preview_rows,
    }


def _preload_models(db: Session, df: pd.DataFrame):
    model_code_values = {_clean_value(value) for value in df.get("型号码", [])}
    model_text_values = {_clean_value(value) for value in df.get("型号", [])}
    model_code_values.discard(None)
    model_text_values.discard(None)
    all_codes = model_code_values | model_text_values

    models_by_code = {}
    models_by_code_unbranded = {}
    if all_codes:
        for model in db.query(ModelRecord).filter(ModelRecord.model_code.in_(all_codes)).all():
            models_by_code[(model.brand_code, model.model_code)] = model
            models_by_code_unbranded.setdefault(model.model_code, []).append(model)

    models_by_name = {}
    if model_text_values:
        for model in db.query(ModelRecord).filter(ModelRecord.model_name.in_(model_text_values)).all():
            models_by_name.setdefault(model.model_name, []).append(model)

    return models_by_code, models_by_code_unbranded, models_by_name


def _ambiguous_model_codes_from_rows(rows: Iterable[dict], models_by_code_unbranded: dict[str, list[ModelRecord]]) -> set[str]:
    brands_by_code = {
        model_code: {model.brand_code for model in models}
        for model_code, models in models_by_code_unbranded.items()
    }
    for row in rows:
        brand_code_raw = _clean_value(_get(row, "品牌码"))
        brand_raw = _clean_value(_get(row, "品牌"))
        brand_code = _effective_brand_code(brand_code_raw, brand_raw)
        if _is_unknown_brand(brand_code):
            continue
        for model_code in {_clean_value(_get(row, "型号码")), _clean_value(_get(row, "型号"))}:
            if model_code:
                brands_by_code.setdefault(model_code, set()).add(brand_code)
    return {model_code for model_code, brands in brands_by_code.items() if len(brands) > 1}


def _ambiguous_model_codes_from_batch(df: pd.DataFrame, models_by_code_unbranded: dict[str, list[ModelRecord]]) -> set[str]:
    return _ambiguous_model_codes_from_rows((raw_row.to_dict() for _, raw_row in df.iterrows()), models_by_code_unbranded)


def _import_historical_dataframe(db: Session, df: pd.DataFrame, import_batch: str) -> dict:
    if df.empty:
        df = pd.DataFrame([{col: None for col in df.columns}])
    rows = (raw_row.to_dict() for _, raw_row in df.iterrows())
    models_by_code, models_by_code_unbranded, models_by_name = _preload_models(db, df)
    ambiguous_model_codes = _ambiguous_model_codes_from_batch(df, models_by_code_unbranded)
    series_codes = _series_category_codes(db)
    models_by_series = _load_series_models(db, series_codes)
    return _import_historical_rows(
        db,
        rows,
        import_batch,
        models_by_code=models_by_code,
        models_by_code_unbranded=models_by_code_unbranded,
        models_by_name=models_by_name,
        ambiguous_model_codes=ambiguous_model_codes,
        series_codes=series_codes,
        models_by_series=models_by_series,
    )


def _model_lookup_values_from_rows(rows: Iterable[dict]) -> tuple[set[str | None], set[str | None]]:
    model_code_values = set()
    model_text_values = set()
    for row in rows:
        model_code_values.add(_clean_value(_get(row, "型号码")))
        model_text_values.add(_clean_value(_get(row, "型号")))
    return model_code_values, model_text_values


def _historical_values_from_existing(existing: HistoricalMapping) -> dict:
    return {
        "import_batch": existing.import_batch,
        "platform": existing.platform,
        "item_id": existing.item_id,
        "item_url": existing.item_url,
        "item_name": existing.item_name,
        "item_name_norm": existing.item_name_norm,
        "year": existing.year,
        "month_num": existing.month_num,
        "week": existing.week,
        "month": existing.month,
        "report_type": existing.report_type,
        "channel": existing.channel,
        "category_name_raw": existing.category_name_raw,
        "category_code_raw": existing.category_code_raw,
        "brand_raw": existing.brand_raw,
        "brand_code_raw": existing.brand_code_raw,
        "model_text": existing.model_text,
        "model_type": existing.model_type,
        "model_code_raw": existing.model_code_raw,
        "model_id": existing.model_id,
        "model_code": existing.model_code,
        "category_code": existing.category_code,
        "sales_amount": existing.sales_amount,
        "sales_qty": existing.sales_qty,
        "price": existing.price,
        "match_key_type": existing.match_key_type,
        "raw_payload": existing.raw_payload,
        "updated_at": existing.updated_at,
    }


def _apply_historical_batch(
    db: Session,
    merged_rows: dict[tuple[str, str, int, int, Optional[str], str], dict],
    merged_row_nums: dict[tuple[str, str, int, int, Optional[str], str], list[int]],
    seen_current_keys: set[tuple[str, str, int, int, Optional[str], str]],
    seen_row_nums: dict[tuple[str, str, int, int, Optional[str], str], list[int]],
) -> tuple[int, int]:
    created = 0
    updated = 0
    touched_rows = []
    existing_by_key = _preload_existing_history(db, set(merged_rows))
    for history_key, values in merged_rows.items():
        row_nums = merged_row_nums[history_key]
        existing = existing_by_key.get(history_key)
        if existing:
            touched_rows.append(existing)
            if history_key in seen_current_keys:
                all_row_nums = seen_row_nums.setdefault(history_key, [])
                all_row_nums.extend(row_nums)
                merged_values = _historical_values_from_existing(existing)
                _merge_duplicate_history_values(merged_values, values, all_row_nums)
                for key, value in merged_values.items():
                    setattr(existing, key, value)
            else:
                for key, value in values.items():
                    setattr(existing, key, value)
                updated += 1
        else:
            new_row = HistoricalMapping(**values)
            db.add(new_row)
            touched_rows.append(new_row)
            created += 1
        if history_key not in seen_current_keys:
            seen_current_keys.add(history_key)
            seen_row_nums[history_key] = list(row_nums)
        elif history_key not in seen_row_nums:
            seen_row_nums[history_key] = list(row_nums)
    db.commit()
    for row in touched_rows:
        if row in db:
            db.expunge(row)
    return created, updated


def _import_historical_rows(
    db: Session,
    rows: Iterable[dict],
    import_batch: str,
    *,
    models_by_code: dict[tuple[str, str], ModelRecord],
    models_by_code_unbranded: dict[str, list[ModelRecord]],
    models_by_name: dict[str, list[ModelRecord]],
    ambiguous_model_codes: set[str],
    series_codes: Optional[set[str]] = None,
    models_by_series: Optional[dict[tuple[str, str, str, str], ModelRecord]] = None,
    progress_cb: Optional[Callable[[int], None]] = None,
) -> dict:
    series_codes = series_codes or set()
    models_by_series = models_by_series or {}
    success = 0
    created = 0
    updated = 0
    errors = []
    categories_by_code, categories_by_name = _preload_categories(db)
    merged_rows: dict[tuple[str, str, int, int, Optional[str], str], dict] = {}
    merged_row_nums: dict[tuple[str, str, int, int, Optional[str], str], list[int]] = {}
    seen_current_keys: set[tuple[str, str, int, int, Optional[str], str]] = set()
    seen_row_nums: dict[tuple[str, str, int, int, Optional[str], str], list[int]] = {}

    def flush_batch() -> None:
        nonlocal created, updated, merged_rows, merged_row_nums
        if not merged_rows:
            return
        batch_created, batch_updated = _apply_historical_batch(
            db,
            merged_rows,
            merged_row_nums,
            seen_current_keys,
            seen_row_nums,
        )
        created += batch_created
        updated += batch_updated
        merged_rows = {}
        merged_row_nums = {}

    idx = -1
    for idx, row in enumerate(rows):
        row_num = idx + 2
        if progress_cb is not None and idx and idx % 1000 == 0:
            progress_cb(idx)
        platform = _normalize_platform(_get(row, "商场")) or _normalize_platform(_get(row, "渠道"))
        item_name = _clean_value(_get(row, "标题"))
        model_text = _clean_value(_get(row, "型号"))
        year = _parse_year(_get(row, "年"))
        month_num = _parse_month(_get(row, "月"))

        missing = []
        if not platform:
            missing.append("商场/渠道不能为空")
        if not item_name:
            missing.append("标题不能为空")
        if year is None:
            missing.append("年不能为空")
        if month_num is None:
            missing.append("月不能为空")
        if missing:
            errors.append({"row": row_num, "reason": "；".join(missing)})
            continue
        if month_num < 1 or month_num > 12:
            errors.append({"row": row_num, "reason": "月必须为 1-12"})
            continue

        item_url = _clean_value(_get(row, "网址"))
        parsed = extract_item_id(item_url)
        item_id = None
        if parsed:
            parsed_platform, item_id = parsed
            platform = parsed_platform

        brand_raw = _clean_value(_get(row, "品牌"))
        brand_code_raw = _clean_value(_get(row, "品牌码"))
        effective_brand_code = _effective_brand_code(brand_code_raw, brand_raw)
        model_code_raw = _clean_value(_get(row, "型号码"))
        model_type_raw = _clean_value(_get(row, "机型"))
        category_name_raw = _clean_value(_get(row, "品类"))
        category_code_raw = _clean_value(_get(row, "品类码"))
        resolved_category_code = _resolve_category_code(
            category_code_raw=category_code_raw,
            category_name_raw=category_name_raw,
            categories_by_code=categories_by_code,
            categories_by_name=categories_by_name,
        )
        model, reason = _get_or_create_model(
            db,
            model_code_raw=model_code_raw,
            model_text=model_text,
            brand_code_raw=effective_brand_code,
            brand_raw=brand_raw,
            category_code=resolved_category_code,
            models_by_code=models_by_code,
            models_by_code_unbranded=models_by_code_unbranded,
            models_by_name=models_by_name,
            ambiguous_model_codes=ambiguous_model_codes,
            model_type_raw=model_type_raw,
            series_codes=series_codes,
            models_by_series=models_by_series,
        )
        if reason:
            errors.append({"row": row_num, "reason": reason})
            continue
        item_name_norm = _normalize_item_name(item_name)
        week = _clean_value(_get(row, "周"))
        month = f"{year:04d}-{month_num:02d}"
        match_key_type = _match_key_type(item_id, item_url, item_name_norm)
        history_key = _history_identity_key(
            platform=platform,
            item_id=item_id,
            item_url=item_url,
            item_name_norm=item_name_norm,
            year=year,
            month_num=month_num,
            week=week,
        )

        values = {
            "import_batch": import_batch,
            "platform": platform,
            "item_id": item_id,
            "item_url": item_url,
            "item_name": item_name,
            "item_name_norm": item_name_norm,
            "year": year,
            "month_num": month_num,
            "week": week,
            "month": month,
            "report_type": _clean_value(_get(row, "报告类型")),
            "channel": _clean_value(_get(row, "渠道")),
            "category_name_raw": category_name_raw,
            "category_code_raw": category_code_raw,
            "brand_raw": brand_raw,
            "brand_code_raw": brand_code_raw or effective_brand_code,
            "model_text": model_text,
            "model_type": _clean_value(_get(row, "机型")),
            "model_code_raw": model_code_raw,
            "model_id": model.id if model else None,
            "model_code": model.model_code if model else None,
            "category_code": model.category_code if model else resolved_category_code,
            "sales_amount": _clean_decimal(_get(row, "销额")),
            "sales_qty": _clean_int(_get(row, "销量")),
            "price": _clean_decimal(_get(row, "单价")),
            "match_key_type": match_key_type,
            "raw_payload": _json_safe_row(row),
            "updated_at": datetime.utcnow(),
        }

        if history_key in merged_rows:
            row_nums = merged_row_nums[history_key]
            row_nums.append(row_num)
            _merge_duplicate_history_values(merged_rows[history_key], values, row_nums)
        else:
            merged_rows[history_key] = values
            merged_row_nums[history_key] = [row_num]
        success += 1
        if len(merged_rows) >= 1000:
            flush_batch()

    flush_batch()
    if progress_cb is not None:
        progress_cb(idx + 1)
    return {"success": success, "created": created, "updated": updated, "errors": errors, "import_batch": import_batch}


def _import_historical_standard_stream(
    db: Session,
    standard_rows_factory,
    import_batch: str,
    *,
    progress_cb: Optional[Callable[[int], None]] = None,
) -> dict:
    model_code_values, model_text_values = _model_lookup_values_from_rows(standard_rows_factory())
    models_by_code, models_by_code_unbranded, models_by_name = _load_preview_models(db, model_code_values, model_text_values)
    ambiguous_model_codes = _ambiguous_model_codes_from_rows(
        standard_rows_factory(),
        models_by_code_unbranded,
    )
    series_codes = _series_category_codes(db)
    models_by_series = _load_series_models(db, series_codes)
    return _import_historical_rows(
        db,
        standard_rows_factory(),
        import_batch,
        models_by_code=models_by_code,
        models_by_code_unbranded=models_by_code_unbranded,
        models_by_name=models_by_name,
        ambiguous_model_codes=ambiguous_model_codes,
        series_codes=series_codes,
        models_by_series=models_by_series,
        progress_cb=progress_cb,
    )


def _import_historical_stream(
    db: Session,
    raw_rows_factory,
    mapping: dict[str, str],
    category_code: Optional[str],
    import_batch: str,
) -> dict:
    return _import_historical_standard_stream(
        db,
        lambda: (
            _standardize_historical_row(row, mapping, category_code)
            for row in raw_rows_factory()
        ),
        import_batch,
    )


_HISTORICAL_ACTIVE_JOBS: set[int] = set()


def _update_historical_job(job_id: int, **fields) -> None:
    progress_db = SessionLocal()
    try:
        job = progress_db.query(HistoricalImportJob).filter_by(id=job_id).first()
        if not job:
            return
        for key, value in fields.items():
            setattr(job, key, value)
        progress_db.commit()
    finally:
        progress_db.close()


def _mark_interrupted_historical_jobs(db: Session) -> None:
    jobs = db.query(HistoricalImportJob).filter(
        HistoricalImportJob.status == "running",
        HistoricalImportJob.id.notin_(list(_HISTORICAL_ACTIVE_JOBS) or [-1]),
    ).all()
    if not jobs:
        return
    for job in jobs:
        job.status = "error"
        job.stage = "interrupted"
        job.stage_label = "任务已中断"
        job.error_msg = "后端服务重启，后台导入线程已中断，请重新上传"
        job.finished_at = datetime.utcnow()
    db.commit()


PART_SUFFIX_RE = re.compile(r"[-_—–\s]*(?:part\s*\d+|第?\d+部分|\d+)$", re.IGNORECASE)


def _derive_import_batch(filenames: list[str], explicit: Optional[str]) -> str:
    if explicit and explicit.strip():
        return explicit.strip()[:200]
    if len(filenames) == 1:
        return Path(filenames[0]).name[:200]
    stems = [Path(name).stem for name in filenames]
    base = PART_SUFFIX_RE.sub("", stems[0]).strip(" -_—–()（）[]【】") or stems[0]
    return f"{base}（合并{len(filenames)}个文件）"[:200]


def _cache_standardized_rows(
    *,
    path: Path,
    xls: pd.ExcelFile,
    sheet_name: str,
    columns: list[str],
    mapping: dict[str, str],
    category_code: Optional[str],
    cache_path: Path,
) -> int:
    usecols = _mapped_columns(mapping, columns)
    if path.suffix.lower() == ".xls":
        df = _read_sheet_preview(xls, sheet_name, usecols=usecols)
        iterator = (
            _standardize_historical_row(raw_row.to_dict(), mapping, category_code)
            for _, raw_row in df.iterrows()
        )
    else:
        iterator = (
            _standardize_historical_row(raw_row, mapping, category_code)
            for raw_row in _iter_sheet_rows_streaming(
                path, sheet_name, columns=columns, usecols=usecols
            )
        )
    count = 0
    with open(cache_path, "wb") as cache_file:
        for row in iterator:
            pickle.dump(row, cache_file, protocol=pickle.HIGHEST_PROTOCOL)
            count += 1
    return count


def _cached_rows_factory(cache_path: Path):
    def rows():
        with open(cache_path, "rb") as cache_file:
            while True:
                try:
                    yield pickle.load(cache_file)
                except EOFError:
                    break

    return rows


def _run_historical_import_thread(job_id: int) -> None:
    db = SessionLocal()
    cache_paths: list[Path] = []
    try:
        job = db.query(HistoricalImportJob).filter_by(id=job_id).first()
        if not job:
            return
        files = list(job.files_data or [])
        _HISTORICAL_ACTIVE_JOBS.add(job_id)
        _update_historical_job(
            job_id,
            status="running",
            stage="preparing",
            stage_label="正在准备导入",
            progress=1,
        )

        total_rows = 0
        file_totals: list[int] = []
        for item in files:
            path = _find_tmp_file(item["temp_file_id"])
            if path.suffix.lower() == ".xls":
                xls = pd.ExcelFile(path)
                try:
                    file_totals.append(len(_read_sheet_preview(xls, item["sheet_name"])))
                finally:
                    xls.close()
            else:
                file_totals.append(_sheet_total_rows_streaming(path, item["sheet_name"]))
            total_rows += file_totals[-1]
        _update_historical_job(job_id, total_rows=total_rows, progress=2)

        processed_rows = 0
        success_rows = 0
        created_rows = 0
        updated_rows = 0
        all_errors: list[dict] = []
        errors_truncated = False

        for index, item in enumerate(files):
            current_file = item.get("filename") or Path(item["temp_file_id"]).name
            _update_historical_job(
                job_id,
                stage="parsing",
                stage_label=f"正在解析第 {index + 1}/{len(files)} 个文件：{current_file}",
                progress=min(10, 2 + index * 5),
            )
            path = _find_tmp_file(item["temp_file_id"])
            xls = pd.ExcelFile(path)
            cache_path = Path(settings.UPLOAD_DIR) / "tmp" / f"hist_import_{job_id}_{index}.pkl"
            cache_paths.append(cache_path)
            try:
                if item["sheet_name"] not in xls.sheet_names:
                    raise HTTPException(400, "选择的 sheet 不存在")
                df_header = _read_sheet_preview(xls, item["sheet_name"], nrows=0)
                columns = [str(col).strip() for col in df_header.columns]
                mapping = _normalize_mapping_for_columns(item["mapping"], columns)
                file_count = _cache_standardized_rows(
                    path=path,
                    xls=xls,
                    sheet_name=item["sheet_name"],
                    columns=columns,
                    mapping=mapping,
                    category_code=item.get("category_code"),
                    cache_path=cache_path,
                )
            finally:
                xls.close()

            if file_count != file_totals[index]:
                total_rows += file_count - file_totals[index]
                file_totals[index] = file_count
                _update_historical_job(job_id, total_rows=total_rows)

            base_processed = processed_rows

            def progress_cb(done: int, base: int = base_processed) -> None:
                done_rows = base + done
                percent = 10 + int(done_rows / max(total_rows, 1) * 88)
                _update_historical_job(
                    job_id,
                    stage="importing",
                    stage_label=f"正在写入第 {index + 1}/{len(files)} 个文件：{current_file}",
                    processed_rows=done_rows,
                    progress=min(99, percent),
                )

            _update_historical_job(
                job_id,
                stage="importing",
                stage_label=f"正在写入第 {index + 1}/{len(files)} 个文件：{current_file}",
                processed_rows=processed_rows,
                progress=min(99, 10 + int(processed_rows / max(total_rows, 1) * 88)),
            )
            result = _import_historical_standard_stream(
                db,
                _cached_rows_factory(cache_path),
                job.import_batch,
                progress_cb=progress_cb,
            )
            processed_rows += file_count
            success_rows += result.get("success", 0)
            created_rows += result.get("created", 0)
            updated_rows += result.get("updated", 0)
            for error in result.get("errors", []):
                if len(all_errors) >= 5000:
                    errors_truncated = True
                    break
                all_errors.append({**error, "file": current_file})
            cache_path.unlink(missing_ok=True)
            _update_historical_job(
                job_id,
                processed_files=index + 1,
                processed_rows=min(processed_rows, total_rows) if total_rows else processed_rows,
                success_rows=success_rows,
                created_rows=created_rows,
                updated_rows=updated_rows,
                error_rows=len(all_errors),
                progress=min(99, 10 + int((index + 1) / len(files) * 88)),
            )

        result_data = {
            "success": success_rows,
            "created": created_rows,
            "updated": updated_rows,
            "errors": all_errors,
            "errors_truncated": errors_truncated,
            "import_batch": job.import_batch,
            "files": [item.get("filename") for item in files],
        }
        progress_db = SessionLocal()
        try:
            done_job = progress_db.query(HistoricalImportJob).filter_by(id=job_id).first()
            if done_job:
                done_job.status = "done"
                done_job.stage = "done"
                done_job.stage_label = "导入完成"
                done_job.progress = 100
                done_job.processed_files = len(files)
                done_job.processed_rows = total_rows
                done_job.total_rows = total_rows
                done_job.success_rows = success_rows
                done_job.created_rows = created_rows
                done_job.updated_rows = updated_rows
                done_job.error_rows = len(all_errors)
                done_job.result_data = result_data
                done_job.finished_at = datetime.utcnow()
                progress_db.commit()
        finally:
            progress_db.close()
        for item in files:
            try:
                _find_tmp_file(item["temp_file_id"]).unlink(missing_ok=True)
            except HTTPException:
                pass
    except Exception as exc:  # noqa: BLE001
        _update_historical_job(
            job_id,
            status="error",
            stage="error",
            stage_label="导入失败",
            error_msg=str(getattr(exc, "detail", exc)),
            finished_at=datetime.utcnow(),
        )
    finally:
        _HISTORICAL_ACTIVE_JOBS.discard(job_id)
        for cache_path in cache_paths:
            cache_path.unlink(missing_ok=True)
        db.close()


def _historical_job_response(job: HistoricalImportJob) -> dict:
    resp = {
        "job_id": job.id,
        "status": job.status,
        "progress": job.progress,
        "stage": job.stage,
        "stage_label": job.stage_label,
        "import_batch": job.import_batch,
        "filename": job.filename,
        "total_files": job.total_files,
        "processed_files": job.processed_files,
        "total_rows": job.total_rows,
        "processed_rows": job.processed_rows,
        "success_rows": job.success_rows,
        "created_rows": job.created_rows,
        "updated_rows": job.updated_rows,
        "error_rows": job.error_rows,
        "error_msg": job.error_msg,
        "created_at": format_beijing_datetime(job.created_at),
        "finished_at": format_beijing_datetime(job.finished_at),
    }
    if job.status == "done" and job.result_data:
        resp["result"] = job.result_data
    return resp


@router.post("/jobs")
def create_historical_import_job(
    payload: HistoricalImportJobIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if len(payload.files) > 50:
        raise HTTPException(400, "单次最多合并导入 50 个文件")
    file_metas = []
    for item in payload.files:
        _ensure_historical_category_visible(db, current_user, item.category_code)
        path = _find_tmp_file(item.temp_file_id)
        xls = pd.ExcelFile(path)
        try:
            if item.sheet_name not in xls.sheet_names:
                raise HTTPException(400, "选择的 sheet 不存在")
            df_header = _read_sheet_preview(xls, item.sheet_name, nrows=0)
            columns = [str(col).strip() for col in df_header.columns]
            issues = _mapping_issues(item.mapping, item.category_code, columns)
            if issues:
                raise HTTPException(422, "；".join(issues))
            mapping = _normalize_mapping_for_columns(item.mapping, columns)
            issues = _mapping_issues(mapping, item.category_code, columns)
            if issues:
                raise HTTPException(422, "；".join(issues))
        finally:
            xls.close()
        file_metas.append({
            "temp_file_id": item.temp_file_id,
            "filename": _original_filename_from_tmp(path, item.temp_file_id),
            "sheet_name": item.sheet_name,
            "mapping": mapping,
            "category_code": item.category_code,
        })

    filenames = [item["filename"] for item in file_metas]
    import_batch = _derive_import_batch(filenames, payload.import_batch)
    job = HistoricalImportJob(
        status="pending",
        stage="pending",
        stage_label="等待处理",
        progress=0,
        import_batch=import_batch,
        filename=filenames[0],
        total_files=len(file_metas),
        files_data=file_metas,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    threading.Thread(
        target=_run_historical_import_thread,
        args=(job.id,),
        daemon=True,
    ).start()
    return _historical_job_response(job)


@router.get("/jobs")
def list_historical_import_jobs(
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _mark_interrupted_historical_jobs(db)
    jobs = (
        db.query(HistoricalImportJob)
        .order_by(HistoricalImportJob.created_at.desc(), HistoricalImportJob.id.desc())
        .limit(limit)
        .all()
    )
    return [_historical_job_response(job) for job in jobs]


@router.get("/jobs/{job_id}")
def get_historical_import_job(
    job_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _mark_interrupted_historical_jobs(db)
    job = db.query(HistoricalImportJob).filter_by(id=job_id).first()
    if not job:
        raise HTTPException(404, "导入任务不存在")
    return _historical_job_response(job)


@router.post("/mappings/batch/merge")
def merge_batches(
    body: BatchMergeIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    batches = list(dict.fromkeys(batch for batch in body.batches if batch))
    if len(batches) < 2:
        raise HTTPException(400, "请至少选择两个批次进行合并")
    target_batch = (body.target_batch or "").strip() or _derive_import_batch(
        [f"{batch}.xlsx" for batch in batches],
        None,
    )
    q = db.query(HistoricalMapping).filter(HistoricalMapping.import_batch.in_(batches))
    q = _filter_historical_visible_categories(q, db, current_user)
    updated = q.update(
        {HistoricalMapping.import_batch: target_batch},
        synchronize_session=False,
    )
    if updated == 0:
        raise HTTPException(404, "所选批次不存在或已删除")
    db.commit()
    return {"import_batch": target_batch, "updated": updated}


@router.get("/template")
def download_historical_template():
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "历史库"
    headers = [
        HISTORICAL_STANDARD_FIELDS["year"],
        HISTORICAL_STANDARD_FIELDS["month_num"],
        HISTORICAL_STANDARD_FIELDS["week"],
        HISTORICAL_STANDARD_FIELDS["report_type"],
        HISTORICAL_STANDARD_FIELDS["channel"],
        HISTORICAL_STANDARD_FIELDS["platform"],
        HISTORICAL_STANDARD_FIELDS["category_name_raw"],
        HISTORICAL_STANDARD_FIELDS["brand_raw"],
        HISTORICAL_STANDARD_FIELDS["model_text"],
        HISTORICAL_STANDARD_FIELDS["model_type"],
        HISTORICAL_STANDARD_FIELDS["category_code_raw"],
        HISTORICAL_STANDARD_FIELDS["brand_code_raw"],
        HISTORICAL_STANDARD_FIELDS["model_code_raw"],
        HISTORICAL_STANDARD_FIELDS["item_name"],
        HISTORICAL_STANDARD_FIELDS["sales_amount"],
        HISTORICAL_STANDARD_FIELDS["sales_qty"],
        HISTORICAL_STANDARD_FIELDS["price"],
        HISTORICAL_STANDARD_FIELDS["item_url"],
    ]
    sheet.append(headers)
    sheet.append(["2026", "9", "周36", "月报", "京东自营", "京东", "电视", "索尼", "XR-77A95L", "XR系列", "tv", "SONY", "X95L", "索尼 77 英寸 4K OLED 电视 XR-77A95L", "12999", "10", "1299.9", "https://item.jd.com/100123456.html"])
    output = io.BytesIO()
    workbook.save(output)
    quoted_filename = quote("历史库映射导入模板.xlsx")
    headers_ = {"Content-Disposition": f"attachment; filename*=UTF-8''{quoted_filename}"}
    return Response(
        content=output.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers_,
    )


@router.post("/import")
async def import_historical_mappings(file: UploadFile = File(...), db: Session = Depends(get_db)):
    _validate_excel_file(file)
    _, save_path, safe_filename = await save_tmp_file(file, settings.UPLOAD_DIR)
    try:
        xls = pd.ExcelFile(save_path)
        sheet_name, columns, mapping = _detect_sheet_and_mapping(xls)
        category_code = _infer_category_code(safe_filename, db)
        mapping = _normalize_mapping_for_columns(mapping, columns)
        usecols = _mapped_columns(mapping, columns)
        if save_path.suffix.lower() == ".xls":
            df = _read_sheet_preview(xls, sheet_name, usecols=usecols)
            standardized_df = _standardize_historical_df(df, mapping, category_code)
            return _import_historical_dataframe(db, standardized_df, safe_filename)
        return _import_historical_stream(
            db,
            lambda: _iter_sheet_rows_streaming(save_path, sheet_name, columns=columns, usecols=usecols),
            mapping,
            category_code,
            safe_filename,
        )
    finally:
        save_path.unlink(missing_ok=True)


@router.post("/headers")
async def historical_headers(file: UploadFile = File(...), db: Session = Depends(get_db)):
    _validate_excel_file(file)
    temp_file_id, save_path, safe_filename = await save_tmp_file(file, settings.UPLOAD_DIR)
    try:
        xls = pd.ExcelFile(save_path)
        sheet_name, columns, mapping = _detect_sheet_and_mapping(xls)
        category_code = _infer_category_code(safe_filename, db)
        return _historical_preview_response(
            temp_file_id=temp_file_id,
            filename=safe_filename,
            xls=xls,
            path=save_path,
            sheet_name=sheet_name,
            columns=columns,
            mapping=mapping,
            category_code=category_code,
            db=db,
        )
    except Exception:
        save_path.unlink(missing_ok=True)
        raise


@router.post("/preview")
def historical_preview(
    payload: HistoricalPreviewIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ensure_historical_category_visible(db, current_user, payload.category_code)
    save_path = _find_tmp_file(payload.temp_file_id)
    xls = pd.ExcelFile(save_path)
    if payload.sheet_name not in xls.sheet_names:
        raise HTTPException(400, "选择的 sheet 不存在")
    df_header = _read_sheet_preview(xls, payload.sheet_name, nrows=0)
    columns = [str(col).strip() for col in df_header.columns]
    filename = _original_filename_from_tmp(save_path, payload.temp_file_id)
    return _historical_preview_response(
        temp_file_id=payload.temp_file_id,
        filename=filename,
        xls=xls,
        path=save_path,
        sheet_name=payload.sheet_name,
        columns=columns,
        mapping=payload.mapping,
        category_code=payload.category_code,
        db=db,
    )


@router.post("/confirm")
def historical_confirm(
    payload: HistoricalConfirmIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ensure_historical_category_visible(db, current_user, payload.category_code)
    save_path = _find_tmp_file(payload.temp_file_id)
    xls = pd.ExcelFile(save_path)
    if payload.sheet_name not in xls.sheet_names:
        raise HTTPException(400, "选择的 sheet 不存在")
    df_header = _read_sheet_preview(xls, payload.sheet_name, nrows=0)
    columns = [str(col).strip() for col in df_header.columns]
    issues = _mapping_issues(payload.mapping, payload.category_code, columns)
    if issues:
        raise HTTPException(422, "；".join(issues))
    mapping = _normalize_mapping_for_columns(payload.mapping, columns)
    issues = _mapping_issues(mapping, payload.category_code, columns)
    if issues:
        raise HTTPException(422, "；".join(issues))
    usecols = _mapped_columns(mapping, columns)
    filename = _original_filename_from_tmp(save_path, payload.temp_file_id)
    if save_path.suffix.lower() == ".xls":
        df = _read_sheet_preview(xls, payload.sheet_name, usecols=usecols)
        standardized_df = _standardize_historical_df(df, mapping, payload.category_code)
        result = _import_historical_dataframe(db, standardized_df, filename)
    else:
        result = _import_historical_stream(
            db,
            lambda: _iter_sheet_rows_streaming(save_path, payload.sheet_name, columns=columns, usecols=usecols),
            mapping,
            payload.category_code,
            filename,
        )
    save_path.unlink(missing_ok=True)
    return result


@router.get("/batches")
def list_batches(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = db.query(
        HistoricalMapping.import_batch,
        func.count(HistoricalMapping.id).label("count"),
        func.max(HistoricalMapping.updated_at).label("updated_at"),
    ).filter(HistoricalMapping.import_batch.isnot(None))
    q = _filter_historical_visible_categories(q, db, current_user)
    rows = (
        q.group_by(HistoricalMapping.import_batch)
        .order_by(func.max(HistoricalMapping.updated_at).desc(), func.max(HistoricalMapping.id).desc())
        .all()
    )
    return [{"batch": r.import_batch, "count": r.count, "updated_at": format_beijing_datetime(r.updated_at)} for r in rows]


HISTORICAL_EXPORT_ROWS_PER_SHEET = 1_000_000

HISTORICAL_EXPORT_HEADERS = [
    "商场/平台",
    "商品ID",
    "标题",
    "品牌",
    "品牌码",
    "型号",
    "机型/系列",
    "标准型号",
    "型号码",
    "品类",
    "品类码",
    "年",
    "月",
    "年月",
    "周",
    "报告类型",
    "渠道",
    "销量",
    "单价",
    "销额",
    "网址",
    "导入批次",
    "匹配键",
]


def _historical_export_values(hm: HistoricalMapping, m: Optional[ModelRecord]) -> list:
    return [
        hm.platform,
        hm.item_id,
        hm.item_name,
        hm.brand_raw,
        hm.brand_code_raw,
        hm.model_text,
        hm.model_type,
        m.model_name if m else None,
        hm.model_code,
        hm.category_name_raw,
        hm.category_code or hm.category_code_raw,
        hm.year,
        hm.month_num,
        hm.month,
        hm.week,
        hm.report_type,
        hm.channel,
        hm.sales_qty,
        float(hm.price) if hm.price is not None else None,
        float(hm.sales_amount) if hm.sales_amount is not None else None,
        hm.item_url,
        hm.import_batch,
        hm.match_key_type,
    ]


def _historical_export_query(db: Session, *, category_codes: Optional[list[str]], import_batch: Optional[str]):
    q = (
        db.query(HistoricalMapping, ModelRecord)
        .outerjoin(ModelRecord, HistoricalMapping.model_id == ModelRecord.id)
    )
    if category_codes is not None:
        q = q.filter(HistoricalMapping.category_code.in_(category_codes))
    if import_batch:
        q = q.filter(HistoricalMapping.import_batch == import_batch)
    return q


def _historical_export_job_response(job: HistoricalExportJob) -> dict:
    return {
        "job_id": job.id,
        "status": job.status,
        "progress": job.progress,
        "import_batch": job.import_batch,
        "total_rows": job.total_rows,
        "processed_rows": job.processed_rows,
        "filename": job.filename,
        "error_msg": job.error_msg,
        "download_url": (
            f"/api/historical/export/download/{job.file_token}"
            if job.status == "done" and job.file_token
            else None
        ),
        "created_at": format_beijing_datetime(job.created_at),
        "finished_at": format_beijing_datetime(job.finished_at),
    }


def _run_historical_export_thread(job_id: int) -> None:
    db = SessionLocal()
    file_path = None
    try:
        job = db.query(HistoricalExportJob).filter_by(id=job_id).first()
        if not job:
            return
        job.status = "running"
        job.progress = 1
        db.commit()

        q = _historical_export_query(
            db,
            category_codes=job.category_codes,
            import_batch=job.import_batch,
        )
        total = q.count()
        if total == 0:
            job.status = "error"
            job.error_msg = "没有符合条件的数据"
            job.finished_at = datetime.utcnow()
            db.commit()
            return
        job.total_rows = total
        job.progress = 5
        db.commit()

        export_dir = Path(settings.EXPORT_DIR)
        export_dir.mkdir(parents=True, exist_ok=True)
        token = uuid.uuid4().hex
        file_path = export_dir / f"historical_{token}.xlsx"
        job.filename = f"historical_export_{job.import_batch or 'all'}.xlsx"

        workbook = Workbook(write_only=True)
        worksheet = workbook.create_sheet("历史库")
        worksheet.append(HISTORICAL_EXPORT_HEADERS)
        sheet_rows = 0
        sheet_index = 1

        last_id: Optional[int] = None
        processed = 0
        page_size = 5000
        while True:
            page_q = q
            if last_id is not None:
                page_q = page_q.filter(HistoricalMapping.id > last_id)
            page_rows = page_q.order_by(HistoricalMapping.id).limit(page_size).all()
            if not page_rows:
                break
            for hm, m in page_rows:
                if sheet_rows >= HISTORICAL_EXPORT_ROWS_PER_SHEET:
                    sheet_index += 1
                    worksheet = workbook.create_sheet(f"历史库{sheet_index}")
                    worksheet.append(HISTORICAL_EXPORT_HEADERS)
                    sheet_rows = 0
                worksheet.append(_historical_export_values(hm, m))
                sheet_rows += 1
            last_id = page_rows[-1][0].id
            processed += len(page_rows)
            job.processed_rows = processed
            job.progress = min(99, 5 + int(90 * processed / max(total, 1)))
            db.commit()
        workbook.save(str(file_path))

        job.status = "done"
        job.progress = 100
        job.processed_rows = processed
        job.file_token = token
        job.finished_at = datetime.utcnow()
        db.commit()
    except Exception as exc:  # noqa: BLE001
        if file_path is not None:
            file_path.unlink(missing_ok=True)
        try:
            job = db.query(HistoricalExportJob).filter_by(id=job_id).first()
            if job:
                job.status = "error"
                job.error_msg = str(getattr(exc, "detail", exc))
                job.finished_at = datetime.utcnow()
                db.commit()
        except Exception:
            pass
    finally:
        db.close()


@router.post("/export/jobs")
def create_historical_export_job(
    payload: HistoricalExportJobIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    visible_codes = _visible_historical_category_codes(db, current_user)
    job = HistoricalExportJob(
        user_id=getattr(current_user, "id", None),
        status="pending",
        import_batch=(payload.import_batch or "").strip() or None,
        category_codes=sorted(visible_codes) if visible_codes is not None else None,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    threading.Thread(
        target=_run_historical_export_thread,
        args=(job.id,),
        daemon=True,
    ).start()
    return _historical_export_job_response(job)


@router.get("/export/jobs/{job_id}")
def get_historical_export_job(
    job_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    job = db.query(HistoricalExportJob).filter_by(id=job_id).first()
    if not job:
        raise HTTPException(404, "导出任务不存在")
    if getattr(current_user, "is_admin", 0) != 1 and job.user_id not in (None, getattr(current_user, "id", None)):
        raise HTTPException(403, "无权查看该导出任务")
    return _historical_export_job_response(job)


@router.get("/export/download/{token}")
def download_historical_export(token: str, db: Session = Depends(get_db)):
    job = db.query(HistoricalExportJob).filter_by(file_token=token).first()
    if not job or not job.filename:
        raise HTTPException(404, "文件不存在或已过期")
    file_path = Path(settings.EXPORT_DIR) / f"historical_{token}.xlsx"
    if not file_path.exists():
        raise HTTPException(404, "文件已被清理，请重新导出")
    return FileResponse(
        path=str(file_path),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(job.filename)}"},
    )


@router.get("/export")
def export_mappings(
    import_batch: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = (
        db.query(HistoricalMapping, ModelRecord)
        .outerjoin(ModelRecord, HistoricalMapping.model_id == ModelRecord.id)
    )
    q = _filter_historical_visible_categories(q, db, current_user)
    if import_batch:
        q = q.filter(HistoricalMapping.import_batch == import_batch)

    total = q.count()
    ensure_export_row_limit(total, max_rows=MAX_SYNC_EXPORT_ROWS, label="历史库导出")
    rows = q.order_by(HistoricalMapping.id).all()

    data = [_historical_export_values(hm, m) for hm, m in rows]
    df = pd.DataFrame(data, columns=HISTORICAL_EXPORT_HEADERS)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="历史库")
    buf.seek(0)
    filename = f"historical_export_{import_batch or 'all'}.xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )


@router.get("/mappings")
def list_mappings(
    platform: Optional[str] = Query(None),
    import_batch: Optional[str] = Query(None),
    category_code: Optional[str] = Query(None),
    model_keyword: Optional[str] = Query(None),
    item_keyword: Optional[str] = Query(None),
    month: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = (
        db.query(HistoricalMapping, ModelRecord)
        .outerjoin(ModelRecord, HistoricalMapping.model_id == ModelRecord.id)
    )
    q = _filter_historical_visible_categories(q, db, current_user)
    if platform:
        q = q.filter(HistoricalMapping.platform == platform.lower())
    if import_batch:
        q = q.filter(HistoricalMapping.import_batch == import_batch)
    if category_code:
        q = q.filter(HistoricalMapping.category_code == category_code)
    if month:
        q = q.filter(HistoricalMapping.month == month)
    if model_keyword:
        pattern = f"%{model_keyword}%"
        q = q.filter(or_(
            HistoricalMapping.model_text.ilike(pattern),
            HistoricalMapping.model_code.ilike(pattern),
            ModelRecord.model_name.ilike(pattern),
        ))
    if item_keyword:
        pattern = f"%{item_keyword}%"
        q = q.filter(or_(
            HistoricalMapping.item_name.ilike(pattern),
            HistoricalMapping.item_id.ilike(pattern),
            HistoricalMapping.item_url.ilike(pattern),
        ))

    total = q.count()
    rows = (
        q.order_by(HistoricalMapping.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    items = [
        {
            "id": hm.id,
            "platform": hm.platform,
            "item_id": hm.item_id,
            "item_url": hm.item_url,
            "item_name": hm.item_name,
            "brand_raw": hm.brand_raw,
            "brand_code_raw": hm.brand_code_raw,
            "model_text": hm.model_text,
            "model_type": hm.model_type,
            "model_id": hm.model_id,
            "model_code": hm.model_code,
            "standard_model_name": m.model_name if m else None,
            "category_code": hm.category_code,
            "category_name_raw": hm.category_name_raw,
            "year": hm.year,
            "month_num": hm.month_num,
            "month": hm.month,
            "week": hm.week,
            "sales_qty": hm.sales_qty,
            "price": float(hm.price) if hm.price is not None else None,
            "sales_amount": float(hm.sales_amount) if hm.sales_amount is not None else None,
            "import_batch": hm.import_batch,
            "match_key_type": hm.match_key_type,
            "updated_at": format_beijing_datetime(hm.updated_at),
        }
        for hm, m in rows
    ]
    return {"total": total, "page": page, "page_size": page_size, "items": items}


@router.delete("/mappings/batch", status_code=204)
def delete_batch(
    body: BatchDeleteIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = db.query(HistoricalMapping).filter(HistoricalMapping.import_batch == body.import_batch)
    q = _filter_historical_visible_categories(q, db, current_user)
    deleted = q.delete(synchronize_session=False)
    if deleted == 0:
        raise HTTPException(404, f"批次 '{body.import_batch}' 不存在或已删除")
    db.commit()


@router.delete("/mappings/{mapping_id}", status_code=204)
def delete_mapping(
    mapping_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = db.query(HistoricalMapping).filter(HistoricalMapping.id == mapping_id)
    q = _filter_historical_visible_categories(q, db, current_user)
    row = q.first()
    if not row:
        raise HTTPException(404, "记录不存在")
    db.delete(row)
    db.commit()
