from datetime import datetime
import re
import sys
import threading
import time
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import String, and_, case, func, or_, select
from sqlalchemy.orm import Session
from pydantic import BaseModel
from app.core.auth_deps import get_current_user
from app.core.permissions import visible_category_codes
from app.services.currency_service import amount_to_cny, build_rate_map
from app.models.database import get_db
from app.models.analytics_db import AnalyticsSession
from app.models.schemas import (
    CleanJobRecord,
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
    MatchResultCandidate,
    ModelRecord,
    ItemUrlMapping,
    PublishJob,
    RawDataRecord,
    UploadFileRecord,
    Category,
    CleanJobItemRecord,
    BrandRecord,
    User,
)
from app.services.clean_task_snapshot import (
    ACTIVE_TASK_STATUSES,
    _find_monthly_job,
    _has_reviewed_or_published_state,
    create_category_task_snapshot,
    get_clean_pool_summary,
    get_monthly_clean_pool,
    touch_clean_job,
    upsert_monthly_task_snapshot,
)
from app.services.exclusion_store import upsert_exclusion_for_raw
from app.services.data_cleaner import run_clean, _load_brand_alias_map, manual_brand_std
from app.services.matcher import run_match
from app.services.publisher import delete_published_data
from app.utils.time_utils import format_beijing_datetime

router = APIRouter(prefix="/api/clean", tags=["clean"])

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
        "dispatch_batch_id": job.dispatch_batch_id,
        "dispatch_category_code": job.dispatch_category_code,
        "task_name": job.task_name,
        "category_code": job.category_code or job.dispatch_category_code,
        "platform": job.platform,
        "month": _job_month(job),
        "source_scope": job.source_scope,
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


def _maybe_commit_and_refresh(db: Session, job: CleanJobRecord, commit: bool) -> None:
    if commit:
        db.commit()
        db.refresh(job)
    else:
        db.flush()


def _run_clean_and_match_for_job(db: Session, job: CleanJobRecord, commit: bool = True) -> None:
    job.status = "cleaning"
    _maybe_commit_and_refresh(db, job, commit)

    _clear_clean_job_outputs(db, job.id)
    _maybe_commit_and_refresh(db, job, commit)

    row_out = run_clean(
        db,
        job.id,
        job.file_ids or [],
        job.rules or {},
        job.dispatch_batch_id,
        job.dispatch_category_code or job.category_code,
        commit=commit,
    )
    job.row_out = row_out
    job.status = "matching"
    _maybe_commit_and_refresh(db, job, commit)

    run_match(db, job.id, commit=commit)
    job.status = "reviewing"
    _maybe_commit_and_refresh(db, job, commit)


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
    try:
        job, snapshot_count = create_category_task_snapshot(
            db,
            category_code=payload.category_code,
            platform=payload.platform,
            dispatch_batch_id=payload.dispatch_batch_id,
            task_name=payload.task_name,
            rules=payload.rules,
            force_reclean=payload.force_reclean,
        )
        db.commit()
        db.refresh(job)
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
    try:
        if payload.force_rebuild:
            existing = _find_monthly_job(
                db,
                category_code=payload.category_code,
                platform=payload.platform,
                month=payload.month,
            )
            if existing and _has_reviewed_or_published_state(db, existing.id):
                _reset_clean_job_downstream(db, existing.id)
        job, snapshot_count, action, _new_snapshot_ids = upsert_monthly_task_snapshot(
            db,
            category_code=payload.category_code,
            platform=payload.platform,
            month=payload.month,
            rules=payload.rules,
            force_reclean=payload.force_reclean,
            force_rebuild=payload.force_rebuild,
        )
        _run_clean_and_match_for_job(db, job, commit=False)
        db.commit()
        db.refresh(job)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"更新清洗任务失败: {str(e)}") from e

    invalidate_clean_pool_cache()
    return {"job": job, "snapshot_count": snapshot_count, "action": action, "match_status": "done"}


@router.post("/tasks/{job_id}/rerun-with-current-rules")
def rerun_clean_task_with_current_rules(
    job_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    job = _get_visible_clean_job_or_404(db, current_user, job_id)
    if db.query(PublishJob.id).filter(PublishJob.clean_job_id == job_id).first():
        raise HTTPException(status_code=400, detail="已发布任务不支持重新处理")

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

    return [
        _clean_job_to_dict(db, job, counts_by_job.get(job.id, {}), category_names)
        for job in jobs
    ]


@router.delete("/jobs/{job_id}")
def delete_clean_job(
    job_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    job = _get_visible_clean_job_or_404(db, current_user, job_id)
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
    group: str = Query("mapping", pattern="^(mapping|interference_link|interference_archive)$"),
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

    支持按价格区间筛选（price_min / price_max，单位为元）。
    """
    _get_visible_clean_job_or_404(db, current_user, job_id)

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
