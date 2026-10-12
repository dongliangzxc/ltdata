"""排除沉淀库读写：人工排除的商品写入 item_exclusions，供后续同品类任务自动沿用排除。

复用匹配键（与匹配引擎 S0.1 一致）：
  - 优先 (platform, item_id) —— 有可解析链接时；
  - 无链接/无 item_id 时回退规范化标题 item_name_norm。
复用范围限定 category_code 相同的任务。
"""
from sqlalchemy.orm import Session

from app.models.schemas import (
    CleanJobRecord,
    ItemExclusion,
    MatchResult,
    RawDataRecord,
)
from app.utils.text_utils import title_key
from app.utils.url_utils import extract_item_id


def _resolve_item_key(raw: RawDataRecord) -> tuple[str | None, str | None]:
    """从原始数据解析 (platform, item_id)，item_id 缺失时尝试从链接提取。"""
    platform = (raw.platform or "").strip().lower() or None
    item_id = (raw.item_id or "").strip() or None
    if (not platform or not item_id) and raw.item_url:
        parsed = extract_item_id(raw.item_url)
        if parsed:
            platform = platform or parsed[0]
            item_id = item_id or parsed[1]
    return platform, item_id


def upsert_exclusion_for_raw(
    db: Session,
    raw: RawDataRecord,
    category_code: str | None,
    reason: str | None = None,
    source: str = "manual",
) -> ItemExclusion | None:
    """把一条原始数据的人工排除写入沉淀库（幂等：同键更新）。无可用匹配键时返回 None。"""
    if raw is None:
        return None
    platform, item_id = _resolve_item_key(raw)
    name_norm = title_key(raw.item_name) or None

    existing: ItemExclusion | None = None
    if platform and item_id:
        existing = (
            db.query(ItemExclusion)
            .filter(
                ItemExclusion.category_code == category_code,
                ItemExclusion.platform == platform,
                ItemExclusion.item_id == item_id,
            )
            .first()
        )
    elif name_norm:
        existing = (
            db.query(ItemExclusion)
            .filter(
                ItemExclusion.category_code == category_code,
                ItemExclusion.item_id.is_(None),
                ItemExclusion.item_name_norm == name_norm,
            )
            .first()
        )
    else:
        return None

    if existing:
        existing.item_url = raw.item_url or existing.item_url
        existing.item_name = raw.item_name or existing.item_name
        existing.item_name_norm = name_norm or existing.item_name_norm
        if platform:
            existing.platform = platform
        if item_id:
            existing.item_id = item_id
        existing.reason = reason or existing.reason
        existing.source = source
        return existing

    record = ItemExclusion(
        category_code=category_code,
        platform=platform,
        item_id=item_id,
        item_url=raw.item_url,
        item_name=raw.item_name,
        item_name_norm=name_norm,
        reason=reason,
        source=source,
    )
    db.add(record)
    return record


def remove_exclusion_for_raw(
    db: Session,
    raw: RawDataRecord,
    category_code: str | None,
) -> int:
    """撤销/覆盖排除时，从沉淀库删除对应记录（按链接优先、标题兜底）。返回删除条数。"""
    if raw is None:
        return 0
    platform, item_id = _resolve_item_key(raw)
    name_norm = title_key(raw.item_name) or None

    deleted = 0
    if platform and item_id:
        deleted += (
            db.query(ItemExclusion)
            .filter(
                ItemExclusion.category_code == category_code,
                ItemExclusion.platform == platform,
                ItemExclusion.item_id == item_id,
            )
            .delete(synchronize_session=False)
        )
        return deleted
    if name_norm:
        deleted += (
            db.query(ItemExclusion)
            .filter(
                ItemExclusion.category_code == category_code,
                ItemExclusion.item_id.is_(None),
                ItemExclusion.item_name_norm == name_norm,
            )
            .delete(synchronize_session=False)
        )
    return deleted


def backfill_existing_exclusions(db: Session) -> int:
    """把历史上所有人工排除记录（match_status='excluded'）全量回填到沉淀库。

    键口径与匹配引擎 S0.1 一致（链接优先、标题兜底，按任务品类限定）；
    已存在的同键记录原地更新，返回参与回填（新增或更新）的记录条数。
    无归属品类的任务跳过。
    """
    rows = (
        db.query(MatchResult, RawDataRecord, CleanJobRecord)
        .join(RawDataRecord, MatchResult.raw_data_id == RawDataRecord.id)
        .join(CleanJobRecord, MatchResult.clean_job_id == CleanJobRecord.id)
        .filter(MatchResult.match_status == "excluded")
        .all()
    )
    backfilled = 0
    for mr, raw, job in rows:
        category = job.category_code or job.dispatch_category_code
        if not category:
            continue
        record = upsert_exclusion_for_raw(
            db, raw, category, reason=mr.review_note, source="manual"
        )
        if record is not None:
            backfilled += 1
    return backfilled


def load_exclusion_index(db: Session, category_code: str | None) -> tuple[set, set]:
    """预加载指定品类的排除键：返回 ((platform, item_id) 集合, 规范化标题集合)。

    category_code 为空时不启用复用（避免跨品类误伤）。
    """
    if not category_code:
        return set(), set()
    rows = (
        db.query(ItemExclusion)
        .filter(ItemExclusion.category_code == category_code)
        .all()
    )
    url_keys: set = set()
    name_keys: set = set()
    for row in rows:
        if row.platform and row.item_id:
            url_keys.add((row.platform.lower(), row.item_id))
        elif row.item_name_norm:
            name_keys.add(row.item_name_norm)
    return url_keys, name_keys
