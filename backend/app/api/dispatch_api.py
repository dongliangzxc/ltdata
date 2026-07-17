"""
数据分发 API
POST /run           — 对指定 file_id 执行分发
GET  /batches       — 列出所有分发批次
GET  /batches/{id}/stats — 某批次各品类行数明细
GET  /rules         — 规则列表（支持 platform / category_code 过滤）
POST /rules         — 新增规则
PUT  /rules/{id}    — 修改规则
DELETE /rules/{id}  — 删除规则
"""
from datetime import datetime
from decimal import Decimal
import io
from pathlib import Path
import re
import threading
from typing import Optional
from urllib.parse import quote
import uuid
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
import pandas as pd
from openpyxl import Workbook
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session
from app.core.config import settings
from app.models.database import get_db, SessionLocal
from app.models.schemas import (
    Category, DispatchRule, DispatchBatch, DispatchItem,
    DispatchRuleIn, DispatchRuleOut, DispatchBatchOut,
    RawDataRecord, UploadFileRecord, ColumnTemplate, WorkbenchExportJob,
)
from app.services.export_guards import (
    MAX_SYNC_EXPORT_ROWS,
    ensure_export_row_limit,
    reserve_async_export_capacity,
)

router = APIRouter(prefix="/api/dispatch", tags=["dispatch"])

DISPATCH_PAGE_SIZE = 2000
DISPATCH_EXPORT_DIR = Path(settings.EXPORT_DIR)
_dispatch_export_progress: dict[int, int] = {}


class DispatchExportParams(BaseModel):
    category_code: Optional[str] = None
    platform: Optional[str] = None
    month: Optional[int] = None
    months: list[int] = Field(default_factory=list)


def _is_valid_export_month(month: int) -> bool:
    return 100001 <= month <= 999912 and 1 <= month % 100 <= 12


def _normalize_export_months(month: int | None, months: list[int] | None) -> list[int]:
    values: list[int] = []
    if months:
        values.extend(int(value) for value in months)
    elif month is not None:
        values.append(int(month))

    normalized = sorted(set(values))
    if any(not _is_valid_export_month(value) for value in normalized):
        raise HTTPException(status_code=400, detail="月份格式应为 YYYYMM")
    return normalized


def _export_month_display(months: list[int] | None) -> str:
    values = months or []
    if not values:
        return "全部月份"
    if len(values) <= 3:
        return "、".join(str(value) for value in values)
    return f"{values[0]}等{len(values)}个月份"


FALLBACK_EXPORT_COLUMNS = [
    ("platform", "平台"),
    ("month", "月份"),
    ("week", "周"),
    ("category_lv0", "Lv0类目"),
    ("category_lv1", "Lv1类目"),
    ("category_lv2", "Lv2类目"),
    ("category_lv3", "Lv3类目"),
    ("category_lv4", "Lv4类目"),
    ("category_lv5", "Lv5类目"),
    ("item_id", "商品ID"),
    ("item_name", "商品名称"),
    ("item_image", "商品图片"),
    ("item_url", "商品链接"),
    ("ref_price", "参考价格"),
    ("brand_raw", "原品牌"),
    ("shop_name", "店铺名"),
    ("sales_qty", "销量"),
    ("sales_amount", "销售额"),
    ("price", "价格"),
    ("brand_std", "标准品牌"),
    ("model_std", "型号"),
]
TRACE_COLUMNS = ["_raw_data_id", "_source_filename"]


def _excel_value(value):
    if isinstance(value, Decimal):
        return float(value)
    return value


def _safe_sheet_name(name: str) -> str:
    cleaned = re.sub(r"[\[\]:*?/\\]", "_", name or "Sheet")[:31]
    return cleaned or "Sheet"


def _unique_sheet_name(name: str, used_names: set[str]) -> str:
    base = _safe_sheet_name(name)
    candidate = base
    index = 2
    while candidate in used_names:
        suffix = f"_{index}"
        candidate = f"{base[:31 - len(suffix)]}{suffix}"
        index += 1
    used_names.add(candidate)
    return candidate


