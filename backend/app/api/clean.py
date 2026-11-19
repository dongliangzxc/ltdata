from datetime import datetime
from io import BytesIO
import logging
import re
import shutil
import sys
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Optional
from urllib.parse import quote
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy import String, and_, case, func, literal, or_, select
from sqlalchemy.orm import Session, aliased
from pydantic import BaseModel
from app.core.auth_deps import get_current_user
from app.core.config import settings
from app.core.permissions import visible_category_codes
from app.services.currency_service import amount_to_cny, build_rate_map, get_country
from app.models.database import get_db
from app.services.clean_task_queue import (
    BUSY_CLEAN_STATUSES, clean_heavy_slot, enqueue_clean_job, ensure_clean_job_idle,
)
from app.services.clean_accounting import clean_accounting
from app.models.analytics_db import AnalyticsSession
from app.models.schemas import (
    CleanJobRecord,
    CleanDuplicateRecord,
    CleanedDataRecord,
    CleanJobOut,
    CleanedDataOut,
    CleanPoolCategoryOut,
    CleanMonthlyPoolOut,
    UpsertMonthlyCleanTaskIn,
    UpsertMonthlyCleanTaskOut,
    CreateCleanTaskIn,
    CreateCleanTaskOut,
    DispatchBatch,
    DispatchItem,
    FilteredItem,
    MatchResult,
    MatchResultAttr,
    MatchResultExtraValue,
    MatchResultCandidate,
    ModelRecord,
    ItemUrlMapping,
    PublishJob,
    RawDataRecord,
    UploadFileRecord,
    Category,
    CleanJobItemRecord,
    CleanTaskRun,
    ColumnTemplate,
    BrandRecord,
    User,
)
from app.services.clean_task_snapshot import (
    ACTIVE_TASK_STATUSES,
    _find_monthly_job,
    _has_reviewed_or_published_state,
    _job_months,
    create_category_task_snapshot,
    get_clean_pool_summary,
    get_monthly_clean_pool,
    normalize_platform,
    touch_clean_job,
    upsert_monthly_task_snapshot,
)
from app.services.exclusion_store import upsert_exclusion_for_raw
from app.services.data_cleaner import run_clean, _load_brand_alias_map, manual_brand_std
from app.services.excel_parser import iter_mapped_chunks
from app.services.filename_metadata import parse_filename_metadata
from app.services.matcher import run_match
from app.services.attribute_matcher import run_attribute_matching
from app.services.price_auditor import audit_price
from app.services.publisher import delete_published_data
from app.services.rawdata_cache import invalidate_rawdata_cache
from app.utils.time_utils import format_beijing_datetime

router = APIRouter(prefix="/api/clean", tags=["clean"])
logger = logging.getLogger(__name__)

# 「只清洗品牌」默认范围排除的匹配状态：已匹配/已人工确认/已排除/已忽略
BRAND_CLEAN_RESOLVED_STATUSES = ("matched", "url_matched", "confirmed", "excluded", "ignored")
# 可人工补充/覆盖品牌的匹配状态
BRAND_CLEAN_ACTIONABLE_STATUSES = ("pending", "text_only", "disputed")

# 待入清洗队列（/pool/monthly）是重只读聚合：无品类筛选时会按品类逐个扫描
# dispatch_items（千万级）并回表 raw_data（千万级宽表）。单次约数秒，多用户/刷新
# 反复触发会打满云盘读 BPS。这里做进程内短 TTL 缓存（生产单 worker），并在
# 派发/清洗任务变更时显式失效；TTL 只作兜底（匹配/发布等改动最多延迟这么久）。
_CLEAN_POOL_CACHE_TTL_SECONDS = 60.0
# 测试环境（pytest）不启用，避免跨用例污染
_clean_pool_cache_enabled = "pytest" not in sys.modules
_clean_pool_cache: dict = {}
_clean_pool_cache_lock = threading.Lock()


def invalidate_clean_pool_cache() -> None:
    with _clean_pool_cache_lock:
        _clean_pool_cache.clear()


def _clean_pool_cache_get(key):
    if not _clean_pool_cache_enabled:
        return None
    with _clean_pool_cache_lock:
        entry = _clean_pool_cache.get(key)
        if entry is None:
            return None
        cached_at, rows = entry
        if time.monotonic() - cached_at > _CLEAN_POOL_CACHE_TTL_SECONDS:
            _clean_pool_cache.pop(key, None)
            return None
        return rows


def _clean_pool_cache_set(key, rows) -> None:
    if not _clean_pool_cache_enabled:
        return
    with _clean_pool_cache_lock:
        if len(_clean_pool_cache) >= 512:
            _clean_pool_cache.clear()
        _clean_pool_cache[key] = (time.monotonic(), rows)


# ── 同范围清洗任务并发锁 ──────────────────────────────────────────
# 创建/更新/重建同一（品类, 平台[, 月份]）范围的清洗任务会在一个长事务里写
# filtered_items / cleaned_data / match_results。两个并发请求处理同一范围时，
# 后一个会等前一个未提交事务的行锁，50s 后抛 1205（Lock wait timeout），且
# 整个任务回滚。这里用进程内锁（生产 uvicorn 单 worker）保证同一范围同时只有
# 一个任务在跑，第二个请求直接 409 提示重试，而不是撞锁超时。
# 锁键含月份：按月任务之间互不阻塞；创建/重跑任务用月份通配键，防止与同品类
# 派发创建任务撞同一批待清洗数据。
_clean_scope_lock_guard = threading.Lock()
_clean_scope_locks: dict[str, threading.Lock] = {}


def _clean_scope_lock_key(category_code: str, platform: str | None, month: int | None = None) -> str:
    normalized = normalize_platform(platform) or ""
    month_part = str(month) if month is not None else "*"
    return f"clean-task:{category_code}:{normalized}:{month_part}"


def _acquire_clean_scope_lock(key: str) -> bool:
    with _clean_scope_lock_guard:
        lock = _clean_scope_locks.setdefault(key, threading.Lock())
    return lock.acquire(blocking=False)


def _release_clean_scope_lock(key: str) -> None:
    _clean_scope_locks[key].release()


@contextmanager
def _clean_scope_guard(category_code: str, platform: str | None, month: int | None = None):
    """同一清洗范围串行化：锁已被其它请求持有则抛 409，成功则持有到请求结束。"""
    key = _clean_scope_lock_key(category_code, platform, month)
    if not _acquire_clean_scope_lock(key):
        scope_desc = f"{category_code} / {platform or ''} / {month if month is not None else '全部月份'}"
        raise HTTPException(status_code=409, detail=f"该范围（{scope_desc}）的清洗任务正在处理中，请稍后重试")
    try:
        yield
    finally:
        _release_clean_scope_lock(key)


def _visible_clean_category_codes(db: Session, current_user: User) -> set[str] | None:
    if getattr(current_user, "is_admin", 0) == 1:
        return None
    if not getattr(current_user, "category_permissions", None):
        return None
    all_codes = [code for code, in db.query(Category.code).order_by(Category.sort_order, Category.name).all()]
    if not all_codes:
        return None
    return set(visible_category_codes(current_user, all_codes))


def _ensure_clean_category_visible(db: Session, current_user: User, category_code: str | None) -> None:
    if not category_code:
        return
    visible_codes = _visible_clean_category_codes(db, current_user)
    if visible_codes is not None and category_code not in visible_codes:
        raise HTTPException(status_code=403, detail="无权限访问该品类")


def _filter_clean_job_visible_categories(query, db: Session, current_user: User, visible_codes: set[str] | None = None):
    if visible_codes is None:
        visible_codes = _visible_clean_category_codes(db, current_user)
    if visible_codes is None:
        return query
    return query.filter(or_(
        CleanJobRecord.category_code.in_(visible_codes),
        CleanJobRecord.dispatch_category_code.in_(visible_codes),
        and_(CleanJobRecord.category_code.is_(None), CleanJobRecord.dispatch_category_code.is_(None)),
    ))


def _filter_dispatch_item_visible_categories(query, db: Session, current_user: User):
    visible_codes = _visible_clean_category_codes(db, current_user)
    if visible_codes is None:
        return query
    return query.filter(DispatchItem.category_code.in_(visible_codes))


def _get_visible_clean_job_or_404(db: Session, current_user: User, job_id: int) -> CleanJobRecord:
    q = db.query(CleanJobRecord).filter(CleanJobRecord.id == job_id)
    q = _filter_clean_job_visible_categories(q, db, current_user)
    job = q.first()
    if not job:
        raise HTTPException(status_code=404, detail="清洗任务不存在")
    return job


def _build_clean_scope_desc(
    db: Session,
    job: CleanJobRecord,
    category_names: dict[str, str] | None = None,
) -> str:
    files = []
    if job.file_ids:
        files = db.query(UploadFileRecord).filter(UploadFileRecord.id.in_(job.file_ids)).all()
    platforms = sorted({f.platform for f in files if f.platform})
    months = sorted({f.month_range for f in files if f.month_range})
    filenames = [f.filename for f in files if f.filename]

    is_task_snapshot = bool(job.task_name or job.source_scope)

    parts = []
    if is_task_snapshot:
        if job.task_name:
            parts.append(job.task_name)
        category_code = job.category_code or job.dispatch_category_code
        if category_code:
            category_name = category_names.get(category_code) if category_names else None
            if category_name is None and category_names is None:
                category = db.query(Category).filter(Category.code == category_code).first()
                category_name = category.name if category else None
            category_label = f"{category_name}（{category_code}）" if category_name else category_code
            parts.append(f"品类：{category_label}")
        if job.platform:
            parts.append(f"平台：{job.platform}")
    else:
        if job.dispatch_batch_id:
            parts.append(f"分发批次#{job.dispatch_batch_id}")
        if job.dispatch_category_code:
            category_name = category_names.get(job.dispatch_category_code) if category_names else None
            if category_name is None and category_names is None:
                category = db.query(Category).filter(Category.code == job.dispatch_category_code).first()
                category_name = category.name if category else None
            category_label = (
                f"{category_name}（{job.dispatch_category_code}）"
                if category_name
                else job.dispatch_category_code
            )
            parts.append(f"品类：{category_label}")
        if platforms:
            parts.append(f"平台：{'、'.join(platforms)}")
        if months:
            parts.append(f"月份：{'、'.join(months)}")
        if filenames:
            parts.append(f"文件：{'、'.join(filenames[:2])}{' 等' if len(filenames) > 2 else ''}")
    if parts:
        return " / ".join(parts)
    if job.file_ids:
        return "、".join(f"文件#{file_id}" for file_id in job.file_ids)
    return "-"


def _match_status_counts(db: Session, clean_job_id: int) -> dict[str, int]:
    return {
        status: count
        for status, count in db.query(MatchResult.match_status, func.count(MatchResult.id))
        .filter(MatchResult.clean_job_id == clean_job_id)
        .group_by(MatchResult.match_status)
        .all()
    }


