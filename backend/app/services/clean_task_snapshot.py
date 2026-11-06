from datetime import datetime

from sqlalchemy import String, and_, case, cast, func, or_
from sqlalchemy.orm import Session

from app.models.schemas import (
    Category,
    CleanJobItemRecord,
    CleanJobRecord,
    DispatchBatch,
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
    "amazon": {"amazon", "亚马逊", "amz"},
    "shopee": {"shopee", "西皮", "虾皮"},
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


def _latest_done_batch_ids(db: Session):
    """每个文件/上传批次的最新已完成分发批次。

    与分发结果下载、规则命中核对保持同一口径：上传批次用 `batch_key` 标识，
    单文件分发用 `file_id` 标识；重新分发/补分发会生成更新的批次，旧批次
    不再是取数依据。
    """
    batch_identity = func.coalesce(
        func.nullif(DispatchBatch.batch_key, ""),
        cast(DispatchBatch.file_id, String),
    )
    return (
        db.query(func.max(DispatchBatch.id).label("batch_id"))
        .filter(
            DispatchBatch.status == "done",
            or_(DispatchBatch.file_id.isnot(None), DispatchBatch.batch_key.isnot(None)),
        )
        .group_by(batch_identity)
        .subquery()
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
        # 显式指定批次时按该批次取数（按批次建任务/清洗）。
        dispatch_item_ids = dispatch_item_ids.filter(DispatchItem.batch_id == dispatch_batch_id)
    else:
        # 月度队列/任务默认只看每个文件的最新已完成批次，避免重新分发后旧批次
        # 命中项继续累计。
        latest_batches = _latest_done_batch_ids(db)
        dispatch_item_ids = dispatch_item_ids.join(
            latest_batches,
            DispatchItem.batch_id == latest_batches.c.batch_id,
        )
    return dispatch_item_ids.group_by(
        DispatchItem.raw_data_id,
        DispatchItem.category_code,
    ).subquery()


def _dispatch_query(
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
    )
    normalized_platform = normalize_platform(platform)
    if normalized_platform:
        q = q.filter(func.lower(RawDataRecord.platform).in_(platform_aliases_for(normalized_platform)))
    return q


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
    category_codes: set[str] | None = None,
) -> dict[tuple[str, str, int], CleanJobRecord]:
    q = db.query(CleanJobRecord).filter(CleanJobRecord.category_code.isnot(None))
    if category_code:
        q = q.filter(CleanJobRecord.category_code == category_code)
    elif category_codes is not None:
        if not category_codes:
            return {}
        q = q.filter(CleanJobRecord.category_code.in_(category_codes))
    normalized_platform = normalize_platform(platform)
    if normalized_platform:
        q = q.filter(func.lower(CleanJobRecord.platform).in_(platform_aliases_for(normalized_platform)))

    jobs_by_scope: dict[tuple[str, str, int], CleanJobRecord] = {}
    for job in q.order_by(CleanJobRecord.id.desc()).all():
        job_platform = normalize_platform(job.platform)
        if not job.category_code or not job_platform or job.status == "archived":
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
    """待入清洗队列（按月/品类/平台聚合）。

    只统计每个文件/上传批次的**最新已完成分发批次**，与分发结果下载一致；
    重新分发后旧批次命中项不再累计。无品类筛选且带 limit 时按 `Category.code`
    逐个品类查询并**提前终止**：通常首个（或前几个）品类即可凑满 limit 个
    scope，避免一次聚合千万级 `dispatch_items`（单条全量聚合会让 MySQL 扫描
    全部派发明细，实测 >3 分钟）。只取两个 distinct 计数，`pending` 由
    `dispatched - queued` 推导（`clean_job_items` 的
    `(raw_data_id, category_code)` 唯一键保证等价）；活跃任务的有下游状态
    批量查询、归档任务候选按 (品类, 平台) 缓存，避免逐行 N+1。
    """
    platform_label = _platform_label_expr()
    normalized_filter_platform = normalize_platform(platform)

    dispatched_count = func.count(func.distinct(DispatchItem.raw_data_id)).label("dispatched_count")
    queued_count = func.count(func.distinct(CleanJobItemRecord.raw_data_id)).label("queued_count")
    latest_batches = _latest_done_batch_ids(db)

    def build_grouped_query(scoped_category_code: str | None = None):
        q = (
            db.query(
                DispatchItem.category_code.label("category_code"),
                Category.name.label("category_name"),
                platform_label.label("platform"),
                RawDataRecord.month.label("month"),
                dispatched_count,
                queued_count,
            )
            .join(latest_batches, DispatchItem.batch_id == latest_batches.c.batch_id)
            .join(RawDataRecord, RawDataRecord.id == DispatchItem.raw_data_id)
            .join(Category, Category.code == DispatchItem.category_code)
            .outerjoin(
                CleanJobItemRecord,
                and_(
                    CleanJobItemRecord.raw_data_id == DispatchItem.raw_data_id,
                    CleanJobItemRecord.category_code == DispatchItem.category_code,
                ),
            )
            .filter(RawDataRecord.month.isnot(None))
        )
        effective_category_code = scoped_category_code or category_code
        if effective_category_code:
            q = q.filter(DispatchItem.category_code == effective_category_code)
        if normalized_filter_platform:
            q = q.filter(func.lower(RawDataRecord.platform).in_(platform_aliases_for(normalized_filter_platform)))
        if month is not None:
            q = q.filter(RawDataRecord.month == month)
        return q.group_by(DispatchItem.category_code, Category.name, platform_label, RawDataRecord.month)

    if limit is not None and not category_code:
        grouped = []
        category_codes = [
            row[0]
            for row in db.query(Category.code).order_by(Category.code).all()
        ]
        for scoped_category_code in category_codes:
            remaining = limit - len(grouped)
            if remaining <= 0:
                break
            rows = (
                build_grouped_query(scoped_category_code)
                .order_by(platform_label, RawDataRecord.month)
                .limit(remaining)
                .all()
            )
            grouped.extend(rows)
    else:
        grouped_query = build_grouped_query().order_by(DispatchItem.category_code, platform_label, RawDataRecord.month)
        if limit is not None:
            grouped_query = grouped_query.limit(limit)
        grouped = grouped_query.all()

    jobs_by_scope = _monthly_jobs_by_scope(
        db,
        category_code=category_code,
        platform=platform,
        category_codes={row.category_code for row in grouped},
    )

    archived_candidates: dict[tuple[str, str | None], list[CleanJobRecord]] = {}
    downstream_state: dict[int, bool] = {}
    active_downstream_ids = _jobs_with_reviewed_or_published_state(
        db, {job.id for job in jobs_by_scope.values()}
    )

    def _archived_job_with_downstream(
        scope_category_code: str,
        scope_platform: str | None,
        scope_month: int,
    ) -> tuple[CleanJobRecord, bool] | None:
        normalized_platform = normalize_platform(scope_platform)
        cache_key = (scope_category_code, normalized_platform)
        if cache_key not in archived_candidates:
            aliases = platform_aliases_for(normalized_platform)
            if not aliases:
                archived_candidates[cache_key] = []
            else:
                archived_candidates[cache_key] = (
                    db.query(CleanJobRecord)
                    .filter(
                        CleanJobRecord.category_code == scope_category_code,
                        CleanJobRecord.status == "archived",
                        func.lower(CleanJobRecord.platform).in_(aliases),
                    )
                    .order_by(CleanJobRecord.id.desc())
                    .all()
                )
        for job in archived_candidates[cache_key]:
            if scope_month not in _job_months(job):
                continue
            if job.id not in downstream_state:
                downstream_state[job.id] = _has_reviewed_or_published_state(db, job.id)
            return job, downstream_state[job.id]
        return None

    result = []
    for row in grouped:
        normalized_platform = normalize_platform(row.platform)
        row_month = int(row.month)
        pending_count = row.dispatched_count - row.queued_count
        job = jobs_by_scope.get((row.category_code, normalized_platform, row_month))
        if job is not None and job.id in active_downstream_ids:
            # 已有人工/发布结果的活跃任务仍按原逻辑不在待入队列表展示；
            # 无下游结果的任务展示出来，便于追加或「重新清洗」同步最新分发。
            continue
        if job is None:
            archived_job = _archived_job_with_downstream(row.category_code, row.platform, row_month)
            if archived_job:
                archived_job_obj, has_downstream = archived_job
                if has_downstream:
                    result.append({
                        "category_code": row.category_code,
                        "category_name": row.category_name,
                        "platform": normalized_platform,
                        "month": row_month,
                        "dispatched_count": row.dispatched_count,
                        "pending_count": pending_count,
                        "queued_count": row.queued_count,
                        "existing_job_id": archived_job_obj.id,
                        "existing_job_name": archived_job_obj.task_name,
                        "existing_job_status": "archived",
                        "has_reviewed_or_published": True,
                    })
                    continue
        result.append({
            "category_code": row.category_code,
            "category_name": row.category_name,
            "platform": normalized_platform,
            "month": row_month,
            "dispatched_count": row.dispatched_count,
            "pending_count": pending_count,
            "queued_count": row.queued_count,
            "existing_job_id": job.id if job else None,
            "existing_job_name": job.task_name if job else None,
            "existing_job_status": job.status if job else None,
            "has_reviewed_or_published": False,
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
# Ignoring is a task-local manual decision and therefore counts as reviewed
# when deciding whether a monthly task has downstream state.  It is kept out
# of the exclusion-store reuse path; only the status bookkeeping is shared.
REVIEWED_MATCH_STATUSES = {"confirmed", "excluded", "ignored", "disputed"}


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


def _jobs_with_reviewed_or_published_state(db: Session, clean_job_ids) -> set[int]:
    job_ids = {int(job_id) for job_id in clean_job_ids if job_id is not None}
    if not job_ids:
        return set()

    result: set[int] = set()
    reviewed_rows = db.query(MatchResult.clean_job_id).filter(
        MatchResult.clean_job_id.in_(job_ids),
        or_(
            MatchResult.match_status.in_(REVIEWED_MATCH_STATUSES),
            MatchResult.is_disabled == 1,
            MatchResult.sales_coefficient.isnot(None),
            MatchResult.dispute_reason.isnot(None),
            MatchResult.review_note.isnot(None),
            MatchResult.reviewed_at.isnot(None),
        ),
    ).distinct().all()
    result.update(row[0] for row in reviewed_rows)

    attr_rows = (
        db.query(MatchResult.clean_job_id)
        .join(MatchResultAttr, MatchResultAttr.match_result_id == MatchResult.id)
        .filter(MatchResult.clean_job_id.in_(job_ids))
        .distinct()
        .all()
    )
    result.update(row[0] for row in attr_rows)

    publish_rows = db.query(PublishJob.clean_job_id).filter(
        PublishJob.clean_job_id.in_(job_ids)
    ).distinct().all()
    result.update(row[0] for row in publish_rows)
    return result


def _has_reviewed_or_published_state(db: Session, clean_job_id: int) -> bool:
    return bool(_jobs_with_reviewed_or_published_state(db, [clean_job_id]))


def touch_clean_job(db: Session, clean_job_id: int) -> None:
    """更新清洗任务的最近处理时间（清洗/匹配/复核/发布等操作时调用）。"""
    db.query(CleanJobRecord).filter(CleanJobRecord.id == clean_job_id).update(
        {CleanJobRecord.updated_at: datetime.utcnow()}
    )


def upsert_monthly_task_snapshot(
    db: Session,
    *,
    category_code: str,
    platform: str,
    month: int,
    rules: dict | None,
    force_reclean: bool = False,
    force_rebuild: bool = False,
):
    """创建/追加/重建月度任务快照。

    取数口径为每个文件最新已完成分发批次。`force_reclean` 在任务没有人工确认/
    发布记录时按最新分发范围重建快照，可移出重新分发后不再命中的旧行；
    `force_rebuild` 允许清除已有下游结果后重建。
    """
    normalized_platform = normalize_platform(platform)
    job = _find_monthly_job(
        db,
        category_code=category_code,
        platform=normalized_platform,
        month=month,
    )
    action = "appended" if job else "created"
    has_downstream = _has_reviewed_or_published_state(db, job.id) if job else False

    # 已有任务「重新清洗」时，若无人工/发布记录，按最新分发范围重建快照，
    # 把已被新批次取代的旧命中行移出；有下游结果时仍要求走强制重建。
    if job and force_reclean and not force_rebuild and has_downstream:
        raise ValueError("任务已有人工处理或发布记录，不能直接重新清洗")

    reset_snapshot = bool(job) and (
        force_rebuild or force_reclean or job.status == "archived"
    )

    if job and not force_rebuild and not force_reclean:
        if job.status not in APPENDABLE_TASK_STATUSES and job.status != "archived":
            raise ValueError(f"任务状态为 {job.status}，不能追加数据")
        if has_downstream:
            raise ValueError("任务已有人工处理或发布记录，不能直接追加数据")

    if reset_snapshot:
        db.query(CleanJobItemRecord).filter(
            CleanJobItemRecord.clean_job_id == job.id
        ).delete(synchronize_session=False)
        job.status = "reviewing"

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
        raise ValueError("该任务范围没有可清洗的数据")

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
