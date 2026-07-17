from datetime import datetime

from sqlalchemy import and_, case, func, or_
from sqlalchemy.orm import Session

from app.models.schemas import (
    Category,
    CleanJobItemRecord,
    CleanJobRecord,
    DispatchItem,
    MatchResult,
    MatchResultAttr,
    PublishJob,
    RawDataRecord,
)


ACTIVE_TASK_STATUSES = {"created", "cleaning", "matching", "reviewing", "processing", "done"}

_PLATFORM_ALIAS_GROUPS = {
    "jd": {"jd", "jingdong", "京东"},
    "tmall": {"tmall", "天猫"},
    "taobao": {"taobao", "淘宝", "tb"},
}

_PLATFORM_ALIASES = {
    alias: canonical
    for canonical, aliases in _PLATFORM_ALIAS_GROUPS.items()
    for alias in aliases
}


def normalize_platform(platform):
    if platform is None:
        return None
    value = str(platform).strip().lower()
    if not value:
        return None
    return _PLATFORM_ALIASES.get(value, value)


def platform_aliases_for(canonical):
    normalized = normalize_platform(canonical)
    if normalized is None:
        return set()
    return _PLATFORM_ALIAS_GROUPS.get(normalized, {normalized})


def _platform_label_expr():
    platform = func.lower(RawDataRecord.platform)
    return case(
        *[
            (platform.in_(aliases), canonical)
            for canonical, aliases in _PLATFORM_ALIAS_GROUPS.items()
        ],
        else_=platform,
    )


def _deduped_dispatch_item_ids(
    db: Session,
    category_code: str | None = None,
    dispatch_batch_id: int | None = None,
):
    dispatch_item_ids = db.query(
        func.min(DispatchItem.id).label("dispatch_item_id"),
    )
    if category_code:
        dispatch_item_ids = dispatch_item_ids.filter(DispatchItem.category_code == category_code)
    if dispatch_batch_id is not None:
        dispatch_item_ids = dispatch_item_ids.filter(DispatchItem.batch_id == dispatch_batch_id)
    return dispatch_item_ids.group_by(
        DispatchItem.raw_data_id,
        DispatchItem.category_code,
    ).subquery()


def _pending_dispatch_query(
    db: Session,
    category_code: str | None = None,
    platform: str | None = None,
    dispatch_batch_id: int | None = None,
):
    deduped_dispatch_item_ids = _deduped_dispatch_item_ids(db, category_code, dispatch_batch_id)

    q = (
        db.query(DispatchItem, RawDataRecord)
        .join(deduped_dispatch_item_ids, DispatchItem.id == deduped_dispatch_item_ids.c.dispatch_item_id)
        .join(RawDataRecord, RawDataRecord.id == DispatchItem.raw_data_id)
        .outerjoin(
            CleanJobItemRecord,
            and_(
                CleanJobItemRecord.raw_data_id == DispatchItem.raw_data_id,
                CleanJobItemRecord.category_code == DispatchItem.category_code,
            ),
        )
        .filter(CleanJobItemRecord.id.is_(None))
    )

    normalized_platform = normalize_platform(platform)
    if normalized_platform:
        q = q.filter(func.lower(RawDataRecord.platform).in_(platform_aliases_for(normalized_platform)))

    return q


def _job_months(job: CleanJobRecord) -> list[int]:
    scope = job.source_scope
    if not isinstance(scope, dict):
        return []
    months = scope.get("months")
    if not isinstance(months, list):
        return []
    parsed = []
    for month in months:
        try:
            parsed.append(int(month))
        except (TypeError, ValueError):
            continue
    return parsed


def _find_monthly_job(
    db: Session,
    *,
    category_code: str,
    platform: str | None,
    month: int,
) -> CleanJobRecord | None:
    normalized_platform = normalize_platform(platform)
    platform_aliases = platform_aliases_for(normalized_platform)
    if not platform_aliases:
        return None
    candidates = (
        db.query(CleanJobRecord)
        .filter(
            CleanJobRecord.category_code == category_code,
            func.lower(CleanJobRecord.platform).in_(platform_aliases),
        )
        .order_by(CleanJobRecord.id.desc())
        .all()
    )
    for job in candidates:
        if month in _job_months(job):
            return job
    return None