def _job_month(job: CleanJobRecord) -> int | None:
    scope = job.source_scope
    if isinstance(scope, dict):
        month = scope.get("month")
        if month is not None:
            try:
                return int(month)
            except (TypeError, ValueError):
                pass
        months = scope.get("months")
        if isinstance(months, list) and len(months) == 1:
            try:
                return int(months[0])
            except (TypeError, ValueError):
                pass
    if job.task_name:
        match = re.search(r"(?<!\d)(20\d{4})(?!\d)", job.task_name)
        if match:
            return int(match.group(1))
    return None


def _clean_job_to_dict(
    db: Session,
    job: CleanJobRecord,
    match_counts: dict[str, int] | None = None,
    category_names: dict[str, str] | None = None,
) -> dict:
    counts = match_counts if match_counts is not None else _match_status_counts(db, job.id)
    pending_count = counts.get("pending", 0) + counts.get("text_only", 0)
    disputed_count = counts.get("disputed", 0)
    confirmed_count = counts.get("confirmed", 0)
    ignored_count = counts.get("ignored", 0)
    publishable_count = (
        counts.get("url_matched", 0)
        + counts.get("matched", 0)
        + confirmed_count
    )
    return {
        "id": job.id,
        "file_ids": job.file_ids,
        "rules": job.rules,
        "status": job.status,
        "row_in": job.row_in,
        "row_out": job.row_out,
        "row_filtered": job.row_filtered,
        "row_duplicated": job.row_duplicated,
        "dispatch_batch_id": job.dispatch_batch_id,
        "dispatch_category_code": job.dispatch_category_code,
        "task_name": job.task_name,
        "category_code": job.category_code or job.dispatch_category_code,
        "platform": job.platform,
        "month": _job_month(job),
        "source_scope": job.source_scope,
        "progress": job.progress or 0,
        "progress_stage": job.progress_stage,
        "error_msg": job.error_msg,
        "pending_count": pending_count,
        "disputed_count": disputed_count,
        "confirmed_count": confirmed_count,
        "ignored_count": ignored_count,
        "publishable_count": publishable_count,
        "created_at": format_beijing_datetime(job.created_at),
        "updated_at": format_beijing_datetime(job.updated_at),
        "scope_desc": _build_clean_scope_desc(db, job, category_names),
    }


def _reset_clean_job_downstream(db: Session, clean_job_id: int) -> None:
    """强制重建前清除任务的全部下游记录：发布数据（含分析库）、人工处理结果、清洗产物。"""
    _clear_duplicate_audit(db, clean_job_id)
    old_match_result_ids = [
        row.id
        for row in db.query(MatchResult.id)
        .filter(MatchResult.clean_job_id == clean_job_id)
        .all()
    ]
    if old_match_result_ids:
        db.query(MatchResultAttr).filter(
            MatchResultAttr.match_result_id.in_(old_match_result_ids)
        ).delete(synchronize_session=False)
        db.query(MatchResultCandidate).filter(
            MatchResultCandidate.match_result_id.in_(old_match_result_ids)
        ).delete(synchronize_session=False)
    db.query(MatchResult).filter(MatchResult.clean_job_id == clean_job_id).delete(synchronize_session=False)
    db.query(FilteredItem).filter(FilteredItem.clean_job_id == clean_job_id).delete(synchronize_session=False)
    db.query(CleanedDataRecord).filter(CleanedDataRecord.clean_job_id == clean_job_id).delete(synchronize_session=False)
    db.query(PublishJob).filter(PublishJob.clean_job_id == clean_job_id).delete(synchronize_session=False)
    analytics_db = AnalyticsSession()
    try:
        delete_published_data(analytics_db, clean_job_id)
        analytics_db.commit()
    finally:
        analytics_db.close()
    db.flush()


def _clear_clean_job_outputs(db: Session, clean_job_id: int) -> None:
    _clear_duplicate_audit(db, clean_job_id)
    old_match_result_ids = [
        row.id
        for row in db.query(MatchResult.id)
        .filter(MatchResult.clean_job_id == clean_job_id)
        .all()
    ]
    if old_match_result_ids:
        db.query(MatchResultAttr).filter(
            MatchResultAttr.match_result_id.in_(old_match_result_ids)
        ).delete(synchronize_session=False)
        db.query(MatchResultCandidate).filter(
            MatchResultCandidate.match_result_id.in_(old_match_result_ids)
        ).delete(synchronize_session=False)
    db.query(MatchResult).filter(MatchResult.clean_job_id == clean_job_id).delete(synchronize_session=False)
    db.query(FilteredItem).filter(FilteredItem.clean_job_id == clean_job_id).delete(synchronize_session=False)
    db.query(CleanedDataRecord).filter(CleanedDataRecord.clean_job_id == clean_job_id).delete(synchronize_session=False)


def _clear_duplicate_audit(db: Session, clean_job_id: int) -> None:
    db.query(CleanDuplicateRecord).filter_by(clean_job_id=clean_job_id).delete(synchronize_session=False)
    job = db.get(CleanJobRecord, clean_job_id)
    if job:
        job.row_duplicated = None


def _maybe_commit_and_refresh(db: Session, job: CleanJobRecord, commit: bool) -> None:
    if commit:
        db.commit()
        db.refresh(job)
    else:
        db.flush()


def _run_clean_and_match_for_job(db: Session, job: CleanJobRecord, commit: bool = True, stage_progress_cb=None) -> None:
    _t0 = time.perf_counter()
    job.status = "cleaning"
    job.progress = 10
    job.progress_stage = "清洗中"
    job.error_msg = None
    _maybe_commit_and_refresh(db, job, commit)

    _clear_clean_job_outputs(db, job.id)
    _maybe_commit_and_refresh(db, job, commit)
    _t1 = time.perf_counter()

    row_out = run_clean(
        db,
        job.id,
        job.file_ids or [],
        job.rules or {},
        job.dispatch_batch_id,
        job.dispatch_category_code or job.category_code,
        commit=commit,
        **({"progress_cb": lambda processed: stage_progress_cb("清洗中", processed, job.row_in or 0)} if stage_progress_cb else {}),
    )
    job.row_out = row_out
    job.status = "matching"
    job.progress = 50
    job.progress_stage = "匹配中"
    _maybe_commit_and_refresh(db, job, commit)
    _t2 = time.perf_counter()

    if stage_progress_cb:
        run_match(db, job.id, commit=commit,
                  progress_cb=lambda processed, total, matched: stage_progress_cb("型号匹配中", processed, total),
                  stage_progress_cb=stage_progress_cb, strict_audit=True)
    else:
        run_match(db, job.id, commit=commit)
    job.status = "reviewing"
    job.progress = 100
    job.progress_stage = "待处理"
    _maybe_commit_and_refresh(db, job, commit)
    logger.info(
        "clean_and_match job=%s clear=%.1fs clean=%.1fs match=%.1fs total=%.1fs",
        job.id, _t1 - _t0, _t2 - _t1, time.perf_counter() - _t2, time.perf_counter() - _t0,
    )


def _run_incremental_clean_and_match_for_job(
    db: Session, job: CleanJobRecord, *, snapshot_id_range, expected_count: int, stage_progress_cb=None,
) -> None:
    """Append atomically. The worker commits these outputs together with run=done.

    Bounds are job-scoped snapshot IDs, not a file/batch fallback. Existing
    snapshot IDs precede this range because the API locks the job before append.
    """
    start, end = snapshot_id_range
    if not start or not end or start > end or expected_count <= 0:
        raise ValueError("追加数据范围为空或不完整，无法执行")
    scope = (
        CleanJobItemRecord.clean_job_id == job.id,
        CleanJobItemRecord.id.between(start, end),
    )
    actual_count = db.query(CleanJobItemRecord.id).join(
        RawDataRecord, RawDataRecord.id == CleanJobItemRecord.raw_data_id,
    ).filter(*scope).count()
    if actual_count != expected_count:
        raise ValueError("追加数据范围已变化，请检查原始数据；未扩大清洗范围")
    raw_ids = select(CleanJobItemRecord.raw_data_id).where(*scope)
    # A successful append commits run=done with its outputs. A failed or killed
    # attempt rolls back all outputs; never clear old results to repair a scope.
    for model in (CleanedDataRecord, FilteredItem, MatchResult, CleanDuplicateRecord):
        if db.query(model.id).filter(model.clean_job_id == job.id, model.raw_data_id.in_(raw_ids)).first():
            raise ValueError("追加范围已存在处理结果，请检查任务，不能重复写入")
    job.status, job.progress_stage, job.error_msg = "cleaning", "清洗中", None
    run_clean(
        db, job.id, job.file_ids or [], job.rules or {},
        dispatch_category_code=job.dispatch_category_code or job.category_code,
        commit=False, raw_data_ids=raw_ids, update_job_counts=False,
        **({"progress_cb": lambda done: stage_progress_cb("清洗中", done, expected_count)} if stage_progress_cb else {}),
    )
    job.status, job.progress_stage = "matching", "型号匹配中"
    run_match(
        db, job.id, commit=False, raw_data_ids=raw_ids, strict_audit=True,
        **({"stage_progress_cb": stage_progress_cb,
            "progress_cb": lambda done, total, matched: stage_progress_cb("型号匹配中", done, total)} if stage_progress_cb else {}),
    )
    db.flush()
    job.row_in = db.query(CleanJobItemRecord).filter_by(clean_job_id=job.id).count()
    job.row_out = db.query(CleanedDataRecord).filter_by(clean_job_id=job.id).count()
    job.row_filtered = db.query(FilteredItem).filter_by(clean_job_id=job.id).count()
    if job.row_duplicated is not None:
        job.row_duplicated = db.query(CleanDuplicateRecord).filter_by(clean_job_id=job.id).count()
    job.status, job.progress_stage = "reviewing", "处理完成"
    db.flush()


def _manual_review_snapshot(db: Session, clean_job_id: int) -> dict[int, dict]:
    rows = (
        db.query(MatchResult)
        .filter(
            MatchResult.clean_job_id == clean_job_id,
            MatchResult.raw_data_id.isnot(None),
            MatchResult.matched_by == "manual",
            MatchResult.match_status.in_(["confirmed", "excluded", "ignored"]),
        )
        .all()
    )
    snapshot = {}
    for row in rows:
        if row.match_status == "confirmed" and row.model_id is None:
            continue
        snapshot[row.raw_data_id] = {
            "match_status": row.match_status,
            "model_id": row.model_id,
            "reviewed_at": row.reviewed_at,
            "review_note": row.review_note,
            "prev_match_status": row.prev_match_status,
            "prev_model_id": row.prev_model_id,
            "prev_matched_by": row.prev_matched_by,
            "prev_match_source": row.prev_match_source,
            "prev_dispute_reason": row.prev_dispute_reason,
            "prev_review_note": row.prev_review_note,
            "prev_reviewed_at": row.prev_reviewed_at,
        }
    return snapshot