def _template_columns(template: ColumnTemplate | None) -> list[tuple[str, str]]:
    if not template or not isinstance(template.mapping, dict):
        return []
    ignored = set(template.ignore_columns or [])
    return [
        (original_column, target_field)
        for original_column, target_field in template.mapping.items()
        if original_column not in ignored
    ]


def _build_export_row(raw: RawDataRecord, file_record: UploadFileRecord, template: ColumnTemplate | None) -> dict:
    extra = raw.extra_data if isinstance(raw.extra_data, dict) else {}
    row = {}
    included_extra_columns = set()
    for original_column, target_field in _template_columns(template):
        if target_field == "__ext__":
            row[original_column] = _excel_value(extra.get(original_column))
            included_extra_columns.add(original_column)
        elif hasattr(raw, target_field):
            row[original_column] = _excel_value(getattr(raw, target_field))
        else:
            row[original_column] = _excel_value(extra.get(original_column))
            included_extra_columns.add(original_column)

    for key, value in extra.items():
        if key not in included_extra_columns and key not in row:
            row[key] = _excel_value(value)

    row["_raw_data_id"] = raw.id
    row["_source_filename"] = file_record.filename
    return row


def _build_fallback_row(raw: RawDataRecord, file_record: UploadFileRecord) -> dict:
    row = {label: _excel_value(getattr(raw, field, None)) for field, label in FALLBACK_EXPORT_COLUMNS}
    extra = raw.extra_data if isinstance(raw.extra_data, dict) else {}
    for key, value in extra.items():
        if key not in row:
            row[key] = _excel_value(value)
    row["_raw_data_id"] = raw.id
    row["_source_filename"] = file_record.filename
    return row


def _write_dispatch_export(rows, output):
    if not rows:
        raise ValueError("没有可导出的分发数据")

    grouped_rows: dict[tuple[int | None, str], dict] = {}
    for _, raw, file_record, template in rows:
        template_id = template.id if template else None
        template_name = template.name if template else "无模板"
        key = (template_id, template_name)
        if key not in grouped_rows:
            grouped_rows[key] = {"template": template, "rows": []}
        if template:
            grouped_rows[key]["rows"].append(_build_export_row(raw, file_record, template))
        else:
            grouped_rows[key]["rows"].append(_build_fallback_row(raw, file_record))

    used_sheet_names: set[str] = set()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        for (template_id, template_name), group in grouped_rows.items():
            sheet_base = template_name if template_id is None else f"{template_name}_{template_id}"
            sheet_name = _unique_sheet_name(sheet_base, used_sheet_names)
            data = group["rows"]
            columns = list(data[0].keys()) if data else []
            for trace_column in TRACE_COLUMNS:
                if trace_column in columns:
                    columns.remove(trace_column)
                    columns.append(trace_column)
            pd.DataFrame(data, columns=columns).to_excel(writer, index=False, sheet_name=sheet_name)


def _build_dispatch_export_response(rows, filename: str):
    buf = io.BytesIO()
    try:
        _write_dispatch_export(rows, buf)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )


def _collect_dispatch_export_columns(query, total: int, page_size: int) -> dict[tuple[int | None, str], dict]:
    grouped_columns: dict[tuple[int | None, str], dict] = {}
    for offset in range(0, total, page_size):
        rows = query.limit(page_size).offset(offset).all()
        for _, raw, file_record, template in rows:
            template_id = template.id if template else None
            template_name = template.name if template else "无模板"
            key = (template_id, template_name)
            if key not in grouped_columns:
                grouped_columns[key] = {"template": template, "columns": []}
            row = _build_export_row(raw, file_record, template) if template else _build_fallback_row(raw, file_record)
            columns = grouped_columns[key]["columns"]
            for column in row.keys():
                if column not in columns:
                    columns.append(column)
    for group in grouped_columns.values():
        columns = group["columns"]
        for trace_column in TRACE_COLUMNS:
            if trace_column in columns:
                columns.remove(trace_column)
                columns.append(trace_column)
    return grouped_columns