def _monthly_pending_rows(
    db: Session,
    *,
    category_code: str | None = None,
    platform: str | None = None,
    month: int | None = None,
):
    q = _pending_dispatch_query(db, category_code=category_code, platform=platform)
    if month is not None:
        q = q.filter(RawDataRecord.month == month)
    return q


def get_clean_pool_summary(db: Session, dispatch_batch_id: int | None = None) -> list[dict]:
    platform_label = _platform_label_expr()
    current_batch_count = func.count(DispatchItem.id)
    deduped_dispatch_item_ids = _deduped_dispatch_item_ids(db, dispatch_batch_id=dispatch_batch_id)
    q = (
        db.query(
            DispatchItem.category_code.label("category_code"),
            Category.name.label("category_name"),
            platform_label.label("platform"),
            current_batch_count.label("current_batch_count"),
        )
        .join(deduped_dispatch_item_ids, DispatchItem.id == deduped_dispatch_item_ids.c.dispatch_item_id)
        .join(RawDataRecord, RawDataRecord.id == DispatchItem.raw_data_id)
        .join(Category, Category.code == DispatchItem.category_code)
    )

    grouped_rows = (
        q.group_by(DispatchItem.category_code, Category.name, platform_label)
        .order_by(current_batch_count.desc(), DispatchItem.category_code, platform_label)
        .all()
    )

    result = []
    for row in grouped_rows:
        platform = normalize_platform(row.platform)
        pending_count = _pending_dispatch_query(
            db,
            category_code=row.category_code,
            platform=platform,
            dispatch_batch_id=dispatch_batch_id,
        ).count()
        active_job_count = (
            db.query(CleanJobRecord)
            .filter(
                CleanJobRecord.category_code == row.category_code,
                CleanJobRecord.status.in_(ACTIVE_TASK_STATUSES),
                or_(
                    CleanJobRecord.platform == platform,
                    CleanJobRecord.platform.is_(None),
                ),
            )
            .count()
        )
        result.append({
            "category_code": row.category_code,
            "category_name": row.category_name,
            "platform": platform,
            "current_batch_count": row.current_batch_count,
            "pending_count": pending_count,
            "active_job_count": active_job_count,
        })

    return result


def _monthly_jobs_by_scope(
    db: Session,
    *,
    category_code: str | None = None,
    platform: str | None = None,
) -> dict[tuple[str, str, int], CleanJobRecord]:
    q = db.query(CleanJobRecord).filter(CleanJobRecord.category_code.isnot(None))
    if category_code:
        q = q.filter(CleanJobRecord.category_code == category_code)
    normalized_platform = normalize_platform(platform)
    if normalized_platform:
        q = q.filter(func.lower(CleanJobRecord.platform).in_(platform_aliases_for(normalized_platform)))

    jobs_by_scope: dict[tuple[str, str, int], CleanJobRecord] = {}
    for job in q.order_by(CleanJobRecord.id.desc()).all():
        job_platform = normalize_platform(job.platform)
        if not job.category_code or not job_platform:
            continue
        for job_month in _job_months(job):
            jobs_by_scope.setdefault((job.category_code, job_platform, job_month), job)
    return jobs_by_scope


def get_monthly_clean_pool(
    db: Session,
    *,
    category_code: str | None = None,
    platform: str | None = None,
    month: int | None = None,
    limit: int | None = None,
) -> list[dict]:
    platform_label = _platform_label_expr()
    q = (
        db.query(
            DispatchItem.category_code.label("category_code"),
            Category.name.label("category_name"),
            platform_label.label("platform"),
            RawDataRecord.month.label("month"),
            func.count(func.distinct(DispatchItem.raw_data_id)).label("pending_count"),
        )
        .join(RawDataRecord, RawDataRecord.id == DispatchItem.raw_data_id)
        .join(Category, Category.code == DispatchItem.category_code)
        .outerjoin(
            CleanJobItemRecord,
            and_(
                CleanJobItemRecord.raw_data_id == DispatchItem.raw_data_id,
                CleanJobItemRecord.category_code == DispatchItem.category_code,
            ),
        )
        .filter(CleanJobItemRecord.id.is_(None), RawDataRecord.month.isnot(None))
    )
    if category_code:
        q = q.filter(DispatchItem.category_code == category_code)
    normalized_filter_platform = normalize_platform(platform)
    if normalized_filter_platform:
        q = q.filter(func.lower(RawDataRecord.platform).in_(platform_aliases_for(normalized_filter_platform)))
    if month is not None:
        q = q.filter(RawDataRecord.month == month)

    grouped_query = (
        q.group_by(DispatchItem.category_code, Category.name, platform_label, RawDataRecord.month)
        .order_by(DispatchItem.category_code, platform_label, RawDataRecord.month)
    )
    if limit is not None:
        grouped_query = grouped_query.limit(limit)
    grouped = grouped_query.all()
    jobs_by_scope = _monthly_jobs_by_scope(db, category_code=category_code, platform=platform)

    result = []
    for row in grouped:
        normalized_platform = normalize_platform(row.platform)
        row_month = int(row.month)
        job = jobs_by_scope.get((row.category_code, normalized_platform, row_month))
        result.append({
            "category_code": row.category_code,
            "category_name": row.category_name,
            "platform": normalized_platform,
            "month": row_month,
            "pending_count": row.pending_count,
            "existing_job_id": job.id if job else None,
            "existing_job_name": job.task_name if job else None,
            "existing_job_status": job.status if job else None,
        })
    return result


