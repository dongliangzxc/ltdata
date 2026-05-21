"""Analytics dashboard query helpers."""
from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote

import pandas as pd
from sqlalchemy import func, or_
from sqlalchemy.orm import Query, Session

from app.core.config import settings
from app.models.analytics_db import PublishedItem
from app.models.schemas import WorkbenchExportJob


_GROUP_COLUMNS = {
    "model": (PublishedItem.model_code, PublishedItem.model_name),
    "brand": (PublishedItem.brand_code, PublishedItem.brand_name),
    "platform": (PublishedItem.platform, PublishedItem.platform),
}

_CATEGORY_COLUMNS = (
    PublishedItem.category_name,
    PublishedItem.category_lv1,
    PublishedItem.category_lv2,
    PublishedItem.category_lv3,
    PublishedItem.category_lv4,
    PublishedItem.category_lv5,
)


def _category_fallback_expr():
    """Return category_name or the most specific non-empty category level."""
    return func.coalesce(
        func.nullif(PublishedItem.category_name, ""),
        func.nullif(PublishedItem.category_lv5, ""),
        func.nullif(PublishedItem.category_lv4, ""),
        func.nullif(PublishedItem.category_lv3, ""),
        func.nullif(PublishedItem.category_lv2, ""),
        func.nullif(PublishedItem.category_lv1, ""),
        "未填",
    )

_SUMMARY_EXPORT_COLUMNS = [
    ("dimension_key", "维度编码"),
    ("dimension_name", "维度名称"),
    ("sales_qty", "原始销量"),
    ("corrected_sales_qty", "修正后销量"),
    ("sales_amount", "原始销额"),
    ("avg_price", "原始均价"),
    ("record_count", "记录数"),
]

_DETAIL_EXPORT_COLUMNS = [
    ("month", "月份"),
    ("platform", "平台"),
    ("item_id", "商品ID"),
    ("item_name", "商品名"),
    ("shop_name", "店铺名"),
    ("category_name", "品类"),
    ("brand_code", "品牌编码"),
    ("brand_name", "品牌名称"),
    ("model_code", "型号编码"),
    ("model_name", "型号名称"),
    ("sales_qty", "原始销量"),
    ("corrected_sales_qty", "修正后销量"),
    ("sales_amount", "原始销额"),
    ("price", "原始均价"),
    ("published_at", "发布时间"),
]
_DETAIL_EXPORT_LABELS = dict(_DETAIL_EXPORT_COLUMNS)


def _like(value: str) -> str:
    return f"%{value}%"


def _metric_values(rows: list[PublishedItem]) -> dict[str, Any]:
    sales_qty = sum(int(r.sales_qty or 0) for r in rows)
    corrected_sales_qty = sum(
        int(r.corrected_sales_qty if r.corrected_sales_qty is not None else (r.sales_qty or 0))
        for r in rows
    )
    sales_amount = sum(float(r.sales_amount or 0) for r in rows)
    avg_price = round(sales_amount / sales_qty, 2) if sales_qty else None
    return {
        "sales_qty": sales_qty,
        "corrected_sales_qty": corrected_sales_qty,
        "sales_amount": round(sales_amount, 2),
        "avg_price": avg_price,
        "record_count": len(rows),
    }


def build_analytics_query(
    db: Session,
    *,
    year: Optional[int] = None,
    month: Optional[int] = None,
    brand: Optional[str] = None,
    category: Optional[str] = None,
    platform: Optional[str] = None,
    model_keyword: Optional[str] = None,
    item_keyword: Optional[str] = None,
) -> Query:
    """Build the filtered PublishedItem query used by dashboard endpoints."""
    query = db.query(PublishedItem)

    if year and month:
        query = query.filter(PublishedItem.month == int(year) * 100 + int(month))
    elif year:
        query = query.filter(
            PublishedItem.month >= int(year) * 100 + 1,
            PublishedItem.month <= int(year) * 100 + 12,
        )
    elif month:
        query = query.filter((PublishedItem.month % 100) == int(month))

    if brand:
        pattern = _like(brand)
        query = query.filter(
            or_(PublishedItem.brand_code.ilike(pattern), PublishedItem.brand_name.ilike(pattern))
        )
    if category:
        pattern = _like(category)
        query = query.filter(or_(*[col.ilike(pattern) for col in _CATEGORY_COLUMNS]))
    if platform:
        query = query.filter(PublishedItem.platform == platform)
    if model_keyword:
        pattern = _like(model_keyword)
        query = query.filter(
            or_(PublishedItem.model_code.ilike(pattern), PublishedItem.model_name.ilike(pattern))
        )
    if item_keyword:
        query = query.filter(PublishedItem.item_name.ilike(_like(item_keyword)))

    return query