def _write_dispatch_export_query(query, total: int, output, progress_callback=None, page_size: int = 5000):
    if total == 0:
        raise ValueError("没有可导出的分发数据")

    grouped_columns = _collect_dispatch_export_columns(query, total, page_size)
    used_sheet_names: set[str] = set()
    workbook = Workbook(write_only=True)
    for (template_id, template_name), group in grouped_columns.items():
        sheet_base = template_name if template_id is None else f"{template_name}_{template_id}"
        sheet_name = _unique_sheet_name(sheet_base, used_sheet_names)
        worksheet = workbook.create_sheet(title=sheet_name)
        columns = group["columns"]
        worksheet.append(columns)
        group["worksheet"] = worksheet

    processed = 0
    for offset in range(0, total, page_size):
        rows = query.limit(page_size).offset(offset).all()
        for _, raw, file_record, template in rows:
            template_id = template.id if template else None
            template_name = template.name if template else "无模板"
            key = (template_id, template_name)
            row = _build_export_row(raw, file_record, template) if template else _build_fallback_row(raw, file_record)
            group = grouped_columns[key]
            group["worksheet"].append([row.get(column) for column in group["columns"]])
            processed += 1
        if progress_callback:
            progress_callback(processed, total)

    workbook.save(output)


def _safe_filename_part(value: str | None, fallback: str) -> str:
    return re.sub(r"[^\w\-一-鿿]+", "_", value or fallback).strip("_") or fallback


def _dispatch_export_filename(category_code: str | None, platform: str | None, months: list[int] | None) -> str:
    return (
        "分发结果_"
        f"{_safe_filename_part(category_code, '全部品类')}_"
        f"{_safe_filename_part(platform, '全部平台')}_"
        f"{_safe_filename_part(_export_month_display(months), '全部月份')}.xlsx"
    )


def _latest_dispatch_export_query(db: Session, category_code: str | None, platform: str | None, months: list[int] | None = None):
    latest_batches = (
        db.query(
            DispatchBatch.file_id.label("file_id"),
            func.max(DispatchBatch.id).label("batch_id"),
        )
        .filter(DispatchBatch.status == "done", DispatchBatch.file_id.isnot(None))
        .group_by(DispatchBatch.file_id)
        .subquery()
    )
    query = (
        db.query(DispatchItem, RawDataRecord, UploadFileRecord, ColumnTemplate)
        .join(latest_batches, DispatchItem.batch_id == latest_batches.c.batch_id)
        .join(RawDataRecord, DispatchItem.raw_data_id == RawDataRecord.id)
        .join(UploadFileRecord, RawDataRecord.file_id == UploadFileRecord.id)
        .outerjoin(ColumnTemplate, UploadFileRecord.template_id == ColumnTemplate.id)
        .filter(DispatchItem.raw_data_id.isnot(None))
    )
    if category_code:
        query = query.filter(DispatchItem.category_code == category_code)
    if platform:
        query = query.filter(RawDataRecord.platform == platform)
    if months:
        query = query.filter(RawDataRecord.month.in_(months))
    return query


def _field_value(row: RawDataRecord, field: str) -> str:
    """从 raw_data 行取指定字段值，返回空字符串如果字段不存在"""
    field_map = {
        "category_lv0": row.category_lv0,
        "category_lv1": row.category_lv1,
        "category_lv2": row.category_lv2,
        "category_lv3": row.category_lv3,
        "category_lv4": row.category_lv4,
        "category_lv5": row.category_lv5,
        "item_name": row.item_name,
    }
    return (field_map.get(field) or "")


def _split_match_values(value: str | None) -> list[str]:
    if not value:
        return []
    parts = [value.strip()]
    parts.extend(part.strip() for part in re.split(r"[/,，、\n\r]+", value) if part.strip())
    return list(dict.fromkeys(parts))


def _split_item_name_keywords(keyword: str | None) -> list[str]:
    if not keyword:
        return []
    return [part.strip() for part in re.split(r"[,，、\n\r]+", keyword) if part.strip()]


