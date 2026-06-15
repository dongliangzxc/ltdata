from datetime import datetime

from sqlalchemy import and_, case, func, or_
from sqlalchemy.orm import Session

from app.models.schemas import (
    Category,
    CleanJobItemRecord,
    CleanJobRecord,
    DispatchItem,
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