def get_analytics_filters(db: Session) -> dict[str, Any]:
    """Return available filter dimensions from published analytics rows."""
    months_raw = [r[0] for r in db.query(PublishedItem.month).distinct().all() if r[0]]
    years = sorted({int(month) // 100 for month in months_raw}, reverse=True)
    months = sorted({int(month) % 100 for month in months_raw}, reverse=True)

    platforms = sorted(
        [r[0] for r in db.query(PublishedItem.platform).distinct().all() if r[0]]
    )

    brand_rows = (
        db.query(PublishedItem.brand_code, func.min(PublishedItem.brand_name))
        .filter(PublishedItem.brand_code.isnot(None), PublishedItem.brand_code != "")
        .group_by(PublishedItem.brand_code)
        .order_by(PublishedItem.brand_code)
        .all()
    )
    brands = [
        {"brand_code": code, "brand_name": name}
        for code, name in brand_rows
        if code
    ]

    category_expr = _category_fallback_expr()
    category_rows = db.query(category_expr.label("category_name")).distinct().all()
    categories = [
        {"category_name": row[0]}
        for row in sorted(category_rows, key=lambda item: item[0] or "")
        if row[0] and row[0] != "未填"
    ]

    return {
        "years": years,
        "months": months,
        "platforms": platforms,
        "brands": brands,
        "categories": categories,
    }


def _summary_sort_expressions(sort_by: str, metrics: dict[str, Any]) -> list[Any]:
    """Return ORDER BY expressions for supported summary sort keys."""
    default_sort = [
        metrics["corrected_sales_qty"].desc(),
        metrics["sales_amount"].desc(),
        metrics["record_count"].desc(),
    ]
    sort_options = {
        "corrected_sales_qty_desc": default_sort,
        "corrected_sales_qty_asc": [metrics["corrected_sales_qty"].asc()],
        "sales_qty_desc": [metrics["sales_qty"].desc()],
        "sales_qty_asc": [metrics["sales_qty"].asc()],
        "sales_amount_desc": [metrics["sales_amount"].desc()],
        "sales_amount_asc": [metrics["sales_amount"].asc()],
        "record_count_desc": [metrics["record_count"].desc()],
        "record_count_asc": [metrics["record_count"].asc()],
    }
    return sort_options.get(sort_by, default_sort)


def get_analytics_summary(
    db: Session,
    *,
    year: Optional[int] = None,
    month: Optional[int] = None,
    brand: Optional[str] = None,
    category: Optional[str] = None,
    platform: Optional[str] = None,
    model_keyword: Optional[str] = None,
    item_keyword: Optional[str] = None,
    group_by: str = "model",
    page: int = 1,
    page_size: int = 20,
    sort_by: str = "corrected_sales_qty_desc",
    paginate: bool = True,
) -> dict[str, Any]:
    """Return grouped sales metrics for the analytics dashboard."""
    if group_by != "category" and group_by not in _GROUP_COLUMNS:
        group_by = "model"
    page = max(int(page or 1), 1)
    page_size = max(int(page_size or 20), 1)

    filtered = build_analytics_query(
        db,
        year=year,
        month=month,
        brand=brand,
        category=category,
        platform=platform,
        model_keyword=model_keyword,
        item_keyword=item_keyword,
    )

    corrected_qty_expr = func.coalesce(PublishedItem.corrected_sales_qty, PublishedItem.sales_qty, 0)
    sales_qty_expr = func.coalesce(PublishedItem.sales_qty, 0)
    sales_amount_expr = func.coalesce(PublishedItem.sales_amount, 0)

    totals_row = filtered.with_entities(
        func.coalesce(func.sum(sales_qty_expr), 0),
        func.coalesce(func.sum(corrected_qty_expr), 0),
        func.coalesce(func.sum(sales_amount_expr), 0),
        func.count(PublishedItem.id),
    ).one()
    total_sales_qty = int(totals_row[0] or 0)
    total_sales_amount = float(totals_row[2] or 0)
    totals = {
        "sales_qty": total_sales_qty,
        "corrected_sales_qty": int(totals_row[1] or 0),
        "sales_amount": round(total_sales_amount, 2),
        "avg_price": round(total_sales_amount / total_sales_qty, 2) if total_sales_qty else None,
        "record_count": int(totals_row[3] or 0),
    }

    if group_by == "category":
        dimension_key_expr = _category_fallback_expr()
        dimension_name_expr = dimension_key_expr
    else:
        key_col, name_col = _GROUP_COLUMNS[group_by]
        dimension_key_expr = func.coalesce(func.nullif(key_col, ""), "未填")
        dimension_name_expr = func.coalesce(
            func.nullif(func.min(name_col), ""),
            func.min(dimension_key_expr),
        )
    sales_qty_sum = func.coalesce(func.sum(sales_qty_expr), 0)
    corrected_qty_sum = func.coalesce(func.sum(corrected_qty_expr), 0)
    sales_amount_sum = func.coalesce(func.sum(sales_amount_expr), 0)
    record_count = func.count(PublishedItem.id)
    metrics = {
        "sales_qty": sales_qty_sum,
        "corrected_sales_qty": corrected_qty_sum,
        "sales_amount": sales_amount_sum,
        "record_count": record_count,
    }

    grouped_query = (
        filtered.with_entities(
            dimension_key_expr.label("dimension_key"),
            dimension_name_expr.label("dimension_name"),
            sales_qty_sum.label("sales_qty"),
            corrected_qty_sum.label("corrected_sales_qty"),
            sales_amount_sum.label("sales_amount"),
            record_count.label("record_count"),
        )
        .group_by(dimension_key_expr)
    )
    total = grouped_query.count()

    grouped_query = grouped_query.order_by(*_summary_sort_expressions(sort_by, metrics))
    if paginate:
        grouped_query = grouped_query.offset((page - 1) * page_size).limit(page_size)

    summary_rows = []
    for row in grouped_query.all():
        row_sales_qty = int(row.sales_qty or 0)
        row_sales_amount = float(row.sales_amount or 0)
        summary_rows.append(
            {
                "dimension_key": row.dimension_key,
                "dimension_name": row.dimension_name or row.dimension_key,
                "group_by": group_by,
                "sales_qty": row_sales_qty,
                "corrected_sales_qty": int(row.corrected_sales_qty or 0),
                "sales_amount": round(row_sales_amount, 2),
                "avg_price": round(row_sales_amount / row_sales_qty, 2) if row_sales_qty else None,
                "record_count": int(row.record_count or 0),
            }
        )

    return {
        "totals": totals,
        "total": total,
        "rows": summary_rows,
        "page": page,
        "page_size": page_size,
    }


def get_analytics_detail_rows(db: Session, **filters: Any) -> list[dict[str, Any]]:
    """Return filtered item-level rows for export."""
    rows = build_analytics_query(db, **filters).order_by(PublishedItem.id.desc()).all()
    return [
        {
            "month": row.month,
            "platform": row.platform,
            "item_id": row.item_id,
            "item_name": row.item_name,
            "shop_name": row.shop_name,
            "category_name": row.category_name,
            "brand_code": row.brand_code,
            "brand_name": row.brand_name,
            "model_code": row.model_code,
            "model_name": row.model_name,
            "sales_qty": row.sales_qty or 0,
            "corrected_sales_qty": row.corrected_sales_qty if row.corrected_sales_qty is not None else (row.sales_qty or 0),
            "sales_amount": float(row.sales_amount or 0),
            "price": float(row.price) if row.price is not None else None,
            "published_at": row.published_at,
        }
        for row in rows
    ]


def selected_detail_export_columns(fields: Optional[str] = None) -> list[tuple[str, str]]:
    """Return valid detail export columns, falling back to defaults when none are valid."""
    if not fields:
        return _DETAIL_EXPORT_COLUMNS

    selected = []
    seen = set()
    for field in fields.split(","):
        key = field.strip()
        if key in _DETAIL_EXPORT_LABELS and key not in seen:
            selected.append((key, _DETAIL_EXPORT_LABELS[key]))
            seen.add(key)

    return selected or _DETAIL_EXPORT_COLUMNS


def write_export_file(
    rows: list[dict[str, Any]],
    filename_prefix: str,
    columns: Optional[list[tuple[str, str]]] = None,
) -> tuple[str, str, Path]:
    """Write rows to an Excel file and return token, filename, and path."""
    export_dir = Path(settings.EXPORT_DIR)
    export_dir.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{filename_prefix}_{timestamp}.xlsx"
    filepath = export_dir / f"{token}_{filename}"
    if columns:
        df = pd.DataFrame(
            [{label: row.get(key) for key, label in columns} for row in rows],
            columns=[label for _, label in columns],
        )
    else:
        df = pd.DataFrame(rows)
    df.to_excel(str(filepath), index=False)
    return token, filename, filepath


def write_summary_export_file(rows: list[dict[str, Any]]) -> tuple[str, str, Path]:
    """Write analytics summary rows with Chinese export headers."""
    return write_export_file(rows, "analytics_summary", _SUMMARY_EXPORT_COLUMNS)


def write_detail_export_file(rows: list[dict[str, Any]], fields: Optional[str] = None) -> tuple[str, str, Path]:
    """Write analytics detail rows with selected Chinese export headers."""
    return write_export_file(rows, "analytics_detail", selected_detail_export_columns(fields))


def mark_export_job_done(db: Session, job: WorkbenchExportJob, token: str, filename: str) -> None:
    job.status = "done"
    job.progress = 100
    job.file_token = token
    job.filename = filename
    job.finished_at = datetime.utcnow()
    db.commit()


def mark_export_job_error(db: Session, job: WorkbenchExportJob, exc: Exception) -> None:
    db.rollback()
    job.status = "error"
    job.progress = 100
    job.error_msg = str(exc)
    job.finished_at = datetime.utcnow()
    db.commit()


def content_disposition(filename: str) -> str:
    return f"attachment; filename*=UTF-8''{quote(filename)}"