def _default_task_name(db: Session, category_code: str, platform: str | None) -> str:
    category = db.query(Category).filter(Category.code == category_code).first()
    category_name = category.name if category else category_code
    platform_suffix = f"-{platform}" if platform else ""
    today = datetime.utcnow().strftime("%Y-%m-%d")
    batch_number = db.query(CleanJobRecord).filter(CleanJobRecord.category_code == category_code).count() + 1
    return f"{category_name}{platform_suffix} {today} 第{batch_number}批"


def create_category_task_snapshot(
    db: Session,
    *,
    category_code: str,
    platform: str | None,
    dispatch_batch_id: int | None,
    task_name: str | None,
    rules: dict | None,
):
    normalized_platform = normalize_platform(platform)
    rows = (
        _pending_dispatch_query(
            db,
            category_code=category_code,
            platform=normalized_platform,
            dispatch_batch_id=dispatch_batch_id,
        )
        .order_by(DispatchItem.id)
        .all()
    )
    if not rows:
        raise ValueError("该品类没有可创建任务的数据")

    file_ids = sorted({raw.file_id for _, raw in rows if raw.file_id is not None})
    dispatch_batch_ids = sorted({dispatch_item.batch_id for dispatch_item, _ in rows if dispatch_item.batch_id is not None})
    job = CleanJobRecord(
        file_ids=file_ids,
        rules=rules or {"dedup": True},
        status="created",
        row_in=len(rows),
        row_out=0,
        dispatch_batch_id=dispatch_batch_id,
        dispatch_category_code=category_code,
        task_name=task_name or _default_task_name(db, category_code, normalized_platform),
        category_code=category_code,
        platform=normalized_platform,
        source_scope={"dispatch_batch_ids": dispatch_batch_ids, "file_ids": file_ids},
    )
    db.add(job)
    db.flush()

    db.add_all([
        CleanJobItemRecord(
            clean_job_id=job.id,
            raw_data_id=raw.id,
            category_code=dispatch_item.category_code,
            platform=normalize_platform(raw.platform),
            dispatch_batch_id=dispatch_item.batch_id,
        )
        for dispatch_item, raw in rows
    ])
    db.flush()
    return job, len(rows)


APPENDABLE_TASK_STATUSES = {"reviewing", "done", "published"}
REVIEWED_MATCH_STATUSES = {"confirmed", "excluded", "disputed"}


def _default_monthly_task_name(db: Session, category_code: str, platform: str, month: int) -> str:
    category = db.query(Category).filter(Category.code == category_code).first()
    category_name = category.name if category else category_code
    return f"{category_name} / {platform} / {month}"


def _scope_list(scope: dict, key: str) -> list:
    value = scope.get(key, [])
    return value if isinstance(value, list) else []


def _safe_int_values(values: list) -> list[int]:
    parsed = []
    for value in values:
        if value is None:
            continue
        try:
            parsed.append(int(value))
        except (TypeError, ValueError):
            continue
    return parsed


def _safe_existing_int_list(value) -> list[int]:
    return _safe_int_values(value if isinstance(value, list) else [])