def _rule_matches(row: RawDataRecord, rule: DispatchRule) -> bool:
    """判断一条规则是否命中该行"""
    val = _field_value(row, rule.field)
    match_values = _split_match_values(rule.value)
    if rule.match_type == "contains":
        main_match = any(match_value in val for match_value in match_values)
    elif rule.match_type == "equals":
        main_match = any(val == match_value for match_value in match_values)
    else:
        main_match = False

    if not main_match:
        return False

    item_name_keywords = _split_item_name_keywords(rule.item_name_keyword)
    if item_name_keywords:
        item_name = row.item_name or ""
        return any(keyword in item_name for keyword in item_name_keywords)

    return True


def _count_rule_matches_for_batch(db: Session, batch: DispatchBatch, rule_ids: list[int]) -> dict[int, int]:
    if not batch.file_id or not rule_ids:
        return {}
    rules = db.query(DispatchRule).filter(DispatchRule.id.in_(rule_ids)).all()
    if not rules:
        return {}

    counts = {rule.id: 0 for rule in rules}
    last_id = 0
    while True:
        rows = (
            db.query(
                RawDataRecord.id,
                RawDataRecord.category_lv0,
                RawDataRecord.category_lv1,
                RawDataRecord.category_lv2,
                RawDataRecord.category_lv3,
                RawDataRecord.category_lv4,
                RawDataRecord.category_lv5,
                RawDataRecord.item_name,
            )
            .filter(RawDataRecord.file_id == batch.file_id, RawDataRecord.id > last_id)
            .order_by(RawDataRecord.id)
            .limit(DISPATCH_PAGE_SIZE)
            .all()
        )
        if not rows:
            break
        for row in rows:
            for rule in rules:
                if _rule_matches(row, rule):
                    counts[rule.id] += 1
        last_id = rows[-1].id
    return counts


@router.post("/run", response_model=DispatchBatchOut)
def run_dispatch(payload: dict, db: Session = Depends(get_db)):
    """对指定 file_id 执行分发，返回新建的 batch"""
    file_id: int = payload.get("file_id")
    if not file_id:
        raise HTTPException(status_code=400, detail="file_id 不能为空")

    file_record = db.query(UploadFileRecord).filter(UploadFileRecord.id == file_id).first()
    if not file_record:
        raise HTTPException(status_code=404, detail="文件不存在")

    platform = (file_record.platform or "").lower()

    # 1. 创建 batch
    batch = DispatchBatch(file_id=file_id, status="running")
    db.add(batch)
    db.commit()
    db.refresh(batch)
    batch_id = batch.id

    try:
        total_rows = (
            db.query(func.count(RawDataRecord.id))
            .filter(RawDataRecord.file_id == file_id)
            .scalar()
            or 0
        )

        # 2. 取匹配平台（或 platform IS NULL）的 active 规则，按 priority ASC
        rules = (
            db.query(DispatchRule)
            .filter(
                DispatchRule.is_active == 1,
                (DispatchRule.platform == None) | (DispatchRule.platform == platform),
            )
            .order_by(DispatchRule.priority, DispatchRule.id)
            .all()
        )

        # 3. 分页读取 raw_data 少量字段并批量插入，避免大文件分发时占满内存
        dispatched_rows = 0
        unmatched_rows = 0
        last_id = 0

        while True:
            rows = (
                db.query(
                    RawDataRecord.id,
                    RawDataRecord.category_lv0,
                    RawDataRecord.category_lv1,
                    RawDataRecord.category_lv2,
                    RawDataRecord.category_lv3,
                    RawDataRecord.category_lv4,
                    RawDataRecord.category_lv5,
                    RawDataRecord.item_name,
                )
                .filter(RawDataRecord.file_id == file_id, RawDataRecord.id > last_id)
                .order_by(RawDataRecord.id)
                .limit(DISPATCH_PAGE_SIZE)
                .all()
            )
            if not rows:
                break

            insert_rows = []
            for row in rows:
                matched_by_category = {}
                for rule in rules:
                    if not _rule_matches(row, rule):
                        continue
                    if rule.category_code not in matched_by_category:
                        matched_by_category[rule.category_code] = rule

                if matched_by_category:
                    for category_code, rule in matched_by_category.items():
                        insert_rows.append({
                            "batch_id": batch_id,
                            "raw_data_id": row.id,
                            "category_code": category_code,
                            "matched_rule_id": rule.id,
                        })
                    dispatched_rows += len(matched_by_category)
                else:
                    unmatched_rows += 1

            if insert_rows:
                db.execute(DispatchItem.__table__.insert(), insert_rows)
                db.flush()
            last_id = rows[-1].id

        # 4. 更新 batch
        batch = db.query(DispatchBatch).filter(DispatchBatch.id == batch_id).one()
        batch.status = "done"
        batch.total_rows = total_rows
        batch.dispatched_rows = dispatched_rows
        batch.unmatched_rows = unmatched_rows
        batch.finished_at = datetime.utcnow()
        db.commit()
        db.refresh(batch)
        return batch
    except Exception:
        db.rollback()
        batch = db.query(DispatchBatch).filter(DispatchBatch.id == batch_id).one()
        batch.status = "error"
        batch.finished_at = datetime.utcnow()
        db.commit()
        raise


