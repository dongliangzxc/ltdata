from datetime import datetime
import re
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import String, and_, func, or_, select
from sqlalchemy.orm import Session
from pydantic import BaseModel
from app.core.auth_deps import get_current_user
from app.core.permissions import visible_category_codes
from app.models.database import get_db
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
    User,
)
from app.services.clean_task_snapshot import (
    ACTIVE_TASK_STATUSES,
    create_category_task_snapshot,
    get_clean_pool_summary,
    get_monthly_clean_pool,
    upsert_monthly_task_snapshot,
)
from app.services.data_cleaner import run_clean
from app.services.matcher import run_match
from app.utils.time_utils import format_beijing_datetime

router = APIRouter(prefix="/api/clean", tags=["clean"])


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
        "publishable_count": publishable_count,
        "created_at": format_beijing_datetime(job.created_at),
        "scope_desc": _build_clean_scope_desc(db, job, category_names),
    }


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
            MatchResult.match_status.in_(["confirmed", "excluded"]),
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
        else:
            continue
        mr.matched_by = "manual"
        mr.match_source = "manual"
        mr.review_note = saved.get("review_note")
        mr.reviewed_at = saved.get("reviewed_at") or now
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

    raw_data_ids = select(DispatchItem.raw_data_id).filter(
        DispatchItem.batch_id == dispatch_batch_id,
        DispatchItem.category_code == dispatch_category_code,
    )
    row_in = db.query(RawDataRecord).filter(RawDataRecord.id.in_(raw_data_ids)).count()
    job = CleanJobRecord(
        file_ids=[file_id],
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
        row_out = run_clean(db, job.id, [file_id], rules, dispatch_batch_id, dispatch_category_code)
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
    rows = get_monthly_clean_pool(
        db,
        category_code=category_code,
        platform=platform,
        month=month,
        limit=limit,
    )
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

    return {"job": job, "snapshot_count": snapshot_count, "match_status": "done"}


@router.post("/tasks/upsert-monthly", response_model=UpsertMonthlyCleanTaskOut)
def upsert_monthly_clean_task(
    payload: UpsertMonthlyCleanTaskIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ensure_clean_category_visible(db, current_user, payload.category_code)
    try:
        job, snapshot_count, action, _new_snapshot_ids = upsert_monthly_task_snapshot(
            db,
            category_code=payload.category_code,
            platform=payload.platform,
            month=payload.month,
            rules=payload.rules,
            force_reclean=payload.force_reclean,
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
    q = q.order_by(CleanJobRecord.created_at.desc())
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

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [CleanedDataOut.model_validate(r) for r in items],
    }


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
    q = (
        db.query(CleanJobRecord, Category)
        .outerjoin(Category, CleanJobRecord.category_code == Category.code)
        .filter(CleanJobRecord.status.in_(ACTIVE_TASK_STATUSES))
    )
    q = _filter_clean_job_visible_categories(q, db, current_user)
    if exclude_id is not None:
        q = q.filter(CleanJobRecord.id != exclude_id)
    if kw:
        like = f"%{kw}%"
        q = q.filter(or_(
            CleanJobRecord.task_name.ilike(like),
            CleanJobRecord.category_code.ilike(like),
            CleanJobRecord.platform.ilike(like),
            Category.name.ilike(like),
        ))
    if category_code:
        q = q.filter(CleanJobRecord.category_code == category_code)
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
        items.append(CleanTaskSearchItem(
            id=cj.id,
            task_name=cj.task_name,
            category_code=cj.category_code,
            category_name=cat.name if cat else None,
            platform=cj.platform,
            month=_job_month(cj),
            status=cj.status,
            display_name=_build_clean_scope_desc(db, cj),
        ))
    return items
