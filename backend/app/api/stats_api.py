"""平台使用统计（仅管理员）：上传量、清洗任务、匹配结果与沉淀资产。"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import case, func, literal_column
from sqlalchemy.orm import Session

from app.core.auth_deps import require_admin
from app.models.database import SessionLocal, get_db
from app.models.schemas import (
    BrandRecord,
    Category,
    CleanJobRecord,
    HistoricalMapping,
    ItemExclusion,
    ItemUrlMapping,
    MatchResult,
    ModelRecord,
    PublishJob,
    RawDataRecord,
    UploadConfirmJob,
    UploadFileRecord,
    User,
)
from app.utils.time_utils import format_beijing_datetime


router = APIRouter(prefix="/api/stats", tags=["stats"])
logger = logging.getLogger(__name__)

# 与清洗任务列表口径一致（app/api/clean.py _serialize_job / 前端 Clean 页）
PUBLISHABLE_STATUSES = ("url_matched", "matched", "confirmed")
ACTIONABLE_STATUSES = ("pending", "text_only", "disputed")
TASK_PENDING_STATUSES = ("pending", "text_only")
REVIEW_STATUSES = ("done", "reviewing")
PROCESSING_STATUSES = ("created", "cleaning", "matching", "processing")
FAILED_STATUSES = ("failed", "error")
ARCHIVED_STATUS = "archived"


def _int(value) -> int:
    return int(value or 0)


def _month_expr(db: Session, column):
    """按北京时间（UTC+8）取 YYYY-MM；库里时间统一以 UTC 写入。"""
    if db.get_bind().dialect.name == "sqlite":
        return func.strftime("%Y-%m", column, "+8 hours")
    return func.date_format(func.date_add(column, literal_column("INTERVAL 8 HOUR")), "%Y-%m")


# raw_data（千万级）与 historical_mappings（百万级）全表 COUNT 在生产库要 30s+，
# 改为后台线程定时刷新、接口直接读缓存；首次未算完时返回 None，前端显示「统计中」。
SLOW_COUNT_TTL = timedelta(hours=1)
_slow_count_lock = threading.Lock()
_slow_count_cache: dict = {"values": {}, "computed_at": None, "running": False}


def _refresh_slow_counts(db: Session) -> None:
    values = {
        "raw_rows": _int(db.query(func.count(RawDataRecord.id)).scalar()),
        "historical_mappings": _int(db.query(func.count(HistoricalMapping.id)).scalar()),
    }
    with _slow_count_lock:
        _slow_count_cache["values"] = values
        _slow_count_cache["computed_at"] = datetime.utcnow()


def _refresh_slow_counts_in_background() -> None:
    def run():
        db = SessionLocal()
        try:
            _refresh_slow_counts(db)
        except Exception:
            logger.exception("refresh platform slow counts failed")
        finally:
            db.close()
            with _slow_count_lock:
                _slow_count_cache["running"] = False

    threading.Thread(target=run, name="stats-slow-counts", daemon=True).start()


def _slow_counts() -> tuple[dict, datetime | None]:
    with _slow_count_lock:
        computed_at = _slow_count_cache["computed_at"]
        expired = computed_at is None or datetime.utcnow() - computed_at > SLOW_COUNT_TTL
        should_start = expired and not _slow_count_cache["running"]
        if should_start:
            _slow_count_cache["running"] = True
        values = dict(_slow_count_cache["values"])
    if should_start:
        _refresh_slow_counts_in_background()
    return values, computed_at


def _upload_stats(db: Session, slow_counts: dict) -> dict:
    files = db.query(
        func.count(UploadFileRecord.id),
        func.sum(UploadFileRecord.row_count),
        func.min(UploadFileRecord.uploaded_at),
        func.max(UploadFileRecord.uploaded_at),
    ).filter(UploadFileRecord.status == "done").one()
    confirm = db.query(
        func.sum(UploadConfirmJob.inserted_rows),
        func.sum(UploadConfirmJob.skipped_rows),
    ).filter(UploadConfirmJob.status == "done").one()
    return {
        "file_count": _int(files[0]),
        "file_rows": _int(files[1]),
        "raw_rows": slow_counts.get("raw_rows"),
        "inserted_rows": _int(confirm[0]),
        "dedup_skipped_rows": _int(confirm[1]),
        "first_uploaded_at": format_beijing_datetime(files[2]) if files[2] else None,
        "last_uploaded_at": format_beijing_datetime(files[3]) if files[3] else None,
    }


def _clean_stats(db: Session) -> dict:
    pending_sub = (
        db.query(MatchResult.clean_job_id.label("job_id"), func.count(MatchResult.id).label("pending"))
        .filter(MatchResult.match_status.in_(TASK_PENDING_STATUSES))
        .group_by(MatchResult.clean_job_id)
        .subquery()
    )
    pending = func.coalesce(pending_sub.c.pending, 0)
    status = CleanJobRecord.status
    row = (
        db.query(
            func.count(CleanJobRecord.id),
            func.sum(case((status.in_(REVIEW_STATUSES) & (pending == 0), 1), (status == "published", 1), else_=0)),
            func.sum(case((status.in_(REVIEW_STATUSES) & (pending > 0), 1), else_=0)),
            func.sum(case((status.in_(PROCESSING_STATUSES), 1), else_=0)),
            func.sum(case((status.in_(FAILED_STATUSES), 1), else_=0)),
            func.sum(CleanJobRecord.row_in),
            func.sum(CleanJobRecord.row_out),
            func.sum(CleanJobRecord.row_filtered),
        )
        .outerjoin(pending_sub, pending_sub.c.job_id == CleanJobRecord.id)
        .filter(status != ARCHIVED_STATUS)
        .one()
    )
    published = (
        db.query(func.count(func.distinct(PublishJob.clean_job_id)), func.sum(PublishJob.published_count))
        .join(CleanJobRecord, CleanJobRecord.id == PublishJob.clean_job_id)
        .filter(PublishJob.status == "done", CleanJobRecord.status != ARCHIVED_STATUS)
        .one()
    )
    archived = db.query(func.count(CleanJobRecord.id)).filter(status == ARCHIVED_STATUS).scalar()
    return {
        "task_total": _int(row[0]),
        "clean_finished": _int(row[1]),
        "has_pending": _int(row[2]),
        "processing": _int(row[3]),
        "failed": _int(row[4]),
        "row_in": _int(row[5]),
        "row_out": _int(row[6]),
        "row_filtered": _int(row[7]),
        "published_tasks": _int(published[0]),
        "published_rows": _int(published[1]),
        "archived": _int(archived),
    }


def _active_match_query(db: Session, *columns):
    """有效匹配结果：排除已删除任务与干扰过滤（is_disabled=1）行。"""
    return (
        db.query(*columns)
        .join(CleanJobRecord, CleanJobRecord.id == MatchResult.clean_job_id)
        .filter(CleanJobRecord.status != ARCHIVED_STATUS, MatchResult.is_disabled == 0)
    )


def _match_stats(db: Session) -> dict:
    counts = {
        status: _int(count)
        for status, count in _active_match_query(db, MatchResult.match_status, func.count(MatchResult.id))
        .group_by(MatchResult.match_status)
        .all()
    }
    auto_matched = _active_match_query(db, func.count(MatchResult.id)).filter(
        MatchResult.matched_by == "auto",
        MatchResult.match_status.in_(("url_matched", "matched")),
    ).scalar()
    publishable_distinct = _active_match_query(db, func.count(func.distinct(MatchResult.raw_data_id))).filter(
        MatchResult.match_status.in_(PUBLISHABLE_STATUSES)
    ).scalar()
    total = sum(counts.values())
    return {
        "total": total,
        "url_matched": counts.get("url_matched", 0),
        "matched": counts.get("matched", 0),
        "confirmed": counts.get("confirmed", 0),
        "publishable": sum(counts.get(s, 0) for s in PUBLISHABLE_STATUSES),
        "publishable_distinct": _int(publishable_distinct),
        "excluded": counts.get("excluded", 0),
        "ignored": counts.get("ignored", 0),
        "pending": counts.get("pending", 0),
        "text_only": counts.get("text_only", 0),
        "disputed": counts.get("disputed", 0),
        "actionable": sum(counts.get(s, 0) for s in ACTIONABLE_STATUSES),
        "auto_matched": _int(auto_matched),
    }


def _source_stats(db: Session) -> list[dict]:
    rows = (
        _active_match_query(db, MatchResult.match_source, MatchResult.match_status, func.count(MatchResult.id))
        .group_by(MatchResult.match_source, MatchResult.match_status)
        .all()
    )
    items = [
        {"source": source or "", "status": status, "count": _int(count)}
        for source, status, count in rows
    ]
    return sorted(items, key=lambda item: item["count"], reverse=True)


def _category_stats(db: Session) -> list[dict]:
    category_code = func.coalesce(CleanJobRecord.category_code, CleanJobRecord.dispatch_category_code)
    month = _month_expr(db, CleanJobRecord.created_at)
    status = MatchResult.match_status
    rows = (
        db.query(
            category_code.label("category_code"),
            CleanJobRecord.platform,
            month.label("month"),
            func.count(func.distinct(CleanJobRecord.id)),
            func.count(MatchResult.id),
            func.sum(case((status.in_(PUBLISHABLE_STATUSES), 1), else_=0)),
            func.sum(case((status == "url_matched", 1), else_=0)),
            func.sum(case((status.in_(ACTIONABLE_STATUSES), 1), else_=0)),
        )
        .outerjoin(
            MatchResult,
            (MatchResult.clean_job_id == CleanJobRecord.id) & (MatchResult.is_disabled == 0),
        )
        .filter(CleanJobRecord.status != ARCHIVED_STATUS)
        .group_by(category_code, CleanJobRecord.platform, month)
        .all()
    )
    names = dict(db.query(Category.code, Category.name).all())
    items = [
        {
            "category_code": code,
            "category_name": names.get(code) or code,
            "platform": platform,
            "month": month_value,
            "tasks": _int(tasks),
            "total": _int(total),
            "publishable": _int(publishable),
            "url_matched": _int(url_matched),
            "actionable": _int(actionable),
        }
        for code, platform, month_value, tasks, total, publishable, url_matched, actionable in rows
    ]
    return sorted(
        items,
        key=lambda item: (item["month"] or "", item["total"], item["tasks"]),
        reverse=True,
    )


def _monthly_stats(db: Session) -> list[dict]:
    months: dict[str, dict] = {}

    def bucket(month: str) -> dict:
        return months.setdefault(month, {
            "month": month, "upload_files": 0, "upload_rows": 0,
            "tasks_created": 0, "rows_in": 0, "manual_reviewed": 0,
        })

    upload_month = _month_expr(db, UploadFileRecord.uploaded_at)
    for month, files, rows in (
        db.query(upload_month, func.count(UploadFileRecord.id), func.sum(UploadFileRecord.row_count))
        .filter(UploadFileRecord.status == "done", UploadFileRecord.uploaded_at.isnot(None))
        .group_by(upload_month)
        .all()
    ):
        bucket(month).update(upload_files=_int(files), upload_rows=_int(rows))

    task_month = _month_expr(db, CleanJobRecord.created_at)
    for month, tasks, rows_in in (
        db.query(task_month, func.count(CleanJobRecord.id), func.sum(CleanJobRecord.row_in))
        .filter(CleanJobRecord.status != ARCHIVED_STATUS, CleanJobRecord.created_at.isnot(None))
        .group_by(task_month)
        .all()
    ):
        bucket(month).update(tasks_created=_int(tasks), rows_in=_int(rows_in))

    # reviewed_at 会被重复操作覆盖，只能作为人工处理量的近似值
    review_month = _month_expr(db, MatchResult.reviewed_at)
    for month, reviewed in (
        db.query(review_month, func.count(MatchResult.id))
        .filter(MatchResult.reviewed_at.isnot(None))
        .group_by(review_month)
        .all()
    ):
        bucket(month)["manual_reviewed"] = _int(reviewed)

    return [months[key] for key in sorted(months)]


def _asset_stats(db: Session, slow_counts: dict) -> dict:
    mapping_sources = [
        {"source": source or "", "count": _int(count), "with_model": _int(with_model)}
        for source, count, with_model in db.query(
            ItemUrlMapping.source,
            func.count(ItemUrlMapping.id),
            func.sum(case((ItemUrlMapping.model_id.isnot(None), 1), else_=0)),
        ).group_by(ItemUrlMapping.source).all()
    ]
    login_since = datetime.utcnow() - timedelta(days=30)
    users = db.query(
        func.count(User.id),
        func.sum(case((User.is_active == 1, 1), else_=0)),
        func.sum(case((User.last_login_at >= login_since, 1), else_=0)),
    ).one()
    return {
        "url_mappings": sum(item["count"] for item in mapping_sources),
        "url_mappings_with_model": sum(item["with_model"] for item in mapping_sources),
        "url_mapping_sources": sorted(mapping_sources, key=lambda item: item["count"], reverse=True),
        "exclusions": _int(db.query(func.count(ItemExclusion.id)).scalar()),
        "historical_mappings": slow_counts.get("historical_mappings"),
        "models": _int(db.query(func.count(ModelRecord.id)).scalar()),
        "brands": _int(db.query(func.count(BrandRecord.id)).scalar()),
        "users": _int(users[0]),
        "active_users": _int(users[1]),
        "login_users_30d": _int(users[2]),
    }


@router.get("/overview", response_model=dict)
def get_stats_overview(
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    slow_counts, slow_counts_at = _slow_counts()
    return {
        "code": 0,
        "data": {
            "upload": _upload_stats(db, slow_counts),
            "clean": _clean_stats(db),
            "match": _match_stats(db),
            "sources": _source_stats(db),
            "categories": _category_stats(db),
            "monthly": _monthly_stats(db),
            "assets": _asset_stats(db, slow_counts),
            "generated_at": format_beijing_datetime(datetime.utcnow()),
            "slow_counts_at": format_beijing_datetime(slow_counts_at) if slow_counts_at else None,
        },
    }