def _merge_scope(scope: dict | None, *, months: list[int], platforms: list[str], dispatch_batch_ids: list[int], file_ids: list[int]) -> dict:
    current = scope if isinstance(scope, dict) else {}
    return {
        "months": sorted({*_safe_int_values(_scope_list(current, "months")), *months}),
        "platforms": sorted({str(v) for v in _scope_list(current, "platforms") + platforms if v}),
        "dispatch_batch_ids": sorted({*_safe_int_values(_scope_list(current, "dispatch_batch_ids")), *dispatch_batch_ids}),
        "file_ids": sorted({*_safe_int_values(_scope_list(current, "file_ids")), *file_ids}),
    }


def _has_reviewed_or_published_state(db: Session, clean_job_id: int) -> bool:
    reviewed_exists = db.query(MatchResult.id).filter(
        MatchResult.clean_job_id == clean_job_id,
        or_(
            MatchResult.match_status.in_(REVIEWED_MATCH_STATUSES),
            MatchResult.is_disabled == 1,
            MatchResult.sales_coefficient.isnot(None),
            MatchResult.dispute_reason.isnot(None),
            MatchResult.review_note.isnot(None),
            MatchResult.reviewed_at.isnot(None),
        ),
    ).first()
    if reviewed_exists:
        return True

    attr_exists = (
        db.query(MatchResultAttr.id)
        .join(MatchResult, MatchResult.id == MatchResultAttr.match_result_id)
        .filter(MatchResult.clean_job_id == clean_job_id)
        .first()
    )
    if attr_exists:
        return True

    return db.query(PublishJob.id).filter(PublishJob.clean_job_id == clean_job_id).first() is not None


def upsert_monthly_task_snapshot(
    db: Session,
    *,
    category_code: str,
    platform: str,
    month: int,
    rules: dict | None,
):
    normalized_platform = normalize_platform(platform)
    rows = (
        _monthly_pending_rows(
            db,
            category_code=category_code,
            platform=normalized_platform,
            month=month,
        )
        .order_by(DispatchItem.id)
        .all()
    )
    if not rows:
        raise ValueError("该任务范围没有待入清洗队列的数据")

    job = _find_monthly_job(
        db,
        category_code=category_code,
        platform=normalized_platform,
        month=month,
    )
    action = "appended" if job else "created"
    if job and job.status not in APPENDABLE_TASK_STATUSES:
        raise ValueError(f"任务状态为 {job.status}，不能追加数据")
    if job and _has_reviewed_or_published_state(db, job.id):
        raise ValueError("任务已有人工处理或发布记录，不能直接追加数据")

    file_ids = sorted({raw.file_id for _, raw in rows if raw.file_id is not None})
    dispatch_batch_ids = sorted({dispatch_item.batch_id for dispatch_item, _ in rows if dispatch_item.batch_id is not None})

    if job is None:
        job = CleanJobRecord(
            file_ids=file_ids,
            rules=rules or {"dedup": True},
            status="created",
            row_in=0,
            row_out=0,
            task_name=_default_monthly_task_name(db, category_code, normalized_platform, month),
            category_code=category_code,
            platform=normalized_platform,
            dispatch_category_code=category_code,
            source_scope={
                "months": [month],
                "platforms": [normalized_platform],
                "dispatch_batch_ids": dispatch_batch_ids,
                "file_ids": file_ids,
            },
        )
        db.add(job)
        db.flush()
    else:
        job.file_ids = sorted({*_safe_existing_int_list(job.file_ids), *file_ids})
        if rules is not None:
            job.rules = rules
        job.source_scope = _merge_scope(
            job.source_scope,
            months=[month],
            platforms=[normalized_platform],
            dispatch_batch_ids=dispatch_batch_ids,
            file_ids=file_ids,
        )

    new_items = [
        CleanJobItemRecord(
            clean_job_id=job.id,
            raw_data_id=raw.id,
            category_code=dispatch_item.category_code,
            platform=normalize_platform(raw.platform),
            dispatch_batch_id=dispatch_item.batch_id,
        )
        for dispatch_item, raw in rows
    ]
    db.add_all(new_items)
    db.flush()
    new_snapshot_ids = [item.id for item in new_items]
    job.row_in = db.query(CleanJobItemRecord).filter(CleanJobItemRecord.clean_job_id == job.id).count()
    return job, len(rows), action, new_snapshot_ids