def _upsert_url_mapping_from_match(db: Session, raw: RawDataRecord, model: ModelRecord) -> bool:
    if not raw.platform or not raw.item_id or not raw.item_url:
        return False
    existing = db.query(ItemUrlMapping).filter_by(platform=raw.platform, item_id=raw.item_id).first()
    if existing:
        existing.model_id = model.id
        existing.brand_code = model.brand_code
        existing.item_url = raw.item_url
        existing.price = raw.price
        existing.source = "match_confirm"
        return True
    db.add(ItemUrlMapping(
        platform=raw.platform,
        item_id=raw.item_id,
        item_url=raw.item_url,
        model_id=model.id,
        brand_code=model.brand_code,
        price=raw.price,
        source="match_confirm",
    ))
    return True


def _restore_manual_reviews(db: Session, clean_job_id: int, snapshot: dict[int, dict]) -> tuple[int, int, list[int]]:
    if not snapshot:
        return 0, 0, []
    rows = (
        db.query(MatchResult, RawDataRecord)
        .join(RawDataRecord, MatchResult.raw_data_id == RawDataRecord.id)
        .filter(
            MatchResult.clean_job_id == clean_job_id,
            MatchResult.raw_data_id.in_(snapshot.keys()),
        )
        .all()
    )
    model_ids = {saved["model_id"] for saved in snapshot.values() if saved["match_status"] == "confirmed" and saved.get("model_id")}
    models = {model.id: model for model in db.query(ModelRecord).filter(ModelRecord.id.in_(model_ids)).all()} if model_ids else {}
    restored_confirmed_count = 0
    restored_review_count = 0
    restored_confirmed_ids: list[int] = []
    now = datetime.utcnow()
    for mr, raw in rows:
        saved = snapshot[mr.raw_data_id]
        if saved["match_status"] == "confirmed":
            model = models.get(saved["model_id"])
            if not model:
                continue
            mr.model_id = saved["model_id"]
            mr.match_status = "confirmed"
            mr.dispute_reason = None
            _upsert_url_mapping_from_match(db, raw, model)
            restored_confirmed_count += 1
            restored_confirmed_ids.append(mr.id)
        elif saved["match_status"] == "excluded":
            mr.model_id = None
            mr.match_status = "excluded"
            mr.dispute_reason = None
        elif saved["match_status"] == "ignored":
            # Task-local ignore: keep it ignored for this task rerun without
            # touching the cross-task item_exclusions store.
            mr.model_id = None
            mr.match_status = "ignored"
            mr.dispute_reason = None
        else:
            continue
        mr.matched_by = "manual"
        mr.match_source = "manual"
        mr.review_note = saved.get("review_note")
        mr.reviewed_at = saved.get("reviewed_at") or now
        mr.prev_match_status = saved.get("prev_match_status")
        mr.prev_model_id = saved.get("prev_model_id")
        mr.prev_matched_by = saved.get("prev_matched_by")
        mr.prev_match_source = saved.get("prev_match_source")
        mr.prev_dispute_reason = saved.get("prev_dispute_reason")
        mr.prev_review_note = saved.get("prev_review_note")
        mr.prev_reviewed_at = saved.get("prev_reviewed_at")
        restored_review_count += 1
    return restored_confirmed_count, restored_review_count, restored_confirmed_ids


def _finalize_rerun_metadata(db: Session, clean_job_id: int, restored_ids: list[int]) -> None:
    final_ids = [
        row.id
        for row in db.query(MatchResult.id)
        .filter(
            MatchResult.clean_job_id == clean_job_id,
            MatchResult.match_status.in_(["matched", "url_matched", "confirmed"]),
        )
        .all()
    ]
    from app.services.attribute_matcher import run_attribute_matching
    from app.services.price_auditor import audit_price
    ids = sorted(set(final_ids + restored_ids))
    if not ids:
        return
    run_attribute_matching(db, ids, commit=False)
    audit_price(db, ids, commit=False)


def _run_clean_for_dispatch_category(
    db: Session,
    file_id: int,
    rules: dict,
    dispatch_batch_id: int,
    dispatch_category_code: str,
) -> CleanJobRecord:
    from app.models.schemas import RawDataRecord

    batch = db.query(DispatchBatch).filter(DispatchBatch.id == dispatch_batch_id).first()
    file_ids = [file_id]
    if batch and batch.batch_key:
        file_ids = [
            record_id
            for record_id, in db.query(UploadFileRecord.id)
            .filter(UploadFileRecord.batch_key == batch.batch_key)
            .order_by(UploadFileRecord.id)
            .all()
        ] or [file_id]

    raw_data_ids = select(DispatchItem.raw_data_id).filter(
        DispatchItem.batch_id == dispatch_batch_id,
        DispatchItem.category_code == dispatch_category_code,
    )
    row_in = db.query(RawDataRecord).filter(RawDataRecord.id.in_(raw_data_ids)).count()
    job = CleanJobRecord(
        file_ids=file_ids,
        rules=rules,
        status="processing",
        row_in=row_in,
        row_out=0,
        dispatch_batch_id=dispatch_batch_id,
        dispatch_category_code=dispatch_category_code,
    )
    db.add(job)
    db.flush()

    try:
        row_out = run_clean(db, job.id, file_ids, rules, dispatch_batch_id, dispatch_category_code)
        job.row_out = row_out
        job.status = "done"
        db.commit()
        db.refresh(job)
    except Exception as e:
        job.status = "error"
        db.commit()
        raise HTTPException(status_code=500, detail=f"清洗失败: {str(e)}")

    return job