@router.get("/batches", response_model=list[DispatchBatchOut])
def list_batches(
    file_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    """列出所有分发批次，可按 file_id 过滤"""
    q = db.query(DispatchBatch)
    if file_id:
        q = q.filter(DispatchBatch.file_id == file_id)
    return q.order_by(DispatchBatch.created_at.desc()).all()


@router.get("/batches/{batch_id}/unmatched")
def get_batch_unmatched(
    batch_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    keyword: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """返回批次所属文件中未进入该批次 dispatch_items 的 raw_data 行"""
    batch = db.query(DispatchBatch).filter(DispatchBatch.id == batch_id).first()
    if not batch:
        raise HTTPException(status_code=404, detail="批次不存在")
    if batch.file_id is None:
        return {"total": 0, "page": page, "page_size": page_size, "items": []}

    dispatched_raw_ids = select(DispatchItem.raw_data_id).where(
        DispatchItem.batch_id == batch_id,
        DispatchItem.raw_data_id.isnot(None),
    )
    q = (
        db.query(RawDataRecord)
        .filter(RawDataRecord.file_id == batch.file_id)
        .filter(~RawDataRecord.id.in_(dispatched_raw_ids))
    )
    if keyword:
        like_keyword = f"%{keyword}%"
        q = q.filter(or_(
            RawDataRecord.item_id.ilike(like_keyword),
            RawDataRecord.item_name.ilike(like_keyword),
        ))

    total = q.count()
    rows = (
        q.order_by(RawDataRecord.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [
            {
                "id": row.id,
                "item_id": row.item_id,
                "item_name": row.item_name,
                "platform": row.platform,
                "month": row.month,
                "category_lv1": row.category_lv1,
                "category_lv2": row.category_lv2,
                "category_lv3": row.category_lv3,
                "brand_raw": row.brand_raw,
                "shop_name": row.shop_name,
                "price": float(row.price) if row.price is not None else None,
                "sales_qty": row.sales_qty,
                "sales_amount": float(row.sales_amount) if row.sales_amount is not None else None,
            }
            for row in rows
        ],
    }


@router.get("/batches/{batch_id}/stats")
def get_batch_stats(batch_id: int, db: Session = Depends(get_db)):
    """某批次各品类行数与规则命中明细"""
    batch = db.query(DispatchBatch).filter(DispatchBatch.id == batch_id).first()
    if not batch:
        raise HTTPException(status_code=404, detail="批次不存在")

    category_rows = (
        db.query(
            DispatchItem.category_code,
            Category.name.label("category_name"),
            func.count(DispatchItem.id).label("count"),
        )
        .outerjoin(Category, DispatchItem.category_code == Category.code)
        .filter(DispatchItem.batch_id == batch_id)
        .group_by(DispatchItem.category_code, Category.name)
        .order_by(func.count(DispatchItem.id).desc(), DispatchItem.category_code)
        .all()
    )

    platform_rows = (
        db.query(
            DispatchItem.category_code,
            RawDataRecord.platform,
            func.count(DispatchItem.id).label("count"),
        )
        .outerjoin(RawDataRecord, DispatchItem.raw_data_id == RawDataRecord.id)
        .filter(DispatchItem.batch_id == batch_id)
        .group_by(DispatchItem.category_code, RawDataRecord.platform)
        .order_by(DispatchItem.category_code, RawDataRecord.platform)
        .all()
    )
    platforms_by_category: dict[str, list[dict]] = {}
    for row in platform_rows:
        platforms_by_category.setdefault(row.category_code, []).append({
            "platform": row.platform,
            "count": row.count,
        })

    rule_stats_subq = (
        db.query(
            DispatchItem.matched_rule_id.label("rule_id"),
            func.count(DispatchItem.id).label("count"),
            func.min(DispatchItem.category_code).label("fallback_category_code"),
        )
        .filter(DispatchItem.batch_id == batch_id, DispatchItem.matched_rule_id.isnot(None))
        .group_by(DispatchItem.matched_rule_id)
        .subquery()
    )
    rule_category_code = func.coalesce(
        DispatchRule.category_code,
        rule_stats_subq.c.fallback_category_code,
    ).label("category_code")
    rule_rows = (
        db.query(
            rule_stats_subq.c.rule_id,
            rule_category_code,
            Category.name.label("category_name"),
            DispatchRule.field,
            DispatchRule.match_type,
            DispatchRule.value,
            DispatchRule.item_name_keyword,
            DispatchRule.platform,
            DispatchRule.priority,
            DispatchRule.is_active,
            rule_stats_subq.c.count.label("assigned_count"),
        )
        .select_from(rule_stats_subq)
        .outerjoin(DispatchRule, rule_stats_subq.c.rule_id == DispatchRule.id)
        .outerjoin(Category, rule_category_code == Category.code)
        .order_by(rule_stats_subq.c.count.desc(), DispatchRule.priority, rule_stats_subq.c.rule_id)
        .all()
    )
    return {
        "batch_id": batch_id,
        "total_rows": batch.total_rows,
        "dispatched_rows": batch.dispatched_rows,
        "unmatched_rows": batch.unmatched_rows,
        "categories": [
            {
                "category_code": row.category_code,
                "category_name": row.category_name,
                "count": row.count,
                "platforms": platforms_by_category.get(row.category_code, []),
            }
            for row in category_rows
        ],
        "rules": [
            {
                "rule_id": row.rule_id,
                "category_code": row.category_code,
                "category_name": row.category_name,
                "field": row.field,
                "match_type": row.match_type,
                "value": row.value,
                "item_name_keyword": row.item_name_keyword,
                "platform": row.platform,
                "priority": row.priority,
                "is_active": row.is_active,
                "count": row.assigned_count,
                "assigned_count": row.assigned_count,
            }
            for row in rule_rows
        ],
    }


@router.get("/batches/{batch_id}/export")
def export_batch_raw_data(
    batch_id: int,
    category_code: str = Query(..., min_length=1),
    platform: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    batch = db.query(DispatchBatch).filter(DispatchBatch.id == batch_id).first()
    if not batch:
        raise HTTPException(status_code=404, detail="批次不存在")
    if batch.status != "done":
        raise HTTPException(status_code=400, detail="批次尚未完成，不能导出")

    query = (
        db.query(DispatchItem, RawDataRecord, UploadFileRecord, ColumnTemplate)
        .join(RawDataRecord, DispatchItem.raw_data_id == RawDataRecord.id)
        .join(UploadFileRecord, RawDataRecord.file_id == UploadFileRecord.id)
        .outerjoin(ColumnTemplate, UploadFileRecord.template_id == ColumnTemplate.id)
        .filter(
            DispatchItem.batch_id == batch_id,
            DispatchItem.category_code == category_code,
            DispatchItem.raw_data_id.isnot(None),
        )
    )
    if platform:
        query = query.filter(RawDataRecord.platform == platform)
    total = query.count()
    ensure_export_row_limit(total, max_rows=MAX_SYNC_EXPORT_ROWS, label="分发批次导出")

    rows = query.order_by(UploadFileRecord.template_id, RawDataRecord.id).all()
    filename = (
        f"已分发原始数据_批次{batch_id}_"
        f"{_safe_filename_part(category_code, 'category')}_"
        f"{_safe_filename_part(platform, 'all')}.xlsx"
    )
    return _build_dispatch_export_response(rows, filename)


def _run_dispatch_export_thread(job_id: int, params: dict):
    db = SessionLocal()
    try:
        job = db.query(WorkbenchExportJob).filter(WorkbenchExportJob.id == job_id).first()
        if not job:
            return
        job.status = "running"
        job.progress = 5
        db.commit()
        _dispatch_export_progress[job_id] = 5

        category_code = params.get("category_code")
        platform = params.get("platform")
        months = _normalize_export_months(params.get("month"), params.get("months") or [])
        query = _latest_dispatch_export_query(db, category_code, platform, months).order_by(
            UploadFileRecord.template_id,
            RawDataRecord.month,
            RawDataRecord.id,
        )
        total = query.count()
        if total == 0:
            job.status = "error"
            job.error_msg = "没有可导出的分发数据"
            job.finished_at = datetime.utcnow()
            db.commit()
            return
        _dispatch_export_progress[job_id] = 10
        job.progress = 10
        db.commit()

        DISPATCH_EXPORT_DIR.mkdir(parents=True, exist_ok=True)
        token = uuid.uuid4().hex
        filename = _dispatch_export_filename(category_code, platform, months)
        filepath = DISPATCH_EXPORT_DIR / f"{token}_{filename}"

        def update_progress(processed: int, total_rows: int):
            progress = 10 + int(85 * processed / max(total_rows, 1))
            _dispatch_export_progress[job_id] = progress
            job.progress = progress
            db.commit()

        _write_dispatch_export_query(query, total, str(filepath), progress_callback=update_progress, page_size=DISPATCH_PAGE_SIZE)

        job.status = "done"
        job.progress = 100
        job.file_token = token
        job.filename = filename
        job.finished_at = datetime.utcnow()
        db.commit()
        _dispatch_export_progress[job_id] = 100
    except Exception as exc:
        try:
            job = db.query(WorkbenchExportJob).filter(WorkbenchExportJob.id == job_id).first()
            if job:
                job.status = "error"
                job.error_msg = str(exc)
                job.finished_at = datetime.utcnow()
                db.commit()
        except Exception:
            pass
    finally:
        _dispatch_export_progress.pop(job_id, None)
        db.close()


@router.post("/export", status_code=202)
def create_dispatch_export_job(payload: DispatchExportParams, db: Session = Depends(get_db)):
    category_code = payload.category_code.strip() if payload.category_code else None
    platform = payload.platform.strip() if payload.platform else None
    months = _normalize_export_months(payload.month, payload.months)
    primary_month = months[0] if months else None
    if not category_code and not platform and not months:
        raise HTTPException(status_code=400, detail="请选择品类、平台或月份后再导出")
    has_export_data = _latest_dispatch_export_query(db, category_code, platform, months).limit(1).first()
    if not has_export_data:
        raise HTTPException(status_code=400, detail="当前筛选条件无可导出数据，请调整月份、品类或平台")

    with reserve_async_export_capacity(db):
        job = WorkbenchExportJob(
            status="pending",
            progress=0,
            category_code=category_code,
            platform=platform,
            month=primary_month,
            params={"month": primary_month, "months": months},
        )
        db.add(job)
        db.commit()
        db.refresh(job)

    thread = threading.Thread(
        target=_run_dispatch_export_thread,
        args=(job.id, {"category_code": category_code, "platform": platform, "month": primary_month, "months": months}),
        daemon=True,
    )
    thread.start()
    return {"job_id": job.id, "status": "pending"}


def _dispatch_export_job_out(job: WorkbenchExportJob) -> dict:
    progress = _dispatch_export_progress.get(job.id, job.progress)
    download_url = (
        f"/api/dispatch/export/download/{job.file_token}"
        if job.status == "done" and job.file_token
        else None
    )
    params = job.params or {}
    months = _normalize_export_months(job.month, params.get("months") or [])
    return {
        "job_id": job.id,
        "status": job.status,
        "progress": progress,
        "category_code": job.category_code,
        "platform": job.platform,
        "month": job.month,
        "months": months,
        "filename": job.filename,
        "download_url": download_url,
        "error_msg": job.error_msg,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
    }


def _dispatch_export_file_path(job: WorkbenchExportJob) -> Path | None:
    if not job.file_token or not job.filename:
        return None
    return DISPATCH_EXPORT_DIR / f"{job.file_token}_{job.filename}"


@router.get("/export/jobs")
def list_dispatch_export_jobs(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
):
    query = db.query(WorkbenchExportJob)
    total = query.count()
    jobs = (
        query.order_by(WorkbenchExportJob.created_at.desc(), WorkbenchExportJob.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {"total": total, "items": [_dispatch_export_job_out(job) for job in jobs]}


@router.delete("/export/jobs/{job_id}")
def delete_dispatch_export_job(job_id: int, db: Session = Depends(get_db)):
    job = db.query(WorkbenchExportJob).filter(WorkbenchExportJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="导出任务不存在")

    file_path = _dispatch_export_file_path(job)
    if file_path and file_path.exists():
        try:
            file_path.unlink()
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"删除导出文件失败：{exc}") from exc

    _dispatch_export_progress.pop(job_id, None)
    db.delete(job)
    db.commit()
    return {"ok": True}


@router.get("/export/jobs/{job_id}")
def get_dispatch_export_job(job_id: int, db: Session = Depends(get_db)):
    job = db.query(WorkbenchExportJob).filter(WorkbenchExportJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="导出任务不存在")
    return _dispatch_export_job_out(job)


@router.get("/export/download/{token}")
def download_dispatch_export(token: str, db: Session = Depends(get_db)):
    job = db.query(WorkbenchExportJob).filter(WorkbenchExportJob.file_token == token).first()
    if not job or not job.filename:
        raise HTTPException(status_code=404, detail="文件不存在或已过期")
    file_path = DISPATCH_EXPORT_DIR / f"{token}_{job.filename}"
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="文件已被清理，请重新导出")
    return FileResponse(
        path=str(file_path),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(job.filename)}"},
    )


@router.get("/rules", response_model=list[DispatchRuleOut])
def list_rules(
    platform: Optional[str] = Query(None),
    category_code: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    q = db.query(DispatchRule)
    if platform:
        q = q.filter(DispatchRule.platform == platform)
    if category_code:
        q = q.filter(DispatchRule.category_code == category_code)
    return q.order_by(DispatchRule.priority, DispatchRule.id).all()


@router.post("/rules", response_model=DispatchRuleOut)
def create_rule(body: DispatchRuleIn, db: Session = Depends(get_db)):
    rule = DispatchRule(**body.model_dump())
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


@router.put("/rules/{rule_id}", response_model=DispatchRuleOut)
def update_rule(rule_id: int, body: DispatchRuleIn, db: Session = Depends(get_db)):
    rule = db.query(DispatchRule).filter(DispatchRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="规则不存在")
    for k, v in body.model_dump().items():
        setattr(rule, k, v)
    db.commit()
    db.refresh(rule)
    return rule


@router.delete("/rules/{rule_id}")
def delete_rule(rule_id: int, db: Session = Depends(get_db)):
    rule = db.query(DispatchRule).filter(DispatchRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="规则不存在")
    db.delete(rule)
    db.commit()
    return {"message": "已删除"}
