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
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session
from app.core.auth_deps import get_current_user
from app.core.config import settings
from app.core.permissions import visible_category_codes
from app.utils.time_utils import format_beijing_datetime
from app.models.database import get_db, SessionLocal
from app.models.schemas import (
    Category, CleanJobItemRecord, DispatchRule, DispatchBatch, DispatchItem,
    DispatchRuleIn, DispatchRuleOut, DispatchBatchOut,
    DispatchRedispatchIn, DispatchRedispatchJob, DispatchRedispatchJobItem,
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


def _category_scope_codes(db: Session, current_user) -> list[str] | None:
    if getattr(current_user, "is_admin", 0) == 1:
        return None
    all_codes = [code for code, in db.query(Category.code).order_by(Category.sort_order, Category.code).all()]
    if all_codes:
        return visible_category_codes(current_user, all_codes)
    return None

def _ensure_category_in_scope(db: Session, current_user, category_code: str) -> None:
    scoped_codes = _category_scope_codes(db, current_user)
    if scoped_codes is not None and category_code not in scoped_codes:
        raise HTTPException(status_code=403, detail="无权限访问该品类")


def _apply_category_scope(query, column, scoped_codes: list[str] | None):
    if scoped_codes is None:
        return query
    return query.filter(column.in_(scoped_codes))


def _job_matches_category_scope(job: WorkbenchExportJob, scoped_codes: list[str] | None) -> bool:
    if scoped_codes is None:
        return True
    allowed = set(scoped_codes)
    if job.category_code:
        return job.category_code in allowed
    params = job.params if isinstance(job.params, dict) else {}
    job_codes = params.get("allowed_category_codes")
    return isinstance(job_codes, list) and bool(job_codes) and set(job_codes).issubset(allowed)


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


def _latest_dispatch_export_query(
    db: Session,
    category_code: str | None,
    platform: str | None,
    months: list[int] | None = None,
    allowed_category_codes: list[str] | None = None,
):
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
    elif allowed_category_codes is not None:
        query = query.filter(DispatchItem.category_code.in_(allowed_category_codes))
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


def _execute_category_dispatch(db: Session, file_id: int, category_code: str | None) -> DispatchBatch:
    """对指定 file_id 执行品类局部分发，返回新建的 batch。

    category_code 为空时执行全量分发；非空时只跑该品类规则，
    并把该文件最新已完成批次中其它品类的分发结果复制进新批次。
    供 run_dispatch 与批量补分发后台线程共用。
    """
    file_record = db.query(UploadFileRecord).filter(UploadFileRecord.id == file_id).first()
    if not file_record:
        raise HTTPException(status_code=404, detail="文件不存在")

    platform = (file_record.platform or "").lower()
    rule_filters = [
        DispatchRule.is_active == 1,
        (DispatchRule.platform.is_(None)) | (DispatchRule.platform == platform),
    ]
    if category_code:
        rule_filters.append(DispatchRule.category_code == category_code)

    # 取匹配平台（或 platform IS NULL）的 active 规则，按 priority ASC
    rules = (
        db.query(DispatchRule)
        .filter(*rule_filters)
        .order_by(DispatchRule.priority, DispatchRule.id)
        .all()
    )
    if category_code and not rules:
        raise HTTPException(status_code=400, detail="该品类没有可用分发规则")

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

        copied_rows = 0
        if category_code:
            latest_non_target_items = (
                db.query(
                    DispatchItem.raw_data_id.label("raw_data_id"),
                    DispatchItem.category_code.label("category_code"),
                    func.max(DispatchItem.id).label("dispatch_item_id"),
                )
                .join(DispatchBatch, DispatchItem.batch_id == DispatchBatch.id)
                .filter(
                    DispatchBatch.file_id == file_id,
                    DispatchBatch.status == "done",
                    DispatchBatch.id != batch_id,
                    DispatchItem.category_code != category_code,
                )
                .group_by(DispatchItem.raw_data_id, DispatchItem.category_code)
                .subquery()
            )
            previous_items = (
                db.query(DispatchItem.raw_data_id, DispatchItem.category_code, DispatchItem.matched_rule_id)
                .join(latest_non_target_items, DispatchItem.id == latest_non_target_items.c.dispatch_item_id)
                .all()
            )
            if previous_items:
                db.execute(
                    DispatchItem.__table__.insert(),
                    [
                        {
                            "batch_id": batch_id,
                            "raw_data_id": item.raw_data_id,
                            "category_code": item.category_code,
                            "matched_rule_id": item.matched_rule_id,
                        }
                        for item in previous_items
                    ],
                )
                copied_rows = len(previous_items)
                db.flush()

        # 3. 分页读取 raw_data 少量字段并批量插入，避免大文件分发时占满内存
        dispatched_rows = copied_rows
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
                    for matched_category_code, rule in matched_by_category.items():
                        insert_rows.append({
                            "batch_id": batch_id,
                            "raw_data_id": row.id,
                            "category_code": matched_category_code,
                            "matched_rule_id": rule.id,
                        })
                    dispatched_rows += len(matched_by_category)
                elif not category_code:
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
        batch.unmatched_rows = max(total_rows - dispatched_rows, 0) if category_code else unmatched_rows
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


@router.post("/run", response_model=DispatchBatchOut)
def run_dispatch(payload: dict, db: Session = Depends(get_db)):
    """对指定 file_id 执行分发，返回新建的 batch"""
    file_id: int = payload.get("file_id")
    category_code = (payload.get("category_code") or "").strip() or None
    if not file_id:
        raise HTTPException(status_code=400, detail="file_id 不能为空")
    return _execute_category_dispatch(db, file_id, category_code)


@router.get("/batches", response_model=list[DispatchBatchOut])
def list_batches(
    file_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """列出所有分发批次，可按 file_id 过滤"""
    q = db.query(DispatchBatch)
    scoped_codes = _category_scope_codes(db, current_user)
    if scoped_codes is not None:
        q = q.filter(DispatchBatch.items.any(DispatchItem.category_code.in_(scoped_codes)))
    if file_id:
        q = q.filter(DispatchBatch.file_id == file_id)
    return q.order_by(DispatchBatch.created_at.desc()).all()


# ─── 批量补分发（按批次多选，针对目标品类异步批量重分发） ───────────

def _latest_done_batch_id(db: Session, file_id: int) -> int | None:
    return db.query(func.max(DispatchBatch.id)).filter(
        DispatchBatch.file_id == file_id,
        DispatchBatch.status == "done",
    ).scalar()


def _file_has_category(db: Session, file_id: int, category_code: str) -> bool:
    latest_batch_id = _latest_done_batch_id(db, file_id)
    if not latest_batch_id:
        return False
    return db.query(DispatchItem.id).filter(
        DispatchItem.batch_id == latest_batch_id,
        DispatchItem.category_code == category_code,
    ).first() is not None


def _redispatch_job_out(job: DispatchRedispatchJob, category_name: str | None = None) -> dict:
    return {
        "id": job.id,
        "category_code": job.category_code,
        "category_name": category_name,
        "skip_contained": job.skip_contained,
        "status": job.status,
        "total_batches": job.total_batches,
        "done_batches": job.done_batches,
        "success_batches": job.success_batches,
        "failed_batches": job.failed_batches,
        "skipped_batches": job.skipped_batches,
        "error_msg": job.error_msg,
        "created_by": job.created_by,
        "created_at": format_beijing_datetime(job.created_at) if job.created_at else None,
        "finished_at": format_beijing_datetime(job.finished_at) if job.finished_at else None,
    }


def _redispatch_item_out(item: DispatchRedispatchJobItem, db: Session, category_code: str) -> dict:
    filename = None
    batch = db.get(DispatchBatch, item.batch_id)
    if batch is not None and batch.file is not None:
        filename = batch.file.filename
    category_count = None
    if item.new_batch_id:
        category_count = (
            db.query(func.count(DispatchItem.id))
            .filter(
                DispatchItem.batch_id == item.new_batch_id,
                DispatchItem.category_code == category_code,
            )
            .scalar()
            or 0
        )
    return {
        "id": item.id,
        "batch_id": item.batch_id,
        "file_id": item.file_id,
        "filename": filename,
        "status": item.status,
        "new_batch_id": item.new_batch_id,
        "category_count": category_count,
        "dispatched_rows": item.dispatched_rows,
        "unmatched_rows": item.unmatched_rows,
        "error_msg": item.error_msg,
        "finished_at": format_beijing_datetime(item.finished_at) if item.finished_at else None,
    }


def _run_redispatch_thread(job_id: int):
    db = SessionLocal()
    try:
        job = db.query(DispatchRedispatchJob).filter(DispatchRedispatchJob.id == job_id).first()
        if not job:
            return
        job.status = "running"
        db.commit()

        items = (
            db.query(DispatchRedispatchJobItem)
            .filter(DispatchRedispatchJobItem.job_id == job_id)
            .order_by(DispatchRedispatchJobItem.id)
            .all()
        )
        done = 0
        success = 0
        failed = 0
        skipped = 0
        for item in items:
            item.status = "running"
            db.commit()
            try:
                if not item.file_id:
                    raise HTTPException(status_code=400, detail="选中批次无关联文件，无法补分发")
                if job.skip_contained and _file_has_category(db, item.file_id, job.category_code):
                    item.status = "skipped"
                    item.error_msg = "该文件最新已完成批次已包含目标品类，已跳过"
                    skipped += 1
                else:
                    batch = _execute_category_dispatch(db, item.file_id, job.category_code)
                    item.new_batch_id = batch.id
                    item.dispatched_rows = batch.dispatched_rows
                    item.unmatched_rows = batch.unmatched_rows
                    item.status = "done"
                    success += 1
            except Exception as exc:
                item.status = "error"
                item.error_msg = str(exc) or "补分发失败"
                failed += 1
            item.finished_at = datetime.utcnow()
            done += 1
            job.done_batches = done
            job.success_batches = success
            job.failed_batches = failed
            job.skipped_batches = skipped
            db.commit()
        job.status = "done"
        job.finished_at = datetime.utcnow()
        db.commit()
    except Exception as exc:
        try:
            job = db.query(DispatchRedispatchJob).filter(DispatchRedispatchJob.id == job_id).first()
            if job:
                job.status = "error"
                job.error_msg = str(exc)
                job.finished_at = datetime.utcnow()
                db.commit()
        except Exception:
            pass
    finally:
        db.close()


@router.post("/redispatch", status_code=202)
def create_redispatch_job(
    payload: DispatchRedispatchIn,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """创建批量补分发任务：对选中批次对应文件按目标品类重新分发，异步后台执行。"""
    category_code = (payload.category_code or "").strip()
    if not payload.batch_ids:
        raise HTTPException(status_code=400, detail="请至少选择一个分发批次")
    if not category_code:
        raise HTTPException(status_code=400, detail="请选择目标品类")
    _ensure_category_in_scope(db, current_user, category_code)

    batches = db.query(DispatchBatch).filter(DispatchBatch.id.in_(payload.batch_ids)).all()
    found_ids = {b.id for b in batches}
    missing = [bid for bid in payload.batch_ids if bid not in found_ids]
    if missing:
        raise HTTPException(status_code=404, detail=f"分发批次不存在: {missing}")
    not_done = [b.id for b in batches if b.status != "done"]
    if not_done:
        raise HTTPException(status_code=400, detail=f"以下批次尚未完成分发: {not_done}")

    platforms: set[str] = set()
    for b in batches:
        if b.file is not None and b.file.platform:
            platforms.add(b.file.platform.lower())
    rule_filters = [DispatchRule.is_active == 1, DispatchRule.category_code == category_code]
    if platforms:
        rule_filters.append(or_(DispatchRule.platform.is_(None), DispatchRule.platform.in_(list(platforms))))
    if not db.query(DispatchRule.id).filter(*rule_filters).first():
        raise HTTPException(status_code=400, detail="该品类没有可用分发规则")

    job = DispatchRedispatchJob(
        category_code=category_code,
        skip_contained=1 if payload.skip_contained else 0,
        status="pending",
        total_batches=len(batches),
        created_by=_current_downloader_name(current_user),
    )
    db.add(job)
    db.flush()
    for b in batches:
        db.add(DispatchRedispatchJobItem(
            job_id=job.id,
            batch_id=b.id,
            file_id=b.file_id,
            status="pending",
        ))
    db.commit()
    db.refresh(job)

    thread = threading.Thread(target=_run_redispatch_thread, args=(job.id,), daemon=True)
    thread.start()
    return {"job_id": job.id, "status": "pending"}


@router.get("/redispatch/jobs")
def list_redispatch_jobs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    scoped_codes = _category_scope_codes(db, current_user)
    query = db.query(DispatchRedispatchJob).order_by(
        DispatchRedispatchJob.created_at.desc(),
        DispatchRedispatchJob.id.desc(),
    )
    visible = []
    for job in query.all():
        if scoped_codes is not None and job.category_code not in scoped_codes:
            continue
        category_name = db.query(Category.name).filter(Category.code == job.category_code).scalar()
        visible.append(_redispatch_job_out(job, category_name))
    total = len(visible)
    start = (page - 1) * page_size
    return {"total": total, "items": visible[start:start + page_size]}


@router.get("/redispatch/jobs/{job_id}")
def get_redispatch_job(job_id: int, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    job = db.query(DispatchRedispatchJob).filter(DispatchRedispatchJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="补分发任务不存在")
    scoped_codes = _category_scope_codes(db, current_user)
    if scoped_codes is not None and job.category_code not in scoped_codes:
        raise HTTPException(status_code=403, detail="无权限访问该品类")
    category_name = db.query(Category.name).filter(Category.code == job.category_code).scalar()
    out = _redispatch_job_out(job, category_name)
    items = (
        db.query(DispatchRedispatchJobItem)
        .filter(DispatchRedispatchJobItem.job_id == job_id)
        .order_by(DispatchRedispatchJobItem.id)
        .all()
    )
    out["items"] = [_redispatch_item_out(item, db, job.category_code) for item in items]
    return out


@router.post("/batches/{batch_id}/categories/{category_code}/enqueue-clean")
def enqueue_dispatch_category_for_clean(batch_id: int, category_code: str, db: Session = Depends(get_db)):
    """将当前批次当前品类暴露给待入清洗队列，不生成新的分发批次。"""
    batch = db.query(DispatchBatch).filter(DispatchBatch.id == batch_id).first()
    if not batch:
        raise HTTPException(status_code=404, detail="分发批次不存在")
    if batch.status != "done":
        raise HTTPException(status_code=400, detail="只能处理已完成的分发批次")

    counts = (
        db.query(
            func.count(func.distinct(DispatchItem.raw_data_id)).label("dispatch_count"),
            func.count(func.distinct(case((CleanJobItemRecord.id.is_(None), DispatchItem.raw_data_id)))).label("pending_count"),
            func.count(func.distinct(case((CleanJobItemRecord.id.isnot(None), DispatchItem.raw_data_id)))).label("queued_count"),
        )
        .outerjoin(
            CleanJobItemRecord,
            (CleanJobItemRecord.raw_data_id == DispatchItem.raw_data_id)
            & (CleanJobItemRecord.category_code == DispatchItem.category_code),
        )
        .filter(
            DispatchItem.batch_id == batch_id,
            DispatchItem.category_code == category_code,
        )
        .one()
    )
    return {
        "dispatch_batch_id": batch_id,
        "category_code": category_code,
        "dispatch_count": int(counts.dispatch_count or 0),
        "pending_count": int(counts.pending_count or 0),
        "queued_count": int(counts.queued_count or 0),
    }


@router.get("/batches/{batch_id}/unmatched")
def get_batch_unmatched(
    batch_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    keyword: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """返回批次所属文件中未进入该批次 dispatch_items 的 raw_data 行"""
    batch = db.query(DispatchBatch).filter(DispatchBatch.id == batch_id).first()
    if not batch:
        raise HTTPException(status_code=404, detail="批次不存在")
    scoped_codes = _category_scope_codes(db, current_user)
    if scoped_codes is not None and not db.query(DispatchItem.id).filter(
        DispatchItem.batch_id == batch_id,
        DispatchItem.category_code.in_(scoped_codes),
    ).first():
        raise HTTPException(status_code=403, detail="无权限访问该品类")
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
def get_batch_stats(batch_id: int, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    """某批次各品类行数与规则命中明细"""
    batch = db.query(DispatchBatch).filter(DispatchBatch.id == batch_id).first()
    if not batch:
        raise HTTPException(status_code=404, detail="批次不存在")

    scoped_codes = _category_scope_codes(db, current_user)

    category_query = (
        db.query(
            DispatchItem.category_code,
            Category.name.label("category_name"),
            func.count(DispatchItem.id).label("count"),
        )
        .outerjoin(Category, DispatchItem.category_code == Category.code)
        .filter(DispatchItem.batch_id == batch_id)
    )
    category_rows = (
        _apply_category_scope(category_query, DispatchItem.category_code, scoped_codes)
        .group_by(DispatchItem.category_code, Category.name)
        .order_by(func.count(DispatchItem.id).desc(), DispatchItem.category_code)
        .all()
    )

    platform_query = (
        db.query(
            DispatchItem.category_code,
            RawDataRecord.platform,
            func.count(DispatchItem.id).label("count"),
        )
        .outerjoin(RawDataRecord, DispatchItem.raw_data_id == RawDataRecord.id)
        .filter(DispatchItem.batch_id == batch_id)
    )
    platform_rows = (
        _apply_category_scope(platform_query, DispatchItem.category_code, scoped_codes)
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
        "dispatched_rows": sum(int(row.count or 0) for row in category_rows) if scoped_codes is not None else batch.dispatched_rows,
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
    current_user=Depends(get_current_user),
):
    batch = db.query(DispatchBatch).filter(DispatchBatch.id == batch_id).first()
    if not batch:
        raise HTTPException(status_code=404, detail="批次不存在")
    if batch.status != "done":
        raise HTTPException(status_code=400, detail="批次尚未完成，不能导出")
    _ensure_category_in_scope(db, current_user, category_code)

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
def create_dispatch_export_job(payload: DispatchExportParams, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    category_code = payload.category_code.strip() if payload.category_code else None
    platform = payload.platform.strip() if payload.platform else None
    months = _normalize_export_months(payload.month, payload.months)
    primary_month = months[0] if months else None
    if not category_code and not platform and not months:
        raise HTTPException(status_code=400, detail="请选择品类、平台或月份后再导出")
    scoped_codes = _category_scope_codes(db, current_user)
    if category_code:
        _ensure_category_in_scope(db, current_user, category_code)
    elif scoped_codes is not None and not scoped_codes:
        raise HTTPException(status_code=403, detail="无权限访问该品类")
    has_export_data = _latest_dispatch_export_query(db, category_code, platform, months, scoped_codes).limit(1).first()
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
    downloaders = job.downloaders if isinstance(job.downloaders, list) else []
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
        "created_at": format_beijing_datetime(job.created_at) if job.created_at else None,
        "finished_at": format_beijing_datetime(job.finished_at) if job.finished_at else None,
        "downloaders": downloaders,
        "last_download_at": format_beijing_datetime(job.last_download_at) if job.last_download_at else None,
    }


def _current_downloader_name(current_user) -> str:
    name = (getattr(current_user, "name", None) or "").strip()
    if name:
        return name
    return getattr(current_user, "username", "未知用户") or "未知用户"


def _record_export_downloader(job: WorkbenchExportJob, current_user) -> None:
    downloader_name = _current_downloader_name(current_user)
    downloaders = []
    existing_downloaders = job.downloaders if isinstance(job.downloaders, list) else []
    for name in existing_downloaders:
        if name not in downloaders:
            downloaders.append(name)
    if downloader_name not in downloaders:
        downloaders.append(downloader_name)
    job.downloaders = downloaders
    job.last_download_at = datetime.utcnow()


def _dispatch_export_file_path(job: WorkbenchExportJob) -> Path | None:
    if not job.file_token or not job.filename:
        return None
    return DISPATCH_EXPORT_DIR / f"{job.file_token}_{job.filename}"


@router.get("/export/jobs")
def list_dispatch_export_jobs(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    scoped_codes = _category_scope_codes(db, current_user)
    query = db.query(WorkbenchExportJob).order_by(WorkbenchExportJob.created_at.desc(), WorkbenchExportJob.id.desc())
    visible_jobs = [job for job in query.all() if _job_matches_category_scope(job, scoped_codes)]
    total = len(visible_jobs)
    start = (page - 1) * page_size
    jobs = visible_jobs[start:start + page_size]
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
def get_dispatch_export_job(job_id: int, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    job = db.query(WorkbenchExportJob).filter(WorkbenchExportJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="导出任务不存在")
    if not _job_matches_category_scope(job, _category_scope_codes(db, current_user)):
        raise HTTPException(status_code=403, detail="无权限访问该品类")
    return _dispatch_export_job_out(job)


@router.get("/export/download/{token}")
def download_dispatch_export(token: str, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    job = db.query(WorkbenchExportJob).filter(WorkbenchExportJob.file_token == token).first()
    if not job or not job.filename:
        raise HTTPException(status_code=404, detail="文件不存在或已过期")
    if not _job_matches_category_scope(job, _category_scope_codes(db, current_user)):
        raise HTTPException(status_code=403, detail="无权限访问该品类")
    file_path = DISPATCH_EXPORT_DIR / f"{token}_{job.filename}"
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="文件已被清理，请重新导出")
    _record_export_downloader(job, current_user)
    db.commit()
    db.refresh(job)
    return FileResponse(
        path=str(file_path),
        filename=job.filename,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(job.filename)}"},
    )


@router.get("/rules", response_model=list[DispatchRuleOut])
def list_rules(
    platform: Optional[str] = Query(None),
    category_code: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    q = db.query(DispatchRule)
    scoped_codes = _category_scope_codes(db, current_user)
    q = _apply_category_scope(q, DispatchRule.category_code, scoped_codes)
    if platform:
        q = q.filter(DispatchRule.platform == platform)
    if category_code:
        _ensure_category_in_scope(db, current_user, category_code)
        q = q.filter(DispatchRule.category_code == category_code)
    return q.order_by(DispatchRule.priority, DispatchRule.id).all()


@router.post("/rules", response_model=DispatchRuleOut)
def create_rule(body: DispatchRuleIn, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    _ensure_category_in_scope(db, current_user, body.category_code)
    rule = DispatchRule(**body.model_dump())
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


@router.put("/rules/{rule_id}", response_model=DispatchRuleOut)
def update_rule(rule_id: int, body: DispatchRuleIn, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    rule = db.query(DispatchRule).filter(DispatchRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="规则不存在")
    _ensure_category_in_scope(db, current_user, rule.category_code)
    _ensure_category_in_scope(db, current_user, body.category_code)
    for k, v in body.model_dump().items():
        setattr(rule, k, v)
    db.commit()
    db.refresh(rule)
    return rule


@router.delete("/rules/{rule_id}")
def delete_rule(rule_id: int, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    rule = db.query(DispatchRule).filter(DispatchRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="规则不存在")
    _ensure_category_in_scope(db, current_user, rule.category_code)
    db.delete(rule)
    db.commit()
    return {"message": "已删除"}