@router.get("/pool/summary", response_model=list[CleanPoolCategoryOut])
def get_clean_pool_summary_endpoint(
    dispatch_batch_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rows = get_clean_pool_summary(db, dispatch_batch_id=dispatch_batch_id)
    visible_codes = _visible_clean_category_codes(db, current_user)
    if visible_codes is None:
        return rows
    return [row for row in rows if row.get("category_code") in visible_codes]


@router.get("/pool/monthly", response_model=list[CleanMonthlyPoolOut])
def get_monthly_clean_pool_endpoint(
    category_code: Optional[str] = Query(None),
    platform: Optional[str] = Query(None),
    month: Optional[int] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    visible_codes = _visible_clean_category_codes(db, current_user)
    if visible_codes is not None and category_code and category_code not in visible_codes:
        return []
    # 缓存键不含用户可见品类：昂贵的聚合结果按查询条件共享，权限过滤在缓存之后做，
    # 这样不同权限的用户也能命中同一份结果。
    cache_key = (category_code, platform, month, limit)
    rows = _clean_pool_cache_get(cache_key)
    if rows is not None:
        job_ids = {row["existing_job_id"] for row in rows if row.get("existing_job_id")}
        statuses = dict(db.query(CleanJobRecord.id, CleanJobRecord.status).filter(CleanJobRecord.id.in_(job_ids)).all()) if job_ids else {}
        if any(row.get("existing_job_id") and statuses.get(row["existing_job_id"]) != row.get("existing_job_status") for row in rows):
            rows = None  # Worker runs in another process and cannot clear this cache.
    if rows is None:
        rows = get_monthly_clean_pool(
            db,
            category_code=category_code,
            platform=platform,
            month=month,
            limit=limit,
        )
        _clean_pool_cache_set(cache_key, rows)
    if visible_codes is None:
        return rows
    return [row for row in rows if row.get("category_code") in visible_codes]


@router.post("/tasks", response_model=CreateCleanTaskOut)
def create_clean_task(
    payload: CreateCleanTaskIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ensure_clean_category_visible(db, current_user, payload.category_code)
    with _clean_scope_guard(payload.category_code, payload.platform):
        try:
            job, snapshot_count = create_category_task_snapshot(
                db,
                category_code=payload.category_code,
                platform=payload.platform,
                dispatch_batch_id=payload.dispatch_batch_id,
                task_name=payload.task_name,
                rules=payload.rules,
            )
            if settings.CLEAN_BACKGROUND_ENABLED:
                enqueue_clean_job(db, job)
            db.commit()
            db.refresh(job)
            if settings.CLEAN_BACKGROUND_ENABLED:
                invalidate_clean_pool_cache()
                return {"job": job, "snapshot_count": snapshot_count, "match_status": "queued"}
        except HTTPException:
            db.rollback()
            raise
        except ValueError as e:
            db.rollback()
            raise HTTPException(status_code=400, detail=f"没有可创建任务的数据: {str(e)}") from e
        except Exception as e:
            db.rollback()
            raise HTTPException(status_code=500, detail=f"创建清洗任务失败: {str(e)}") from e

        job_id = job.id
        try:
            job.status = "cleaning"
            db.commit()
            db.refresh(job)

            row_out = run_clean(
                db,
                job.id,
                job.file_ids or [],
                job.rules or {},
                job.dispatch_batch_id,
                job.dispatch_category_code,
            )
            job.row_out = row_out
            job.status = "matching"
            db.commit()
            db.refresh(job)

            run_match(db, job.id)
            job.status = "reviewing"
            db.commit()
            db.refresh(job)
        except Exception as e:
            db.rollback()
            failed_job = db.query(CleanJobRecord).filter(CleanJobRecord.id == job_id).first()
            if failed_job:
                db.query(CleanJobItemRecord).filter(CleanJobItemRecord.clean_job_id == job_id).delete(synchronize_session=False)
                failed_job.status = "failed"
                db.commit()
            raise HTTPException(status_code=500, detail=f"创建清洗任务失败: {str(e)}") from e

        invalidate_clean_pool_cache()
        return {"job": job, "snapshot_count": snapshot_count, "match_status": "done"}


@router.post("/tasks/upsert-monthly", response_model=UpsertMonthlyCleanTaskOut)
def upsert_monthly_clean_task(
    payload: UpsertMonthlyCleanTaskIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ensure_clean_category_visible(db, current_user, payload.category_code)
    with _clean_scope_guard(payload.category_code, payload.platform, payload.month):
        try:
            existing = _find_monthly_job(db, category_code=payload.category_code,
                                         platform=payload.platform, month=payload.month)
            if existing:
                ensure_clean_job_idle(db, existing.id, allow_failed=True)
            incremental = bool(settings.CLEAN_BACKGROUND_ENABLED and existing and existing.status != "archived"
                               and not payload.force_reclean and not payload.force_rebuild)
            if payload.force_rebuild:
                existing = _find_monthly_job(
                    db,
                    category_code=payload.category_code,
                    platform=payload.platform,
                    month=payload.month,
                )
                if existing and _has_reviewed_or_published_state(db, existing.id):
                    _reset_clean_job_downstream(db, existing.id)
            job, snapshot_count, action, new_snapshot_ids = upsert_monthly_task_snapshot(
                db,
                category_code=payload.category_code,
                platform=payload.platform,
                month=payload.month,
                rules=payload.rules,
                force_reclean=payload.force_reclean,
                force_rebuild=payload.force_rebuild,
            )
            if not new_snapshot_ids and action == "appended" and not payload.force_reclean and not payload.force_rebuild:
                db.commit()
                return {"job": job, "snapshot_count": 0, "action": action, "match_status": "unchanged"}
            # 快照先提交：避免「快照 + 清洗 + 匹配」挤在一个长事务里，导致其它
            # 请求在 filtered_items / cleaned_data 上长时间等锁（1205）。
            if settings.CLEAN_BACKGROUND_ENABLED:
                if incremental:
                    enqueue_clean_job(db, job, mode="incremental", snapshot_start_id=min(new_snapshot_ids),
                                      snapshot_end_id=max(new_snapshot_ids), input_count=len(new_snapshot_ids))
                else:
                    enqueue_clean_job(db, job)
            db.commit()
            db.refresh(job)
            if settings.CLEAN_BACKGROUND_ENABLED:
                invalidate_clean_pool_cache()
                return {"job": job, "snapshot_count": snapshot_count, "action": action, "match_status": "queued"}
            job_id = job.id
            try:
                _run_clean_and_match_for_job(db, job, commit=True)
            except ValueError:
                raise
            except Exception as e:
                db.rollback()
                failed_job = db.query(CleanJobRecord).filter(CleanJobRecord.id == job_id).first()
                if failed_job:
                    # 快照已提交：清掉下游输出并把任务整单删除，保持「失败即无任务」
                    # 语义（与之前单事务整体回滚的对外表现一致），让用户可重试。
                    _clear_clean_job_outputs(db, job_id)
                    db.query(CleanJobItemRecord).filter(
                        CleanJobItemRecord.clean_job_id == job_id
                    ).delete(synchronize_session=False)
                    db.query(CleanJobRecord).filter(CleanJobRecord.id == job_id).delete(synchronize_session=False)
                    db.commit()
                raise HTTPException(status_code=500, detail=f"更新清洗任务失败: {str(e)}") from e
        except HTTPException:
            db.rollback()
            raise
        except ValueError as e:
            db.rollback()
            raise HTTPException(status_code=400, detail=str(e)) from e
        except Exception as e:
            db.rollback()
            raise HTTPException(status_code=500, detail=f"更新清洗任务失败: {str(e)}") from e

        invalidate_clean_pool_cache()
        return {"job": job, "snapshot_count": snapshot_count, "action": action, "match_status": "done"}


@router.get("/jobs/progress")
def get_clean_job_progress(
    ids: str = Query(..., min_length=1, max_length=2200, pattern=r"^[0-9]+(,[0-9]+)*$"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    job_ids = sorted({int(value) for value in ids.split(",")})
    if len(job_ids) > 200:
        raise HTTPException(400, "一次最多查询 200 个任务")
    query = db.query(
        CleanJobRecord.id, CleanJobRecord.status, CleanJobRecord.progress_stage,
        CleanJobRecord.error_msg, CleanTaskRun.stage, CleanTaskRun.processed,
        CleanTaskRun.total, CleanTaskRun.state, CleanJobRecord.updated_at,
        CleanTaskRun.mode, CleanTaskRun.input_count,
    ).outerjoin(CleanTaskRun, CleanTaskRun.clean_job_id == CleanJobRecord.id).filter(CleanJobRecord.id.in_(job_ids))
    query = _filter_clean_job_visible_categories(query, db, current_user)
    return [dict(id=job_id, status=status, progress_stage=stage or job_stage,
                 progress_processed=processed or 0, progress_total=total or 0,
                 error_msg=error_msg, can_retry=state == "failed" and status == "failed", updated_at=format_beijing_datetime(updated_at),
                 execution_mode=mode or "full", execution_input_count=input_count or 0)
            for job_id, status, job_stage, error_msg, stage, processed, total, state, updated_at, mode, input_count in query.all()]


@router.post("/tasks/{job_id}/retry", response_model=CleanJobOut)
def retry_clean_task(
    job_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    _get_visible_clean_job_or_404(db, current_user, job_id)
    job = ensure_clean_job_idle(db, job_id, allow_failed=True)
    run = db.query(CleanTaskRun).filter_by(clean_job_id=job_id).first()
    if not settings.CLEAN_BACKGROUND_ENABLED or job.status != "failed" or run is None or run.state != "failed":
        raise HTTPException(409, "仅支持重试失败或中断的后台任务")
    if not db.query(CleanJobItemRecord.id).filter_by(clean_job_id=job_id).first():
        raise HTTPException(400, "任务数据范围为空，无法重试")
    # Full retries must protect all manual/published output. Incremental retries
    # only touch their saved range, so pre-existing manual output is safe.
    retry_scope = [MatchResult.clean_job_id == job_id]
    if run.mode == "incremental":
        if (not run.snapshot_start_id or not run.snapshot_end_id or run.snapshot_start_id > run.snapshot_end_id
                or not run.input_count or run.input_count < 0):
            raise HTTPException(409, "追加数据范围不完整，不能重试")
        retry_raw_ids = select(CleanJobItemRecord.raw_data_id).where(
            CleanJobItemRecord.clean_job_id == job_id,
            CleanJobItemRecord.id.between(run.snapshot_start_id, run.snapshot_end_id),
        )
        retry_scope.append(MatchResult.raw_data_id.in_(retry_raw_ids))
    manual = db.query(MatchResult.id).filter(*retry_scope, or_(
        MatchResult.matched_by == "manual", MatchResult.reviewed_at.isnot(None),
        MatchResult.review_note.isnot(None), MatchResult.is_disabled == 1,
        MatchResult.sales_coefficient.isnot(None), MatchResult.dispute_reason.isnot(None),
    )).first()
    manual_fields = db.query(MatchResultExtraValue.id).join(
        MatchResult, MatchResult.id == MatchResultExtraValue.match_result_id,
    ).filter(*retry_scope, MatchResultExtraValue.source == "manual").first()
    if manual or manual_fields or (run.mode != "incremental" and db.query(PublishJob.id).filter_by(clean_job_id=job_id).first()):
        raise HTTPException(409, "任务已有人工处理或发布记录，不能直接重试")
    enqueue_clean_job(db, job, mode=run.mode, snapshot_start_id=run.snapshot_start_id,
                      snapshot_end_id=run.snapshot_end_id, input_count=run.input_count)
    db.commit()
    db.refresh(job)
    invalidate_clean_pool_cache()
    return job


SUPPLEMENT_REQUIRED_FIELDS = {"item_id", "item_name", "sales_qty", "sales_amount", "price"}


@router.get("/supplement-template")
def download_supplement_template(current_user: User = Depends(get_current_user)):
    """补充上传专用示例：首张表可直接解析，第二张表说明字段和任务归属。"""
    from openpyxl import Workbook
    from openpyxl.comments import Comment
    from openpyxl.styles import Alignment, Font, PatternFill

    fields = [
        ["item_id", "商品ID", "是", "商品在平台上的唯一编号，不是型号。按文本填写，保留前导零和完整长数字。"],
        ["item_name", "商品名称", "是", "填写商品标题，例如某品牌10000mAh移动电源。"],
        ["sales_qty", "销量", "是", "本次数据周期内销售的件数，例如10。填写整数，不带单位。"],
        ["sales_amount", "销售额", "是", "本次数据周期内的总销售金额，例如10件共1290。填写纯数字；海外数据填写任务国家对应币种的原币金额。"],
        ["price", "单价", "是", "单件商品的价格，例如129。填写纯数字，不带货币符号；币种同销售额。"],
        ["brand_raw", "原始品牌", "否", "商品原始品牌名称。建议填写，便于品牌识别；没有可留空。"],
        ["shop_name", "店铺名称", "否", "销售该商品的店铺名称。建议填写；没有可留空。"],
        ["item_url", "商品链接", "否", "商品详情页的完整网址。建议填写真实链接，便于历史库和映射库匹配；没有可留空。"],
    ]
    workbook = Workbook()
    data = workbook.active
    data.title = "补充数据"
    data.append([field[0] for field in fields])
    data.append(["EXAMPLE-001", "示例商品A（请替换）", 10, 1290, 129, "示例品牌", "示例店铺", "https://example.com/items/EXAMPLE-001"])
    data.append(["EXAMPLE-002", "示例商品B（请替换）", 5, 995, 199, "示例品牌", "示例店铺", "https://example.com/items/EXAMPLE-002"])
    for index, (_, label, required, description) in enumerate(fields, start=1):
        requirement = "必填" if required == "是" else "选填"
        comment = Comment(
            f"{label}（{requirement}）\n{description}\n示例：{data.cell(2, index).value}",
            "洛图数据平台",
        )
        comment.width, comment.height = 360, 130
        data.cell(1, index).comment = comment
    for row in data.iter_rows(min_row=2):
        row[0].number_format = "@"
        row[2].number_format = "0"
        row[3].number_format = row[4].number_format = "0.00"
    for column, width in zip("ABCDEFGH", [24, 36, 16, 18, 16, 22, 26, 58]):
        data.column_dimensions[column].width = width
    data.auto_filter.ref = data.dimensions

    notes = workbook.create_sheet("填写说明")
    notes.append(["表头（保持不变）", "中文含义", "是否必填", "填写要求"])
    for values in [
        *fields,
        ["使用方法", "", "", "鼠标悬停首张表的英文表头可查看中文注释；删除或替换两行示例数据，保留第一行表头，每行填写一个商品。"],
        ["任务范围", "", "", "无需填写品类、平台、月份；系统统一使用点击「补充数据」所在任务的范围。"],
        ["国家与币种", "", "", "当前弹窗不选择国家；优先沿用任务唯一国家，否则尝试从文件名识别，仍无法识别时按中国处理。"],
        ["重复处理", "", "", "同一国家、平台、月份、商品ID的重复行会跳过，不覆盖已有数据；只清洗匹配新增行。"],
        ["提交后", "", "", "文件接收后进入后台队列，可在任务列表查看进度；处理失败请重试，无需重复上传。"],
    ]:
        notes.append(values)
    for column, width in zip("ABCD", [26, 18, 14, 90]):
        notes.column_dimensions[column].width = width
    for row in notes.iter_rows(min_row=2):
        notes.row_dimensions[row[0].row].height = 44
        for cell in row:
            cell.alignment = Alignment(vertical="center", wrap_text=True)
    for sheet in workbook:
        sheet.freeze_panes = "A2"
        sheet.row_dimensions[1].height = 28
        for cell in sheet[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="1677FF")
            cell.alignment = Alignment(vertical="center")
    buffer = BytesIO()
    workbook.save(buffer)
    filename = quote("补充数据上传示例.xlsx")
    return Response(
        content=buffer.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
    )


def _int_scope_list(values) -> list[int]:
    parsed: list[int] = []
    if not isinstance(values, list):
        return parsed
    for value in values:
        try:
            parsed.append(int(value))
        except (TypeError, ValueError):
            continue
    return parsed


def _resolve_supplement_mapping(db: Session, columns: list, template_id: int | None) -> tuple[dict, list]:
    from app.api.upload import REQUIRED_FIELDS, _find_best_template

    if template_id:
        template = db.query(ColumnTemplate).filter(ColumnTemplate.id == template_id).first()
        if not template:
            raise HTTPException(status_code=404, detail="列映射模板不存在")
        return dict(template.mapping or {}), list(template.ignore_columns or [])

    standard_fields = set(REQUIRED_FIELDS) | {
        "brand_raw", "brand", "shop_name", "item_url", "ref_price", "item_image", "week",
    }
    # The downloadable example must work even when a saved, similar template
    # remaps standard columns. Explicit template_id above remains authoritative.
    if SUPPLEMENT_REQUIRED_FIELDS.issubset(columns):
        return {column: column for column in columns if column in standard_fields}, []

    best_template, score = _find_best_template(columns, db)
    if best_template and score >= 60:
        return dict(best_template.mapping or {}), list(best_template.ignore_columns or [])

    return {column: column for column in columns if column in standard_fields}, []


@router.post("/tasks/{job_id}/supplement")
def supplement_clean_task(
    job_id: int,
    file: UploadFile = File(...),
    template_id: Optional[int] = Form(None),
    country_code: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """给已有清洗任务补充本月新增数据：只处理新增行，保留原任务结果。"""
    from app.api.upload import (
        _cleanup_old_tmp,
        _existing_upload_keys,
        _raw_insert_row,
        _read_columns,
    )

    job = _get_visible_clean_job_or_404(db, current_user, job_id)
    ensure_clean_job_idle(db, job_id)
    category_code = job.category_code or job.dispatch_category_code
    if not category_code:
        raise HTTPException(status_code=400, detail="任务缺少品类，无法补充数据")
    _ensure_clean_category_visible(db, current_user, category_code)
    platform = normalize_platform(job.platform)
    if not platform:
        raise HTTPException(status_code=400, detail="任务缺少平台，无法补充数据")
    months = sorted({int(month) for month in _job_months(job)})
    job_month = _job_month(job)
    if not months and job_month is not None:
        months = [job_month]
    if not months:
        raise HTTPException(status_code=400, detail="任务缺少月份信息，暂不支持补充数据")
    if len(months) != 1:
        raise HTTPException(status_code=400, detail="任务包含多个月份，暂不支持补充数据")
    month = months[0]

    if not file.filename or not file.filename.lower().endswith((".xlsx", ".xls", ".csv")):
        raise HTTPException(status_code=400, detail="只支持 .xlsx / .xls / .csv 格式文件")

    safe_filename = Path(file.filename).name
    tmp_dir = Path(settings.UPLOAD_DIR) / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    _cleanup_old_tmp(tmp_dir)
    temp_path = tmp_dir / f"supplement_{uuid.uuid4().hex}_{safe_filename}"
    safe_stem = Path(safe_filename).stem[:80]
    safe_suffix = Path(safe_filename).suffix
    final_name = f"补充-{job.id}-{uuid.uuid4().hex[:6]}-{safe_stem}{safe_suffix}"
    final_path = Path(settings.UPLOAD_DIR) / final_name
    batch_key = f"supplement:{job.id}:{uuid.uuid4().hex[:10]}"

    file_record: UploadFileRecord | None = None
    try:
        with open(temp_path, "wb") as handle:
            shutil.copyfileobj(file.file, handle)
        columns = _read_columns(temp_path)
        mapping, ignore_columns = _resolve_supplement_mapping(db, columns, template_id)
        mapped_targets = {value for value in mapping.values() if value != "__ext__"}
        missing = SUPPLEMENT_REQUIRED_FIELDS - mapped_targets
        if missing:
            raise HTTPException(
                status_code=422,
                detail=f"文件缺少必要列映射：{', '.join(sorted(missing))}；请使用与原始上传一致的模板",
            )

        country = (country_code or "").strip().upper() or None
        if not country:
            countries = {
                code for code, in db.query(RawDataRecord.country_code)
                .join(CleanJobItemRecord, CleanJobItemRecord.raw_data_id == RawDataRecord.id)
                .filter(CleanJobItemRecord.clean_job_id == job.id)
                .distinct()
                .all()
                if code
            }
            if len(countries) == 1:
                country = next(iter(countries))
        if not country:
            country = parse_filename_metadata(safe_filename, db).country_code
        if not country:
            country = "CN"
        if country != "CN":
            country_row = get_country(db, country)
            if country_row is None or country_row.is_active != 1:
                raise HTTPException(status_code=400, detail="国家不存在或已停用")
        data_region = "domestic" if country == "CN" else "overseas"

        file_record = UploadFileRecord(
            filename=final_name,
            platform=platform.upper(),
            month_range=str(month),
            row_count=0,
            status="processing",
            batch_key=batch_key,
            data_region=data_region,
            country_code=country,
            data_year=month // 100,
            data_month=month % 100,
        )
        db.add(file_record)
        db.flush()

        seen_keys: set = set()
        total_rows = inserted_rows = skipped_rows = 0
        for records, _chunk_platform, _chunk_months in iter_mapped_chunks(str(temp_path), mapping, ignore_columns):
            for record in records:
                record["month"] = month
                record["platform"] = platform
                record["source_category_code"] = category_code
            candidates = []
            for record in records:
                item_id = record.get("item_id")
                if item_id is not None:
                    key = (country, str(item_id), month, platform)
                    if key in seen_keys:
                        continue
                    seen_keys.add(key)
                candidates.append(record)
            existing_keys = _existing_upload_keys(db, candidates, country, filter_country=True)
            to_insert = [
                record for record in candidates
                if (country, str(record.get("item_id")), record.get("month"), record.get("platform")) not in existing_keys
            ]
            for start in range(0, len(to_insert), 5000):
                db.execute(
                    RawDataRecord.__table__.insert(),
                    [_raw_insert_row(file_record.id, country, record) for record in to_insert[start:start + 5000]],
                )
            total_rows += len(records)
            inserted_rows += len(to_insert)
            skipped_rows += len(records) - len(to_insert)

        if inserted_rows == 0:
            raise HTTPException(status_code=400, detail="文件中的数据均已存在，没有可补充的新数据")

        file_record.row_count = total_rows
        file_record.status = "done"
        db.flush()

        # Every source belongs to the just-created upload. Insert membership in
        # SQL rather than materialising IDs and issuing per-row ORM inserts.
        batch = DispatchBatch(
            file_id=file_record.id, batch_key=batch_key, status="done",
            total_rows=inserted_rows, dispatched_rows=inserted_rows,
            unmatched_rows=0, finished_at=datetime.utcnow(),
        )
        db.add(batch)
        db.flush()
        db.execute(DispatchItem.__table__.insert().from_select(
            ["batch_id", "raw_data_id", "category_code"],
            select(literal(batch.id), RawDataRecord.id, literal(category_code))
            .where(RawDataRecord.file_id == file_record.id).order_by(RawDataRecord.id),
        ))
        db.execute(CleanJobItemRecord.__table__.insert().from_select(
            ["clean_job_id", "raw_data_id", "category_code", "platform", "dispatch_batch_id"],
            select(literal(job.id), RawDataRecord.id, literal(category_code), literal(platform), literal(batch.id))
            .where(RawDataRecord.file_id == file_record.id).order_by(RawDataRecord.id),
        ))
        start_id, end_id, append_count = db.query(
            func.min(CleanJobItemRecord.id), func.max(CleanJobItemRecord.id), func.count(CleanJobItemRecord.id),
        ).filter_by(clean_job_id=job.id, dispatch_batch_id=batch.id).one()
        if append_count != inserted_rows:
            raise ValueError("补充数据快照数量与新增来源不一致，未提交任务")

        job.file_ids = sorted({*(job.file_ids or []), file_record.id})
        scope = job.source_scope if isinstance(job.source_scope, dict) else {}
        job.source_scope = {
            "months": sorted({*_int_scope_list(scope.get("months")), month}),
            "platforms": sorted({*(scope.get("platforms") or []), platform}),
            "dispatch_batch_ids": sorted({*_int_scope_list(scope.get("dispatch_batch_ids")), batch.id}),
            "file_ids": job.file_ids,
        }

        job.row_in = db.query(CleanJobItemRecord).filter_by(clean_job_id=job.id).count()
        if settings.CLEAN_BACKGROUND_ENABLED:
            enqueue_clean_job(db, job, mode="incremental", snapshot_start_id=start_id,
                              snapshot_end_id=end_id, input_count=append_count)
        else:
            # Compatibility mode shares bounded batch matching and strict audit.
            _run_incremental_clean_and_match_for_job(
                db, job, snapshot_id_range=(start_id, end_id), expected_count=append_count,
            )
        job.updated_at = datetime.utcnow()
        # Publish the original file before committing its durable references.
        # Rename/commit failures roll back upload, membership and queue together.
        shutil.move(str(temp_path), str(final_path))
        db.commit()
    except HTTPException:
        db.rollback()
        temp_path.unlink(missing_ok=True)
        final_path.unlink(missing_ok=True)
        raise
    except Exception as exc:
        db.rollback()
        temp_path.unlink(missing_ok=True)
        final_path.unlink(missing_ok=True)
        logger.exception("Supplement clean task failed job_id=%s", job_id)
        raise HTTPException(status_code=500, detail=f"补充数据失败: {exc}") from exc

    invalidate_rawdata_cache()
    invalidate_clean_pool_cache()
    counts = _match_status_counts(db, job.id)
    return {
        "code": 0,
        "data": {
            "job_id": job.id,
            "file_id": file_record.id if file_record else None,
            "total_rows": total_rows,
            "inserted_rows": inserted_rows,
            "duplicate_rows": skipped_rows,
            "appended_items": append_count,
            "match_status": "queued" if settings.CLEAN_BACKGROUND_ENABLED else "done",
            "status": job.status,
            "matched_count": counts.get("matched", 0) + counts.get("url_matched", 0) + counts.get("confirmed", 0),
            "pending_count": counts.get("pending", 0) + counts.get("text_only", 0) + counts.get("disputed", 0),
            "row_in": job.row_in,
            "row_out": job.row_out,
            "row_filtered": job.row_filtered,
        },
    }


@router.post("/tasks/{job_id}/rerun-with-current-rules")
def rerun_clean_task_with_current_rules(
    job_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _heavy_slot=Depends(clean_heavy_slot),
):
    job = _get_visible_clean_job_or_404(db, current_user, job_id)
    ensure_clean_job_idle(db, job_id)
    if db.query(PublishJob.id).filter(PublishJob.clean_job_id == job_id).first():
        raise HTTPException(status_code=400, detail="已发布任务不支持重新处理")

    with _clean_scope_guard(job.category_code or job.dispatch_category_code, job.platform):
        snapshot = _manual_review_snapshot(db, job_id)
        try:
            job.status = "cleaning"
            db.flush()
            _clear_clean_job_outputs(db, job_id)
            row_out = run_clean(
                db,
                job.id,
                job.file_ids or [],
                job.rules or {},
                job.dispatch_batch_id,
                job.dispatch_category_code or job.category_code,
                commit=False,
            )
            job.row_out = row_out
            job.status = "matching"
            db.flush()
            run_match(db, job.id, commit=False)
            restored_confirmed_count, restored_review_count, restored_ids = _restore_manual_reviews(db, job.id, snapshot)
            _finalize_rerun_metadata(db, job.id, restored_ids)
            job.status = "reviewing"
            db.flush()
            db.commit()
            db.refresh(job)
        except Exception as e:
            db.rollback()
            failed_job = db.query(CleanJobRecord).filter(CleanJobRecord.id == job_id).first()
            if failed_job:
                failed_job.status = "failed"
                db.commit()
            raise HTTPException(status_code=500, detail=f"重新处理任务失败: {str(e)}") from e

        counts = _match_status_counts(db, job.id)
        filtered_count = db.query(FilteredItem).filter(FilteredItem.clean_job_id == job.id).count()
        invalidate_clean_pool_cache()
        return {
            "clean_job_id": job.id,
            "row_out": job.row_out or 0,
            "filtered_count": filtered_count,
            "matched_count": counts.get("matched", 0) + counts.get("url_matched", 0) + counts.get("confirmed", 0),
            "restored_confirmed_count": restored_confirmed_count,
            "restored_review_count": restored_review_count,
            "pending_count": counts.get("pending", 0) + counts.get("text_only", 0) + counts.get("disputed", 0),
        }


@router.post("/run", response_model=CleanJobOut)
def run_clean_job(
    payload: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _heavy_slot=Depends(clean_heavy_slot),
):
    """
    执行数据清洗任务。
    payload: {
      "file_ids": [1,2],
      "rules": { "dedup": true },
      "dispatch_batch_id": 1,          // 可选
      "dispatch_category_code": "SPK"  // 可选
    }
    """
    file_ids: list[int] = payload.get("file_ids", [])
    rules: dict = payload.get("rules", {"dedup": True})
    dispatch_batch_id: int | None = payload.get("dispatch_batch_id")
    dispatch_category_code: str | None = payload.get("dispatch_category_code")
    _ensure_clean_category_visible(db, current_user, dispatch_category_code)

    if not file_ids:
        raise HTTPException(status_code=400, detail="file_ids 不能为空")

    # 统计输入行数
    from app.models.schemas import RawDataRecord, DispatchItem
    if dispatch_batch_id and dispatch_category_code:
        raw_data_ids = (
            db.query(DispatchItem.raw_data_id)
            .filter(
                DispatchItem.batch_id == dispatch_batch_id,
                DispatchItem.category_code == dispatch_category_code,
            )
            .subquery()
        )
        row_in = db.query(RawDataRecord).filter(RawDataRecord.id.in_(raw_data_ids)).count()
    else:
        row_in = db.query(RawDataRecord).filter(RawDataRecord.file_id.in_(file_ids)).count()

    # 创建 job 记录
    job = CleanJobRecord(
        file_ids=file_ids,
        rules=rules,
        status="processing",
        row_in=row_in,
        row_out=0,
        dispatch_batch_id=dispatch_batch_id,
        dispatch_category_code=dispatch_category_code,
    )
    db.add(job)
    db.flush()

    try:
        row_out = run_clean(db, job.id, file_ids, rules, dispatch_batch_id, dispatch_category_code)
        job.row_out = row_out
        job.status = "done"
        db.commit()
        db.refresh(job)
    except Exception as e:
        job.status = "error"
        db.commit()
        raise HTTPException(status_code=500, detail=f"清洗失败: {str(e)}")

    return job


@router.post("/run-dispatch-batch")
def run_dispatch_batch_clean(
    payload: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _heavy_slot=Depends(clean_heavy_slot),
):
    dispatch_batch_id: int | None = payload.get("dispatch_batch_id")
    rules: dict = payload.get("rules", {"dedup": True})

    if not dispatch_batch_id:
        raise HTTPException(status_code=400, detail="dispatch_batch_id 不能为空")

    batch = db.query(DispatchBatch).filter(DispatchBatch.id == dispatch_batch_id).first()
    if not batch:
        raise HTTPException(status_code=404, detail="分发批次不存在")
    if batch.status != "done":
        raise HTTPException(status_code=400, detail="只能清洗已完成的分发批次")
    if not batch.file_id:
        raise HTTPException(status_code=400, detail="分发批次缺少文件信息")

    category_codes = [
        row[0]
        for row in db.query(DispatchItem.category_code)
        .filter(DispatchItem.batch_id == dispatch_batch_id)
        .distinct()
        .order_by(DispatchItem.category_code)
        .all()
    ]
    visible_codes = _visible_clean_category_codes(db, current_user)
    if visible_codes is not None:
        category_codes = [code for code in category_codes if code in visible_codes]
    if not category_codes:
        raise HTTPException(status_code=400, detail="分发批次没有可清洗的类目")

    jobs = []
    for category_code in category_codes:
        job = _run_clean_for_dispatch_category(db, batch.file_id, rules, dispatch_batch_id, category_code)
        jobs.append(job)

    return {
        "dispatch_batch_id": dispatch_batch_id,
        "jobs": [CleanJobOut.model_validate(job) for job in jobs],
    }


@router.get("/jobs")
def list_clean_jobs(
    category_code: Optional[str] = Query(None),
    platform: Optional[str] = Query(None),
    month: Optional[int] = Query(None),
    view: str = Query("active", pattern="^(active|archived|all)$"),
    sort_by: str = Query("created_at", pattern="^(created_at|updated_at)$"),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    limit: Optional[int] = Query(None, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    visible_codes = _visible_clean_category_codes(db, current_user)
    q = db.query(CleanJobRecord)
    q = _filter_clean_job_visible_categories(q, db, current_user, visible_codes)
    if view == "active":
        q = q.filter(CleanJobRecord.status != "archived")
    elif view == "archived":
        q = q.filter(CleanJobRecord.status == "archived")
    if category_code:
        q = q.filter(CleanJobRecord.category_code == category_code)
    if platform:
        q = q.filter(func.lower(CleanJobRecord.platform) == platform.lower())
    sort_col = CleanJobRecord.updated_at if sort_by == "updated_at" else CleanJobRecord.created_at
    q = q.order_by(sort_col.desc() if order == "desc" else sort_col.asc())
    if month is None:
        if offset:
            q = q.offset(offset)
        if limit is not None:
            q = q.limit(limit)
        jobs = q.all()
    else:
        jobs = [job for job in q.all() if _job_month(job) == month]
        if offset:
            jobs = jobs[offset:]
        if limit is not None:
            jobs = jobs[:limit]

    category_codes = {
        code
        for job in jobs
        for code in (job.category_code, job.dispatch_category_code)
        if code
    }
    category_names = {
        category.code: category.name
        for category in db.query(Category).filter(Category.code.in_(category_codes)).all()
    } if category_codes else {}

    job_ids = [job.id for job in jobs]
    counts_by_job: dict[int, dict[str, int]] = {job_id: {} for job_id in job_ids}
    if job_ids:
        rows = (
            db.query(MatchResult.clean_job_id, MatchResult.match_status, func.count(MatchResult.id))
            .filter(MatchResult.clean_job_id.in_(job_ids))
            .group_by(MatchResult.clean_job_id, MatchResult.match_status)
            .all()
        )
        for job_id, status, count in rows:
            counts_by_job.setdefault(job_id, {})[status] = count

    runs = {run.clean_job_id: run for run in db.query(CleanTaskRun).filter(CleanTaskRun.clean_job_id.in_(job_ids)).all()} if job_ids else {}
    result = []
    for job in jobs:
        row = _clean_job_to_dict(db, job, counts_by_job.get(job.id, {}), category_names)
        run = runs.get(job.id)
        if run:
            row.update(execution_mode=run.mode, execution_input_count=run.input_count,
                       progress_stage=run.stage, progress_processed=run.processed, progress_total=run.total,
                       can_retry=run.state == "failed" and job.status == "failed")
        result.append(row)
    return result


@router.delete("/jobs/{job_id}")
def delete_clean_job(
    job_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    job = _get_visible_clean_job_or_404(db, current_user, job_id)
    ensure_clean_job_idle(db, job_id, allow_failed=True)
    job.status = "archived"
    db.commit()
    db.refresh(job)
    invalidate_clean_pool_cache()
    return _clean_job_to_dict(db, job)


@router.get("/jobs/{job_id}/preview")
def preview_clean_job(
    job_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _get_visible_clean_job_or_404(db, current_user, job_id)

    q = db.query(CleanedDataRecord).filter(CleanedDataRecord.clean_job_id == job_id)
    total = q.count()
    items = q.offset((page - 1) * page_size).limit(page_size).all()
    rates = build_rate_map(db)

    def _item(r: CleanedDataRecord) -> dict:
        info = rates.get(r.country_code or "")
        rate = info["rate_to_cny"] if info else None
        return {
            "id": r.id,
            "clean_job_id": r.clean_job_id,
            "country_code": r.country_code,
            "currency_code": info["currency_code"] if info else None,
            "exchange_rate": rate,
            "platform": r.platform,
            "month": r.month,
            "category_lv1": r.category_lv1,
            "category_lv2": r.category_lv2,
            "item_id": r.item_id,
            "item_name": r.item_name,
            "item_url": r.item_url,
            "ref_price": float(r.ref_price) if r.ref_price is not None else None,
            "ref_price_cny": amount_to_cny(r.ref_price, rate),
            "brand_raw": r.brand_raw,
            "shop_name": r.shop_name,
            "sales_qty": r.sales_qty,
            "sales_amount": float(r.sales_amount) if r.sales_amount is not None else None,
            "sales_amount_cny": amount_to_cny(r.sales_amount, rate),
            "price": float(r.price) if r.price is not None else None,
            "price_cny": amount_to_cny(r.price, rate),
            "brand_std": r.brand_std,
            "model_std": r.model_std,
        }

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "rates": rates,
        "items": [_item(r) for r in items],
    }


@router.get("/jobs/{job_id}/matched")
def list_clean_job_matched(
    job_id: int,
    group: str = Query("mapping", pattern="^(mapping|interference_link|interference_archive|duplicates)$"),
    keyword: Optional[str] = Query(None),
    price_min: Optional[float] = Query(None, ge=0),
    price_max: Optional[float] = Query(None, ge=0),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """查看清洗任务已匹配到的数据，按来源分开：
    - mapping：匹配到型号的结果（matched/url_matched/confirmed）
    - interference_link：命中干扰链接库被剔除的数据
    - interference_archive：命中干扰项规则被存档的数据
    - duplicates：清洗去重时实际记录的重复行及其保留行

    支持按价格区间筛选（price_min / price_max，单位为元）。
    """
    job = _get_visible_clean_job_or_404(db, current_user, job_id)

    mapping_count = (
        db.query(func.count(MatchResult.id))
        .filter(
            MatchResult.clean_job_id == job_id,
            MatchResult.match_status.in_(["matched", "url_matched", "confirmed"]),
        )
        .scalar()
        or 0
    )
    interference_link_count = (
        db.query(func.count(FilteredItem.id))
        .filter(
            FilteredItem.clean_job_id == job_id,
            FilteredItem.is_recovered == 0,
            FilteredItem.intervention_rule_id.is_(None),
        )
        .scalar()
        or 0
    )
    interference_archive_count = (
        db.query(func.count(FilteredItem.id))
        .filter(
            FilteredItem.clean_job_id == job_id,
            FilteredItem.is_recovered == 0,
            FilteredItem.intervention_rule_id.isnot(None),
        )
        .scalar()
        or 0
    )
    counts = {
        "mapping": mapping_count,
        "interference_link": interference_link_count,
        "interference_archive": interference_archive_count,
        "duplicates": db.query(CleanDuplicateRecord).filter_by(clean_job_id=job_id).count(),
    }

    kw = (keyword or "").strip()

    def _apply_price_filter(query):
        if price_min is not None:
            query = query.filter(RawDataRecord.price >= price_min)
        if price_max is not None:
            query = query.filter(RawDataRecord.price <= price_max)
        return query

    if group == "mapping":
        q = (
            db.query(MatchResult, RawDataRecord, ModelRecord)
            .join(RawDataRecord, MatchResult.raw_data_id == RawDataRecord.id)
            .outerjoin(ModelRecord, MatchResult.model_id == ModelRecord.id)
            .filter(
                MatchResult.clean_job_id == job_id,
                MatchResult.match_status.in_(["matched", "url_matched", "confirmed"]),
            )
        )
        if kw:
            q = q.filter(RawDataRecord.item_name.ilike(f"%{kw}%"))
        q = _apply_price_filter(q)
        total = q.count()
        rows = q.order_by(MatchResult.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
        rates = build_rate_map(db)
        items = []
        for mr, rd, model in rows:
            info = rates.get(rd.country_code or "")
            rate = info["rate_to_cny"] if info else None
            items.append({
                "id": mr.id,
                "raw_data_id": mr.raw_data_id,
                "match_status": mr.match_status,
                "match_source": mr.match_source,
                "model_code": model.model_code if model else None,
                "brand_code": model.brand_code if model else None,
                "series": model.series if model else None,
                "item_name": rd.item_name,
                "item_url": rd.item_url,
                "brand_raw": rd.brand_raw,
                "shop_name": rd.shop_name,
                "platform": rd.platform,
                "item_id": rd.item_id,
                "country_code": rd.country_code,
                "currency_code": info["currency_code"] if info else None,
                "exchange_rate": rate,
                "price": float(rd.price) if rd.price is not None else None,
                "price_cny": amount_to_cny(rd.price, rate),
                "sales_qty": rd.sales_qty,
                "sales_amount": float(rd.sales_amount) if rd.sales_amount is not None else None,
                "sales_amount_cny": amount_to_cny(rd.sales_amount, rate),
            })
    elif group == "duplicates":
        kept = aliased(RawDataRecord)
        q = (
            db.query(CleanDuplicateRecord, RawDataRecord, kept)
            .join(RawDataRecord, RawDataRecord.id == CleanDuplicateRecord.raw_data_id)
            .outerjoin(kept, kept.id == CleanDuplicateRecord.kept_raw_data_id)
            .filter(CleanDuplicateRecord.clean_job_id == job_id)
        )
        if kw:
            q = q.filter(or_(RawDataRecord.item_name.ilike(f"%{kw}%"), kept.item_name.ilike(f"%{kw}%")))
        q = _apply_price_filter(q)
        total = q.count()
        rows = q.order_by(CleanDuplicateRecord.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
        items = [dict(
            id=entry.id, raw_data_id=raw.id, item_name=raw.item_name, item_url=raw.item_url,
            item_id=raw.item_id, platform=raw.platform, brand_raw=raw.brand_raw,
            shop_name=raw.shop_name, month=raw.month, file_id=raw.file_id,
            price=float(raw.price) if raw.price is not None else None,
            sales_qty=raw.sales_qty, sales_amount=float(raw.sales_amount) if raw.sales_amount is not None else None,
            kept_raw_data_id=entry.kept_raw_data_id, kept_item_name=retained.item_name if retained else None,
            kept_item_url=retained.item_url if retained else None, kept_file_id=retained.file_id if retained else None,
            dedup_basis=entry.dedup_basis, dedup_key=entry.dedup_key,
            created_at=format_beijing_datetime(entry.created_at),
        ) for entry, raw, retained in rows]
    else:
        q = (
            db.query(FilteredItem, RawDataRecord)
            .join(RawDataRecord, FilteredItem.raw_data_id == RawDataRecord.id)
            .filter(
                FilteredItem.clean_job_id == job_id,
                FilteredItem.is_recovered == 0,
            )
        )
        if group == "interference_link":
            q = q.filter(FilteredItem.intervention_rule_id.is_(None))
        else:
            q = q.filter(FilteredItem.intervention_rule_id.isnot(None))
        if kw:
            q = q.filter(RawDataRecord.item_name.ilike(f"%{kw}%"))
        q = _apply_price_filter(q)
        total = q.count()
        rows = q.order_by(FilteredItem.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
        rates = build_rate_map(db)
        items = [
            {
                "id": fi.id,
                "raw_data_id": fi.raw_data_id,
                "matched_keyword": fi.matched_keyword,
                "intervention_rule_name": fi.intervention_rule_name,
                "matched_reason": fi.matched_reason,
                "item_name": rd.item_name,
                "item_url": rd.item_url,
                "brand_raw": rd.brand_raw,
                "shop_name": rd.shop_name,
                "platform": rd.platform,
                "item_id": rd.item_id,
                "country_code": rd.country_code,
                "currency_code": (rates.get(rd.country_code or "") or {}).get("currency_code"),
                "price": float(rd.price) if rd.price is not None else None,
                "price_cny": amount_to_cny(rd.price, (rates.get(rd.country_code or "") or {}).get("rate_to_cny")),
                "sales_qty": rd.sales_qty,
                "sales_amount": float(rd.sales_amount) if rd.sales_amount is not None else None,
                "sales_amount_cny": amount_to_cny(rd.sales_amount, (rates.get(rd.country_code or "") or {}).get("rate_to_cny")),
                "created_at": format_beijing_datetime(fi.created_at),
            }
            for fi, rd in rows
        ]

    return {
        "group": group,
        "counts": counts,
        "accounting": clean_accounting(
            job, db.query(CleanedDataRecord).filter_by(clean_job_id=job_id).count(),
            interference_link_count + interference_archive_count, counts["duplicates"],
        ),
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": items,
    }


class BrandCleanRow(BaseModel):
    cleaned_data_id: int
    raw_data_id: int
    match_id: int | None = None
    platform: str | None = None
    item_name: str | None = None
    brand_raw: str | None = None
    brand_std: str | None = None
    sales_qty: int | None = None
    model_brand_code: str | None = None
    model_brand_name: str | None = None
    has_model: bool = False
    brand_identified: int = 1
    brand_std_manual: bool = False
    editable: bool = False


class BrandCleanListOut(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[BrandCleanRow]


class BrandCleanUpdateItem(BaseModel):
    cleaned_data_id: int
    brand_std: str | None = None


class BrandCleanUpdateIn(BaseModel):
    items: list[BrandCleanUpdateItem]


@router.get("/jobs/{job_id}/brand-rows", response_model=BrandCleanListOut)
def list_clean_job_brand_rows(
    job_id: int,
    keyword: Optional[str] = Query(None),
    search_by: str = Query("item_name", description="搜索字段：item_name/brand_raw/brand_code/shop_name/model_code"),
    group: str = Query(
        "actionable",
        description="筛选分类：actionable=待处理 / unidentified_brand=未识别品牌 / "
                    "pending=待确认 / text_only=URL映射待确认 / disputed=争议复核 / all=全部",
    ),
    sort_by: str = Query("default", description="排序：default/item_name_asc/item_name_desc/sales_qty_desc/sales_qty_asc/price_desc/price_asc"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """「只清洗品牌」列表：返回该清洗任务的数据行（cleaned_data），
    附带原品牌、当前入库品牌、已匹配型号的品牌，并标记该行是否可人工补充/覆盖品牌。"""
    _get_visible_clean_job_or_404(db, current_user, job_id)

    q = (
        db.query(CleanedDataRecord, RawDataRecord)
        .join(RawDataRecord, CleanedDataRecord.raw_data_id == RawDataRecord.id)
        .filter(CleanedDataRecord.clean_job_id == job_id)
    )

    if group == "unidentified_brand":
        group_cond = and_(
            MatchResult.match_status == "pending",
            MatchResult.brand_identified == 0,
            MatchResult.is_disabled == 0,
        )
    elif group == "pending":
        group_cond = and_(MatchResult.match_status == "pending", MatchResult.is_disabled == 0)
    elif group == "text_only":
        group_cond = and_(MatchResult.match_status == "text_only", MatchResult.is_disabled == 0)
    elif group == "disputed":
        group_cond = and_(MatchResult.match_status == "disputed", MatchResult.is_disabled == 0)
    elif group == "all":
        group_cond = None
    else:  # actionable
        group = "actionable"
        group_cond = and_(
            MatchResult.match_status.in_(BRAND_CLEAN_ACTIONABLE_STATUSES),
            MatchResult.is_disabled == 0,
        )
    if group_cond is not None:
        group_exists = (
            db.query(MatchResult.id)
            .filter(
                MatchResult.clean_job_id == job_id,
                MatchResult.raw_data_id == CleanedDataRecord.raw_data_id,
                group_cond,
            )
            .correlate(CleanedDataRecord)
            .exists()
        )
        q = q.filter(group_exists)

    allowed_search_fields = {"item_name", "brand_raw", "brand_code", "shop_name", "model_code"}
    if search_by not in allowed_search_fields:
        search_by = "item_name"
    kw = (keyword or "").strip()
    if kw:
        pattern = f"%{kw}%"
        if search_by == "brand_raw":
            q = q.filter(RawDataRecord.brand_raw.ilike(pattern))
        elif search_by == "shop_name":
            q = q.filter(RawDataRecord.shop_name.ilike(pattern))
        elif search_by == "model_code":
            model_exists = (
                db.query(MatchResult.id)
                .outerjoin(ModelRecord, MatchResult.model_id == ModelRecord.id)
                .filter(
                    MatchResult.clean_job_id == job_id,
                    MatchResult.raw_data_id == CleanedDataRecord.raw_data_id,
                    ModelRecord.model_code.ilike(pattern),
                )
                .correlate(CleanedDataRecord)
                .exists()
            )
            q = q.filter(model_exists)
        elif search_by == "brand_code":
            model_exists = (
                db.query(MatchResult.id)
                .outerjoin(ModelRecord, MatchResult.model_id == ModelRecord.id)
                .outerjoin(BrandRecord, BrandRecord.brand_code == ModelRecord.brand_code)
                .filter(
                    MatchResult.clean_job_id == job_id,
                    MatchResult.raw_data_id == CleanedDataRecord.raw_data_id,
                    or_(ModelRecord.brand_code.ilike(pattern), BrandRecord.brand_name.ilike(pattern)),
                )
                .correlate(CleanedDataRecord)
                .exists()
            )
            # 人工补充的品牌存的是品牌码（cleaned_data.brand_std），
            # 这里把匹配到的品牌码也纳入，保证按中文品牌名也能搜到。
            matched_brand_codes = select(BrandRecord.brand_code).where(
                or_(BrandRecord.brand_code.ilike(pattern), BrandRecord.brand_name.ilike(pattern))
            )
            q = q.filter(or_(
                CleanedDataRecord.brand_std.ilike(pattern),
                CleanedDataRecord.brand_std.in_(matched_brand_codes),
                model_exists,
            ))
        else:  # item_name
            q = q.filter(RawDataRecord.item_name.ilike(pattern))

    if sort_by == "sales_qty_desc":
        q = q.order_by(case((RawDataRecord.sales_qty.is_(None), 1), else_=0), RawDataRecord.sales_qty.desc())
    elif sort_by == "sales_qty_asc":
        q = q.order_by(case((RawDataRecord.sales_qty.is_(None), 1), else_=0), RawDataRecord.sales_qty.asc())
    elif sort_by == "price_desc":
        q = q.order_by(case((RawDataRecord.price.is_(None), 1), else_=0), RawDataRecord.price.desc())
    elif sort_by == "price_asc":
        q = q.order_by(case((RawDataRecord.price.is_(None), 1), else_=0), RawDataRecord.price.asc())
    elif sort_by == "item_name_asc":
        q = q.order_by(RawDataRecord.item_name.asc())
    elif sort_by == "item_name_desc":
        q = q.order_by(RawDataRecord.item_name.desc())
    else:
        q = q.order_by(CleanedDataRecord.id)

    total = q.count()
    rows = (
        q.offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    raw_ids = [rd.id for _, rd in rows]
    model_map: dict[int, tuple[str, str | None]] = {}
    identified_map: dict[int, int] = {}
    editable_raw_ids: set[int] = set()
    match_id_map: dict[int, int] = {}
    if raw_ids:
        model_rows = (
            db.query(
                MatchResult.id,
                MatchResult.raw_data_id,
                MatchResult.brand_identified,
                MatchResult.match_status,
                MatchResult.is_disabled,
                ModelRecord.brand_code,
                ModelRecord.brand_name,
            )
            .outerjoin(ModelRecord, MatchResult.model_id == ModelRecord.id)
            .filter(
                MatchResult.clean_job_id == job_id,
                MatchResult.raw_data_id.in_(raw_ids),
            )
            .all()
        )
        for match_id, raw_id, brand_identified, status, is_disabled, brand_code, brand_name in model_rows:
            match_id_map.setdefault(raw_id, match_id)
            identified_map.setdefault(raw_id, 1 if brand_identified is None else brand_identified)
            if status in BRAND_CLEAN_ACTIONABLE_STATUSES and not is_disabled:
                editable_raw_ids.add(raw_id)
            if brand_code is not None or brand_name is not None:
                model_map.setdefault(raw_id, (brand_code, brand_name))

    items = []
    brand_alias_map = _load_brand_alias_map(db)
    for cd, rd in rows:
        matched = model_map.get(rd.id)
        items.append(BrandCleanRow(
            cleaned_data_id=cd.id,
            raw_data_id=rd.id,
            match_id=match_id_map.get(rd.id),
            platform=rd.platform,
            item_name=rd.item_name,
            brand_raw=rd.brand_raw,
            brand_std=cd.brand_std,
            sales_qty=rd.sales_qty,
            model_brand_code=matched[0] if matched else None,
            model_brand_name=matched[1] if matched else None,
            has_model=matched is not None,
            brand_identified=identified_map.get(rd.id, 1),
            brand_std_manual=manual_brand_std(cd, rd, brand_alias_map) is not None,
            editable=rd.id in editable_raw_ids,
        ))
    return BrandCleanListOut(total=total, page=page, page_size=page_size, items=items)


@router.patch("/jobs/{job_id}/brand-rows")
def update_clean_job_brand_rows(
    job_id: int,
    payload: BrandCleanUpdateIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """「只清洗品牌」保存：仅更新 cleaned_data.brand_std（品牌码），
    不写 match_results、不改任务状态与待处理计数。
    已匹配/已人工确认/已排除/已禁用的行跳过不更新；有型号的（如 URL映射待确认）行允许人工覆盖品牌。"""
    _get_visible_clean_job_or_404(db, current_user, job_id)
    ensure_clean_job_idle(db, job_id)
    if not payload.items:
        return {"updated": 0}

    cleaned_ids = [item.cleaned_data_id for item in payload.items]
    rows = (
        db.query(CleanedDataRecord)
        .filter(
            CleanedDataRecord.clean_job_id == job_id,
            CleanedDataRecord.id.in_(cleaned_ids),
        )
        .all()
    )
    found = {cd.id: cd for cd in rows}

    raw_ids = [cd.raw_data_id for cd in rows]
    blocked_raw_ids: set[int] = set()
    if raw_ids:
        blocked_raw_ids = {
            raw_id
            for (raw_id,) in db.query(MatchResult.raw_data_id)
            .filter(
                MatchResult.clean_job_id == job_id,
                MatchResult.raw_data_id.in_(raw_ids),
                or_(
                    MatchResult.match_status.in_(BRAND_CLEAN_RESOLVED_STATUSES),
                    MatchResult.is_disabled == 1,
                ),
            )
            .all()
        }

    to_update: list[tuple[CleanedDataRecord, str | None]] = []
    for item in payload.items:
        cd = found.get(item.cleaned_data_id)
        if cd is None or cd.raw_data_id in blocked_raw_ids:
            continue
        value = (item.brand_std or "").strip() or None
        to_update.append((cd, value))

    codes = {value for _, value in to_update if value}
    if codes:
        valid_codes = {
            code
            for (code,) in db.query(BrandRecord.brand_code)
            .filter(BrandRecord.brand_code.in_(codes))
            .all()
        }
        invalid = codes - valid_codes
        if invalid:
            raise HTTPException(status_code=400, detail=f"品牌不存在: {', '.join(sorted(invalid))}")

    for cd, value in to_update:
        cd.brand_std = value
    db.commit()
    return {"updated": len(to_update)}


class BrandCleanExcludeIn(BaseModel):
    cleaned_data_ids: list[int]
    reason: str | None = None


def _snapshot_prev_state(mr: MatchResult) -> None:
    mr.prev_match_status = mr.match_status
    mr.prev_model_id = mr.model_id
    mr.prev_matched_by = mr.matched_by
    mr.prev_match_source = mr.match_source
    mr.prev_dispute_reason = mr.dispute_reason
    mr.prev_review_note = mr.review_note
    mr.prev_reviewed_at = mr.reviewed_at


@router.post("/jobs/{job_id}/brand-rows/exclude")
def exclude_clean_job_brand_rows(
    job_id: int,
    payload: BrandCleanExcludeIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """「只清洗品牌」一键排除：把所选行标记为已排除（status=excluded），
    并写入排除沉淀库，供后续同品类任务沿用。已匹配/已人工确认/已排除/已禁用的行跳过。"""
    job = _get_visible_clean_job_or_404(db, current_user, job_id)
    ensure_clean_job_idle(db, job_id)
    if not payload.cleaned_data_ids:
        return {"excluded": 0}

    rows = (
        db.query(CleanedDataRecord)
        .filter(
            CleanedDataRecord.clean_job_id == job_id,
            CleanedDataRecord.id.in_(payload.cleaned_data_ids),
        )
        .all()
    )
    raw_ids = [cd.raw_data_id for cd in rows]
    if not raw_ids:
        return {"excluded": 0}

    category_code = job.category_code or job.dispatch_category_code
    reason = (payload.reason or "").strip() or None
    match_rows = (
        db.query(MatchResult, RawDataRecord)
        .join(RawDataRecord, MatchResult.raw_data_id == RawDataRecord.id)
        .filter(
            MatchResult.clean_job_id == job_id,
            MatchResult.raw_data_id.in_(raw_ids),
        )
        .all()
    )

    excluded_count = 0
    now = datetime.utcnow()
    for mr, raw in match_rows:
        if mr.match_status in BRAND_CLEAN_RESOLVED_STATUSES or mr.is_disabled:
            continue
        _snapshot_prev_state(mr)
        mr.match_status = "excluded"
        mr.model_id = None
        mr.matched_by = "manual"
        mr.dispute_reason = None
        mr.review_note = reason
        mr.reviewed_at = now
        upsert_exclusion_for_raw(db, raw, category_code, reason=reason, source="manual")
        excluded_count += 1

    db.commit()
    if excluded_count:
        touch_clean_job(db, job_id)
        db.commit()
    return {"excluded": excluded_count}


class CleanTaskSearchItem(BaseModel):
    id: int
    task_name: str | None = None
    category_code: str | None = None
    category_name: str | None = None
    platform: str | None = None
    month: int | None = None
    status: str
    display_name: str | None = None


@router.get("/tasks/search", response_model=list[CleanTaskSearchItem])
def search_clean_tasks(
    keyword: str = Query("", description="任务名/品类码/品类名/平台关键字，可空"),
    exclude_id: int | None = Query(None, description="排除的 clean_job_id（通常传当前任务）"),
    category_code: str | None = Query(None, description="按品类码精确筛选"),
    platform: str | None = Query(None, description="按平台精确筛选"),
    month: int | None = Query(None, description="按任务月份精确筛选"),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    kw = (keyword or "").strip()
    effective_category_code = func.coalesce(CleanJobRecord.category_code, CleanJobRecord.dispatch_category_code)
    q = (
        db.query(CleanJobRecord, Category)
        .outerjoin(Category, Category.code == effective_category_code)
        .filter(CleanJobRecord.status.in_(ACTIVE_TASK_STATUSES))
    )
    if exclude_id is not None:
        q = q.filter(CleanJobRecord.id != exclude_id)
    if kw:
        like = f"%{kw}%"
        q = q.filter(or_(
            CleanJobRecord.task_name.ilike(like),
            CleanJobRecord.category_code.ilike(like),
            CleanJobRecord.dispatch_category_code.ilike(like),
            CleanJobRecord.platform.ilike(like),
            Category.name.ilike(like),
        ))
    if category_code:
        q = q.filter(or_(
            CleanJobRecord.category_code == category_code,
            CleanJobRecord.dispatch_category_code == category_code,
        ))
    if platform:
        q = q.filter(func.lower(CleanJobRecord.platform) == platform.lower())
    if month is not None:
        month_like = f"%{month}%"
        q = q.filter(or_(
            CleanJobRecord.source_scope.cast(String).ilike(month_like),
            CleanJobRecord.task_name.ilike(month_like),
        ))
    q = q.order_by(CleanJobRecord.created_at.desc()).limit(limit)

    items: list[CleanTaskSearchItem] = []
    for cj, cat in q.all():
        resolved_category_code = cj.category_code or cj.dispatch_category_code
        items.append(CleanTaskSearchItem(
            id=cj.id,
            task_name=cj.task_name,
            category_code=resolved_category_code,
            category_name=cat.name if cat else None,
            platform=cj.platform,
            month=_job_month(cj),
            status=cj.status,
            display_name=_build_clean_scope_desc(db, cj),
        ))
    return items
