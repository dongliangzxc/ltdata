"""
型号匹配 API
"""
import logging
import re
import time
import unicodedata
from collections import Counter
from datetime import datetime
from threading import Thread
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.models.database import get_db, SessionLocal
from sqlalchemy import func
from app.models.schemas import (
    MatchResult, MatchResultOut, MatchSummary,
    CleanJobRecord, RawDataRecord, ModelRecord, BrandRecord,
    MatchResultAttr, MatchResultCandidate, MatchCandidateOut, ItemUrlMapping, Category,
    MetadataSpec, ModelSpec, CleanedDataRecord,
    DispatchItem,
    PaginatedResponse,
)
from app.services.matcher import run_match
from app.services.price_auditor import audit_price
from app.utils.time_utils import format_beijing_datetime

router = APIRouter(prefix="/api/match", tags=["match"])
logger = logging.getLogger(__name__)

# ── 进度状态（内存，key=clean_job_id）────────────────────────────────
# {
#   clean_job_id: {
#     "status":    "running" | "done" | "error",
#     "total":     int,
#     "processed": int,
#     "matched":   int,
#     "started_at": float,
#     "finished_at": float | None,
#     "error":     str | None,
#   }
# }
_progress: dict[int, dict] = {}

SAME_TITLE_ACTIONABLE_STATUSES = {"pending", "text_only", "disputed"}
_TITLE_PUNCT_RE = re.compile(
    r"[\s\-‐‑‒–—―_/\\|,，、.。·・•!！?？:：;；'‘’\"“”()（）\[\]【】{}<>《》&+@#＃$￥%％^*＊=~～`｀…]+"
)


def _same_title_key(value: str | None) -> str:
    normalized = unicodedata.normalize("NFKC", value or "").casefold().strip()
    return _TITLE_PUNCT_RE.sub("", normalized)


def _same_title_rows(db: Session, match_id: int):
    current = (
        db.query(MatchResult, RawDataRecord)
        .join(RawDataRecord, MatchResult.raw_data_id == RawDataRecord.id)
        .filter(MatchResult.id == match_id)
        .first()
    )
    if not current:
        raise HTTPException(status_code=404, detail="匹配记录不存在")

    current_mr, current_raw = current
    key = _same_title_key(current_raw.item_name)
    if not key:
        return current_mr, []

    candidates = (
        db.query(MatchResult, RawDataRecord, ModelRecord)
        .join(RawDataRecord, MatchResult.raw_data_id == RawDataRecord.id)
        .outerjoin(ModelRecord, MatchResult.model_id == ModelRecord.id)
        .filter(MatchResult.clean_job_id == current_mr.clean_job_id)
        .order_by(MatchResult.id)
        .all()
    )
    rows = [row for row in candidates if _same_title_key(row[1].item_name) == key]
    return current_mr, rows


def _same_title_item_payload(mr: MatchResult, rd: RawDataRecord, model: ModelRecord | None) -> dict:
    return {
        "id": mr.id,
        "raw_data_id": mr.raw_data_id,
        "item_name": rd.item_name,
        "item_url": rd.item_url,
        "brand_raw": rd.brand_raw,
        "match_status": mr.match_status,
        "model_id": mr.model_id,
        "model_code": model.model_code if model else None,
        "brand_code": model.brand_code if model else None,
        "sales_qty": rd.sales_qty,
        "actionable": mr.match_status in SAME_TITLE_ACTIONABLE_STATUSES,
    }


def _allowed_same_title_statuses(payload: dict) -> set[str]:
    raw_statuses = payload.get("include_statuses")
    if raw_statuses is None:
        raw_statuses = list(SAME_TITLE_ACTIONABLE_STATUSES)
    if not isinstance(raw_statuses, list):
        raise HTTPException(status_code=400, detail="include_statuses 必须是数组")
    statuses = {str(status) for status in raw_statuses}
    invalid = statuses - SAME_TITLE_ACTIONABLE_STATUSES
    if invalid:
        raise HTTPException(status_code=400, detail=f"不支持批量处理状态: {sorted(invalid)[0]}")
    return statuses


def _upsert_url_mapping_for_raw(db: Session, rd: RawDataRecord, model: ModelRecord, source: str = "match_confirm") -> bool:
    if not rd or not rd.item_url or not rd.platform or not rd.item_id:
        return False
    existing = db.query(ItemUrlMapping).filter_by(platform=rd.platform, item_id=rd.item_id).first()
    if existing:
        changed = existing.model_id != model.id or existing.brand_code != model.brand_code or existing.item_url != rd.item_url
        existing.model_id = model.id
        existing.item_url = rd.item_url
        existing.brand_code = model.brand_code
        existing.price = rd.price
        existing.source = source
        return changed
    db.add(ItemUrlMapping(
        platform=rd.platform,
        item_id=rd.item_id,
        item_url=rd.item_url,
        model_id=model.id,
        brand_code=model.brand_code,
        price=rd.price,
        source=source,
    ))
    return True


def confirm_single_review(db: Session, mr: MatchResult, model: ModelRecord) -> None:
    """将一条 MatchResult 确认为指定型号；不做 commit，由调用方负责。"""
    mr.model_id = model.id
    mr.match_status = "confirmed"
    mr.matched_by = "manual"
    mr.match_source = "manual"
    mr.dispute_reason = None
    mr.review_note = None
    mr.reviewed_at = datetime.utcnow()

    if mr.raw_data_id:
        rd_for_url = db.query(RawDataRecord).filter(RawDataRecord.id == mr.raw_data_id).first()
        if rd_for_url:
            _upsert_url_mapping_for_raw(db, rd_for_url, model, source="match_confirm")

    db.query(MatchResultAttr).filter(MatchResultAttr.match_result_id == mr.id).delete()


MANUAL_TERMINAL_STATUSES = {"confirmed", "excluded", "disputed"}


def _snapshot_prev_state(mr: MatchResult) -> None:
    """记录当前状态作为撤销回滚点。人工三态之外（比如 pending / matched）也照录，
    这样从任意状态执行手工操作后都可以回到操作前的样子。"""
    mr.prev_match_status = mr.match_status
    mr.prev_model_id = mr.model_id
    mr.prev_matched_by = mr.matched_by
    mr.prev_match_source = mr.match_source
    mr.prev_dispute_reason = mr.dispute_reason
    mr.prev_review_note = mr.review_note
    mr.prev_reviewed_at = mr.reviewed_at


def _clear_prev_state(mr: MatchResult) -> None:
    mr.prev_match_status = None
    mr.prev_model_id = None
    mr.prev_matched_by = None
    mr.prev_match_source = None
    mr.prev_dispute_reason = None
    mr.prev_review_note = None
    mr.prev_reviewed_at = None


def _is_revertible(mr: MatchResult) -> bool:
    # 有 prev_* 快照就精准回滚到操作前状态；即便老数据没有快照，只要当前是人工三态，
    # 也允许撤销——按空快照兜底为 pending，让部署前的历史误操作也能修正
    return bool(mr and mr.match_status in MANUAL_TERMINAL_STATUSES)


def _run_post_confirm_hooks(db: Session, match_result_ids: list[int]) -> dict:
    if not match_result_ids:
        return {"matched_attrs": 0, "items_processed": 0}
    from app.services.attribute_matcher import run_attribute_matching
    attr_result = run_attribute_matching(db, match_result_ids, commit=False)
    try:
        audit_price(db, match_result_ids, commit=False)
    except Exception:
        logger.exception("Price audit failed after batch confirming match_result_ids=%s", match_result_ids)
        raise
    return attr_result


def _run_match_thread(clean_job_id: int):
    """在独立线程中执行匹配，更新 _progress"""
    db = SessionLocal()
    try:
        _progress[clean_job_id].update(status="running", started_at=time.time())

        def on_progress(processed: int, total: int, matched: int):
            _progress[clean_job_id].update(
                processed=processed, total=total, matched=matched
            )

        stats = run_match(db, clean_job_id, progress_cb=on_progress)
        _progress[clean_job_id].update(
            status="done",
            total=stats["total"],
            processed=stats["total"],
            matched=stats["matched"],
            finished_at=time.time(),
        )
    except Exception as e:
        _progress[clean_job_id].update(status="error", error=str(e), finished_at=time.time())
    finally:
        db.close()


@router.post("/run")
def run_match_job(payload: dict, db: Session = Depends(get_db)):
    """启动后台匹配任务，立即返回。通过 /progress/{id} 轮询进度。"""
    clean_job_id: int = payload.get("clean_job_id")
    if not clean_job_id:
        raise HTTPException(status_code=400, detail="clean_job_id 不能为空")

    job = db.query(CleanJobRecord).filter(CleanJobRecord.id == clean_job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="清洗任务不存在")

    # 若已在运行则拒绝重复触发
    if _progress.get(clean_job_id, {}).get("status") == "running":
        raise HTTPException(status_code=409, detail="该任务匹配正在进行中，请勿重复触发")

    _progress[clean_job_id] = {
        "status": "running",
        "total": 0,
        "processed": 0,
        "matched": 0,
        "started_at": time.time(),
        "finished_at": None,
        "error": None,
    }

    t = Thread(target=_run_match_thread, args=(clean_job_id,), daemon=True)
    t.start()

    return {"status": "started", "clean_job_id": clean_job_id}


@router.get("/progress/{clean_job_id}")
def get_match_progress(clean_job_id: int):
    """查询匹配进度"""
    p = _progress.get(clean_job_id)
    if not p:
        return {"status": "idle"}

    result = dict(p)
    if p["total"] > 0 and p["status"] == "running":
        elapsed = time.time() - p["started_at"]
        rate = p["processed"] / elapsed if elapsed > 0 else 0
        remaining_items = p["total"] - p["processed"]
        result["eta_seconds"] = int(remaining_items / rate) if rate > 0 else None
        result["rate"] = round(rate)
    else:
        result["eta_seconds"] = None
        result["rate"] = None

    return result


@router.get("/{clean_job_id}/summary", response_model=MatchSummary)
def get_match_summary(clean_job_id: int, db: Session = Depends(get_db)):
    """查看某次清洗任务的匹配统计，无记录时返回全零（不报错）"""
    rows = db.query(MatchResult).filter(MatchResult.clean_job_id == clean_job_id).all()
    if not rows:
        return MatchSummary(
            clean_job_id=clean_job_id,
            total=0, url_matched=0, matched=0, text_only=0,
            pending=0, confirmed=0, excluded=0, disputed=0, disabled=0,
        )

    total = len(rows)
    status_count: dict[str, int] = {}
    for r in rows:
        status_count[r.match_status] = status_count.get(r.match_status, 0) + 1

    disabled_count = sum(1 for r in rows if r.is_disabled == 1)
    unidentified_brand_count = sum(1 for r in rows if getattr(r, 'brand_identified', 1) == 0 and r.match_status == "pending")
    precise_matched_count = sum(
        1 for r in rows
        if r.match_status in ("url_matched", "matched") and r.match_source in ("s0", "historical")
    )

    confirmed_ids = {r.id for r in rows if r.match_status in ("matched", "confirmed", "url_matched")}
    if confirmed_ids:
        ids_with_attrs = {
            r.match_result_id
            for r in db.query(MatchResultAttr.match_result_id)
                        .filter(MatchResultAttr.match_result_id.in_(confirmed_ids))
                        .distinct()
                        .all()
        }
        missing_attrs_count = len(confirmed_ids - ids_with_attrs)
    else:
        missing_attrs_count = 0

    return MatchSummary(
        clean_job_id=clean_job_id,
        total=total,
        url_matched=status_count.get("url_matched", 0),
        precise_matched=precise_matched_count,
        matched=status_count.get("matched", 0),
        text_only=status_count.get("text_only", 0),
        pending=status_count.get("pending", 0),
        confirmed=status_count.get("confirmed", 0),
        excluded=status_count.get("excluded", 0),
        disputed=status_count.get("disputed", 0),
        disabled=disabled_count,
        unidentified_brand=unidentified_brand_count,
        missing_attrs=missing_attrs_count,
    )


def _build_review_queue_query(
    db: Session,
    clean_job_id: int,
    tab: str,
    keyword: Optional[str],
    search_by: str,
    category_name: Optional[str],
    sort_by: str,
):
    """构造复核队列基础查询（与 list_pending 使用相同过滤）。返回未 count/paginate 的 Query。"""
    if tab not in _BATCH_ALLOWED_STATUSES:
        raise HTTPException(status_code=400, detail="tab 只能为 text_only 或 pending")

    clean_job = db.query(CleanJobRecord).filter(CleanJobRecord.id == clean_job_id).first()
    dispatch_batch_id = clean_job.dispatch_batch_id if clean_job else None
    if dispatch_batch_id is not None:
        di_join_cond = (
            (DispatchItem.raw_data_id == MatchResult.raw_data_id) &
            (DispatchItem.batch_id == dispatch_batch_id)
        )
    else:
        di_join_cond = (DispatchItem.raw_data_id == None)  # noqa: E711

    q = (
        db.query(MatchResult, RawDataRecord, ModelRecord)
        .join(RawDataRecord, MatchResult.raw_data_id == RawDataRecord.id)
        .outerjoin(ModelRecord, MatchResult.model_id == ModelRecord.id)
        .outerjoin(DispatchItem, di_join_cond)
        .outerjoin(Category, DispatchItem.category_code == Category.code)
        .filter(MatchResult.clean_job_id == clean_job_id, MatchResult.match_status == tab)
    )

    allowed_search_fields = {"item_name", "brand_raw", "brand_code"}
    if search_by not in allowed_search_fields:
        search_by = "item_name"
    if keyword:
        pattern = f"%{keyword}%"
        if search_by == "brand_raw":
            q = q.filter(RawDataRecord.brand_raw.ilike(pattern))
        elif search_by == "brand_code":
            q = (
                q.outerjoin(BrandRecord, BrandRecord.brand_code == ModelRecord.brand_code)
                 .filter(
                     (ModelRecord.brand_code.ilike(pattern))
                     | (BrandRecord.brand_name.ilike(pattern))
                 )
            )
        else:
            q = q.filter(RawDataRecord.item_name.ilike(pattern))
    if category_name:
        q = q.filter(Category.code == category_name)

    if sort_by == "sales_qty_desc":
        q = q.order_by(func.isnull(RawDataRecord.sales_qty).asc(), RawDataRecord.sales_qty.desc())
    elif sort_by == "sales_qty_asc":
        q = q.order_by(func.isnull(RawDataRecord.sales_qty).asc(), RawDataRecord.sales_qty.asc())
    else:
        q = q.order_by(MatchResult.id.asc())
    return q


@router.get("/{clean_job_id}/pending", response_model=PaginatedResponse)
def list_pending(
    clean_job_id: int,
    keyword: Optional[str] = Query(None),
    search_by: str = Query("item_name"),
    status: str = Query("pending"),
    brand_identified: Optional[int] = Query(None),
    category_name: Optional[str] = Query(None),
    sort_by: str = Query("default"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """分页查询复核队列条目。"""
    allowed_statuses = {"pending", "text_only", "disputed", "matched", "url_matched", "confirmed", "excluded"}
    if status not in allowed_statuses:
        status = "pending"

    # 获取 clean_job 的 dispatch_batch_id，用于关联 dispatch_items 取类目
    clean_job = db.query(CleanJobRecord).filter(CleanJobRecord.id == clean_job_id).first()
    dispatch_batch_id = clean_job.dispatch_batch_id if clean_job else None

    # 构建 dispatch_items join 条件（仅在有 dispatch_batch_id 时关联）
    if dispatch_batch_id is not None:
        di_join_cond = (
            (DispatchItem.raw_data_id == MatchResult.raw_data_id) &
            (DispatchItem.batch_id == dispatch_batch_id)
        )
    else:
        di_join_cond = (DispatchItem.raw_data_id == None)  # noqa: E711 — 无派发批次时不关联

    q = (
        db.query(MatchResult, RawDataRecord, ModelRecord, Category, func.count(MatchResultAttr.id).label("attr_count"))
        .join(RawDataRecord, MatchResult.raw_data_id == RawDataRecord.id)
        .outerjoin(ModelRecord, MatchResult.model_id == ModelRecord.id)
        .outerjoin(DispatchItem, di_join_cond)
        .outerjoin(Category, DispatchItem.category_code == Category.code)
        .outerjoin(MatchResultAttr, MatchResultAttr.match_result_id == MatchResult.id)
        .filter(MatchResult.clean_job_id == clean_job_id)
        .group_by(MatchResult.id, RawDataRecord.id, ModelRecord.id, Category.id)
    )
    if status == "matched":
        q = q.filter(MatchResult.match_status.in_(["matched", "url_matched"]))
    else:
        q = q.filter(MatchResult.match_status == status)

    allowed_search_fields = {"item_name", "brand_raw", "brand_code"}
    if search_by not in allowed_search_fields:
        search_by = "item_name"

    if keyword:
        pattern = f"%{keyword}%"
        if search_by == "brand_raw":
            q = q.filter(RawDataRecord.brand_raw.ilike(pattern))
        elif search_by == "brand_code":
            q = (
                q.outerjoin(BrandRecord, BrandRecord.brand_code == ModelRecord.brand_code)
                 .filter(
                     (ModelRecord.brand_code.ilike(pattern))
                     | (BrandRecord.brand_name.ilike(pattern))
                 )
                 .group_by(BrandRecord.id)
            )
        else:  # item_name（默认）
            q = q.filter(RawDataRecord.item_name.ilike(pattern))
    if brand_identified is not None:
        q = q.filter(MatchResult.brand_identified == brand_identified)
    if category_name:
        q = q.filter(Category.code == category_name)

    if sort_by == "sales_qty_desc":
        # MySQL 旧版不支持 NULLS LAST 语法，用 ISNULL() 模拟（NULL 排末尾）
        q = q.order_by(func.isnull(RawDataRecord.sales_qty).asc(), RawDataRecord.sales_qty.desc())
    elif sort_by == "sales_qty_asc":
        q = q.order_by(func.isnull(RawDataRecord.sales_qty).asc(), RawDataRecord.sales_qty.asc())

    total = q.count()
    rows = q.offset((page - 1) * page_size).limit(page_size).all()

    # 批量查询候选
    mr_ids = [mr.id for mr, *_ in rows]
    candidates_by_mr: dict[int, list] = {}
    if mr_ids:
        cand_rows = (
            db.query(MatchResultCandidate, ModelRecord)
            .outerjoin(ModelRecord, MatchResultCandidate.model_id == ModelRecord.id)
            .filter(MatchResultCandidate.match_result_id.in_(mr_ids))
            .order_by(MatchResultCandidate.match_result_id, MatchResultCandidate.rank)
            .all()
        )
        for cand, model in cand_rows:
            candidates_by_mr.setdefault(cand.match_result_id, []).append(
                MatchCandidateOut(
                    model_id=cand.model_id,
                    model_code=model.model_code if model else None,
                    brand_code=model.brand_code if model else None,
                    match_source=cand.match_source,
                    score=cand.score,
                    rank=cand.rank,
                )
            )

    items = []
    for mr, rd, model, cat, attr_count in rows:
        items.append(MatchResultOut(
            id=mr.id,
            clean_job_id=mr.clean_job_id,
            raw_data_id=mr.raw_data_id,
            model_id=mr.model_id,
            match_status=mr.match_status,
            matched_by=mr.matched_by,
            match_source=mr.match_source,
            brand_identified=mr.brand_identified,
            price_flag=mr.price_flag,
            price_ref=float(mr.price_ref) if mr.price_ref is not None else None,
            sales_coefficient=float(mr.sales_coefficient) if mr.sales_coefficient is not None else None,
            dispute_reason=mr.dispute_reason,
            review_note=mr.review_note,
            reviewed_at=mr.reviewed_at,
            item_name=rd.item_name,
            item_url=rd.item_url,
            brand_raw=rd.brand_raw,
            model_code=model.model_code if model else None,
            brand_code=model.brand_code if model else None,
            attr_count=attr_count,
            candidates=candidates_by_mr.get(mr.id, []),
            sales_qty=rd.sales_qty,
            category_name=cat.name if cat else None,
        ))

    return PaginatedResponse(total=total, page=page, page_size=page_size, items=items)


@router.get("/items/{match_id}/same-title-preview")
def preview_same_title_matches(match_id: int, db: Session = Depends(get_db)):
    _current_mr, rows = _same_title_rows(db, match_id)
    status_counts = Counter(mr.match_status for mr, _rd, _model in rows)
    actionable_count = sum(1 for mr, _rd, _model in rows if mr.match_status in SAME_TITLE_ACTIONABLE_STATUSES)
    return {
        "total": len(rows),
        "actionable_count": actionable_count,
        "status_counts": dict(sorted(status_counts.items())),
        "items": [
            _same_title_item_payload(mr, rd, model)
            for mr, rd, model in rows[:20]
        ],
    }


@router.post("/items/{match_id}/same-title-confirm")
def confirm_same_title_matches(match_id: int, payload: dict, db: Session = Depends(get_db)):
    model_id = payload.get("model_id")
    if model_id is None:
        raise HTTPException(status_code=400, detail="model_id 不能为空")
    model = db.query(ModelRecord).filter(ModelRecord.id == int(model_id)).first()
    if not model:
        raise HTTPException(status_code=404, detail="型号不存在")

    include_statuses = _allowed_same_title_statuses(payload)
    _current_mr, rows = _same_title_rows(db, match_id)
    now = datetime.utcnow()
    affected_ids: list[int] = []
    url_mapping_count = 0

    for mr, rd, _old_model in rows:
        if mr.match_status not in include_statuses:
            continue
        mr.model_id = model.id
        mr.match_status = "confirmed"
        mr.matched_by = "manual"
        mr.match_source = "manual"
        mr.dispute_reason = None
        mr.review_note = None
        mr.reviewed_at = now
        affected_ids.append(mr.id)
        if _upsert_url_mapping_for_raw(db, rd, model):
            url_mapping_count += 1

    attr_result = _run_post_confirm_hooks(db, affected_ids)
    db.commit()
    return {
        "affected_count": len(affected_ids),
        "url_mapping_count": url_mapping_count,
        "attr_result": attr_result,
    }


@router.post("/items/{match_id}/same-title-exclude")
def exclude_same_title_matches(match_id: int, payload: dict, db: Session = Depends(get_db)):
    include_statuses = _allowed_same_title_statuses(payload)
    reason = (payload.get("reason") or "").strip() or None
    _current_mr, rows = _same_title_rows(db, match_id)
    now = datetime.utcnow()
    affected_ids: list[int] = []

    for mr, _rd, _model in rows:
        if mr.match_status not in include_statuses:
            continue
        mr.match_status = "excluded"
        mr.model_id = None
        mr.matched_by = "manual"
        mr.match_source = "manual"
        mr.dispute_reason = None
        mr.review_note = reason
        mr.reviewed_at = now
        affected_ids.append(mr.id)

    db.commit()
    return {"affected_count": len(affected_ids)}


@router.get("/items/{match_id}/review-detail")
def get_match_review_detail(match_id: int, db: Session = Depends(get_db)):
    row = (
        db.query(MatchResult, RawDataRecord, ModelRecord, Category)
        .join(RawDataRecord, MatchResult.raw_data_id == RawDataRecord.id)
        .outerjoin(ModelRecord, MatchResult.model_id == ModelRecord.id)
        .outerjoin(Category, ModelRecord.category_code == Category.code)
        .filter(MatchResult.id == match_id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="匹配记录不存在")

    mr, rd, model, cat = row
    candidate_rows = (
        db.query(MatchResultCandidate, ModelRecord)
        .outerjoin(ModelRecord, MatchResultCandidate.model_id == ModelRecord.id)
        .filter(MatchResultCandidate.match_result_id == match_id)
        .order_by(MatchResultCandidate.rank)
        .all()
    )
    mapping = None
    if rd.platform and rd.item_id:
        mapping = db.query(ItemUrlMapping).filter_by(platform=rd.platform, item_id=rd.item_id).first()

    category_code = model.category_code if model and model.category_code else None
    if not category_code:
        clean_job = db.query(CleanJobRecord).filter(CleanJobRecord.id == mr.clean_job_id).first()
        category_code = (clean_job.category_code or clean_job.dispatch_category_code) if clean_job else None

    metadata_specs = []
    if category_code:
        metadata_specs = [
            {
                "id": spec.id,
                "spec_name": spec.spec_name,
                "spec_type": spec.spec_type,
                "spec_values": spec.spec_values,
                "required": bool(spec.required),
                "decimal_places": spec.decimal_places,
                "single_select": bool(spec.single_select),
            }
            for spec in db.query(MetadataSpec)
            .filter(MetadataSpec.category_code == category_code)
            .order_by(MetadataSpec.id)
            .all()
        ]

    model_specs = []
    if model:
        model_specs = [
            {"id": spec.id, "spec_name": spec.spec_name, "spec_value": spec.spec_value}
            for spec in db.query(ModelSpec).filter(ModelSpec.model_id == model.id).order_by(ModelSpec.id).all()
        ]

    match_attrs = [
        {"id": attr.id, "attr_name": attr.attr_name, "attr_value": attr.attr_value, "rule_id": attr.rule_id}
        for attr in db.query(MatchResultAttr)
        .filter(MatchResultAttr.match_result_id == match_id)
        .order_by(MatchResultAttr.id)
        .all()
    ]

    if not cat and category_code:
        cat = db.query(Category).filter(Category.code == category_code).first()

    return {
        "id": mr.id,
        "clean_job_id": mr.clean_job_id,
        "raw_data_id": mr.raw_data_id,
        "model_id": mr.model_id,
        "model_code": model.model_code if model else None,
        "brand_code": model.brand_code if model else None,
        "category_code": category_code,
        "category_name": cat.name if cat else None,
        "metadata_specs": metadata_specs,
        "model_specs": model_specs,
        "match_attrs": match_attrs,
        "match_status": mr.match_status,
        "matched_by": mr.matched_by,
        "match_source": mr.match_source,
        "brand_identified": mr.brand_identified,
        "price_flag": mr.price_flag,
        "price_ref": float(mr.price_ref) if mr.price_ref is not None else None,
        "sales_coefficient": float(mr.sales_coefficient) if mr.sales_coefficient is not None else None,
        "dispute_reason": mr.dispute_reason,
        "review_note": mr.review_note,
        "reviewed_at": format_beijing_datetime(mr.reviewed_at),
        "revertible": _is_revertible(mr),
        "item_name": rd.item_name,
        "item_url": rd.item_url,
        "item_image": rd.item_image,
        "platform": rd.platform,
        "item_id": rd.item_id,
        "brand_raw": rd.brand_raw,
        "shop_name": rd.shop_name,
        "ref_price": float(rd.ref_price) if rd.ref_price is not None else None,
        "price": float(rd.price) if rd.price is not None else None,
        "sales_qty": rd.sales_qty,
        "sales_amount": float(rd.sales_amount) if rd.sales_amount is not None else None,
        "url_mapping": {
            "id": mapping.id,
            "model_id": mapping.model_id,
            "brand_code": mapping.brand_code,
            "source": mapping.source,
        } if mapping else None,
        "candidates": [
            {
                "model_id": cand.model_id,
                "model_code": candidate_model.model_code if candidate_model else None,
                "brand_code": candidate_model.brand_code if candidate_model else None,
                "match_source": cand.match_source,
                "score": cand.score,
                "rank": cand.rank,
            }
            for cand, candidate_model in candidate_rows
        ],
    }


@router.get("/{clean_job_id}/missing-attrs", response_model=PaginatedResponse)
def list_missing_attrs(
    clean_job_id: int,
    category_name: Optional[str] = Query(None),
    sort_by: str = Query("default"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """
    列出已匹配/已确认但无属性标注的条目。
    match_status IN (matched, confirmed, url_matched) 且 match_result_attrs 为空。
    """
    subq = (
        db.query(MatchResultAttr.match_result_id)
        .filter(MatchResultAttr.match_result_id == MatchResult.id)
        .correlate(MatchResult)
        .exists()
    )
    q = (
        db.query(MatchResult, RawDataRecord, ModelRecord, Category)
        .join(RawDataRecord, MatchResult.raw_data_id == RawDataRecord.id)
        .outerjoin(ModelRecord, MatchResult.model_id == ModelRecord.id)
        .outerjoin(Category, ModelRecord.category_code == Category.code)
        .filter(
            MatchResult.clean_job_id == clean_job_id,
            MatchResult.match_status.in_(["matched", "confirmed", "url_matched"]),
            MatchResult.is_disabled == 0,
            ~subq,
        )
    )
    if category_name:
        q = q.filter(Category.code == category_name)

    if sort_by == "sales_qty_desc":
        # MySQL 旧版不支持 NULLS LAST 语法，用 ISNULL() 模拟（NULL 排末尾）
        q = q.order_by(func.isnull(RawDataRecord.sales_qty).asc(), RawDataRecord.sales_qty.desc())
    elif sort_by == "sales_qty_asc":
        q = q.order_by(func.isnull(RawDataRecord.sales_qty).asc(), RawDataRecord.sales_qty.asc())

    total = q.count()
    rows = q.offset((page - 1) * page_size).limit(page_size).all()

    items = []
    for mr, rd, model, cat in rows:
        items.append({
            "id": mr.id,
            "raw_data_id": mr.raw_data_id,
            "match_status": mr.match_status,
            "item_name": rd.item_name,
            "brand_raw": rd.brand_raw,
            "model_code": model.model_code if model else None,
            "brand_code": model.brand_code if model else None,
            "sales_qty": rd.sales_qty,
            "category_name": cat.name if cat else None,
        })
    return PaginatedResponse(total=total, page=page, page_size=page_size, items=items)


@router.put("/confirm/{match_id}", response_model=MatchResultOut)
def confirm_match(match_id: int, payload: dict, db: Session = Depends(get_db)):
    """
    人工确认或排除匹配结果。
    payload: { "model_id": 123 }  → 指定型号，status=confirmed
    payload: { "excluded": true } → 标记排除，status=excluded
    """
    mr = db.query(MatchResult).filter(MatchResult.id == match_id).first()
    if not mr:
        raise HTTPException(status_code=404, detail="匹配记录不存在")

    reason = (payload.get("reason") or "").strip() or None

    if payload.get("excluded"):
        _snapshot_prev_state(mr)
        mr.match_status = "excluded"
        mr.model_id = None
        mr.matched_by = "manual"
        mr.dispute_reason = None
        mr.review_note = reason
        mr.reviewed_at = datetime.utcnow()
    elif payload.get("disputed"):
        if not reason:
            raise HTTPException(status_code=400, detail="暂存争议需填写原因")
        _snapshot_prev_state(mr)
        mr.match_status = "disputed"
        mr.matched_by = "manual"
        mr.dispute_reason = reason
        mr.review_note = reason
        mr.reviewed_at = datetime.utcnow()
    elif payload.get("model_id") is not None:
        model_id = int(payload["model_id"])
        m = db.query(ModelRecord).filter(ModelRecord.id == model_id).first()
        if not m:
            raise HTTPException(status_code=404, detail="型号不存在")
        _snapshot_prev_state(mr)
        confirm_single_review(db, mr, m)
    else:
        raise HTTPException(status_code=400, detail="需提供 model_id、excluded=true 或 disputed=true")

    db.commit()

    # 型号确认后触发属性匹配和量价审核
    if mr.match_status in ("confirmed", "matched") and mr.model_id:
        from app.services.attribute_matcher import run_attribute_matching
        run_attribute_matching(db, [mr.id])
        try:
            audit_price(db, [mr.id])
        except Exception:
            logger.exception("Price audit failed after confirming match_id=%s", mr.id)
            db.rollback()

    db.refresh(mr)

    rd = db.query(RawDataRecord).filter(RawDataRecord.id == mr.raw_data_id).first()
    model_info = db.query(ModelRecord).filter(ModelRecord.id == mr.model_id).first() if mr.model_id else None

    return MatchResultOut(
        id=mr.id,
        clean_job_id=mr.clean_job_id,
        raw_data_id=mr.raw_data_id,
        model_id=mr.model_id,
        match_status=mr.match_status,
        matched_by=mr.matched_by,
        match_source=mr.match_source,
        price_flag=mr.price_flag,
        price_ref=mr.price_ref,
        sales_coefficient=mr.sales_coefficient,
        dispute_reason=mr.dispute_reason,
        review_note=mr.review_note,
        reviewed_at=mr.reviewed_at,
        item_name=rd.item_name if rd else None,
        item_url=rd.item_url if rd else None,
        brand_raw=rd.brand_raw if rd else None,
        model_code=model_info.model_code if model_info else None,
        brand_code=model_info.brand_code if model_info else None,
        sales_qty=rd.sales_qty if rd else None,
        revertible=_is_revertible(mr),
    )


# ── 批量确认：一键接受系统候选 ──────────────────────────────────────────

_BATCH_ALLOWED_STATUSES = {"text_only", "pending"}
_BATCH_IDS_LIMIT = 200
_BATCH_FILTER_LIMIT = 500
_INVALID_MODEL_CODES = {None, "", "-", "--"}


def _pick_top_candidate(db: Session, mr: MatchResult) -> Optional[ModelRecord]:
    """取该 mr 的首个候选型号（rank 最小），无候选返回 None。"""
    cand = (
        db.query(MatchResultCandidate)
        .filter(MatchResultCandidate.match_result_id == mr.id)
        .order_by(MatchResultCandidate.rank.asc(), MatchResultCandidate.id.asc())
        .first()
    )
    if not cand or not cand.model_id:
        return None
    return db.query(ModelRecord).filter(ModelRecord.id == cand.model_id).first()


def _candidate_is_valid(mr: MatchResult, model: Optional[ModelRecord]) -> bool:
    if not model:
        return False
    if getattr(mr, "brand_identified", 1) == 0:
        return False
    if model.brand_code in _INVALID_MODEL_CODES:
        return False
    if model.model_code in _INVALID_MODEL_CODES:
        return False
    return True


def _existing_url_mapping_conflict(
    db: Session, rd: RawDataRecord, model: ModelRecord
) -> Optional[ModelRecord]:
    """若同 platform+item_id 已有映射且指向不同型号，返回冲突的 ModelRecord。"""
    if not rd or not rd.platform or not rd.item_id:
        return None
    existing = (
        db.query(ItemUrlMapping)
        .filter_by(platform=rd.platform, item_id=rd.item_id)
        .first()
    )
    if not existing or existing.model_id == model.id:
        return None
    return db.query(ModelRecord).filter(ModelRecord.id == existing.model_id).first()


def _run_batch_confirm(
    db: Session, clean_job_id: int, targets: list[MatchResult]
) -> dict:
    """对给定 targets 逐条独立提交确认；返回统一响应结构。"""
    success = 0
    failures: list[dict] = []
    ok_ids: list[int] = []

    for mr in targets:
        rd = db.query(RawDataRecord).filter(RawDataRecord.id == mr.raw_data_id).first()
        item_name = rd.item_name if rd else None
        try:
            if mr.match_status not in _BATCH_ALLOWED_STATUSES:
                failures.append({"id": mr.id, "item_name": item_name, "reason": "状态已变更"})
                continue
            model = _pick_top_candidate(db, mr)
            if not _candidate_is_valid(mr, model):
                failures.append({"id": mr.id, "item_name": item_name, "reason": "候选型号无效"})
                continue
            conflict = _existing_url_mapping_conflict(db, rd, model)
            if conflict is not None:
                failures.append({
                    "id": mr.id, "item_name": item_name,
                    "reason": f"URL 映射冲突：指向 [{conflict.brand_code or '-'}] {conflict.model_code or '-'}",
                })
                continue
            # 条件更新保证并发安全
            updated = (
                db.query(MatchResult)
                .filter(
                    MatchResult.id == mr.id,
                    MatchResult.match_status.in_(list(_BATCH_ALLOWED_STATUSES)),
                )
                .update({MatchResult.match_status: mr.match_status}, synchronize_session=False)
            )
            if updated == 0:
                failures.append({"id": mr.id, "item_name": item_name, "reason": "状态已变更"})
                db.rollback()
                continue
            _snapshot_prev_state(mr)
            confirm_single_review(db, mr, model)
            db.commit()
            success += 1
            ok_ids.append(mr.id)
        except Exception:
            logger.exception("batch confirm failed for mr_id=%s", mr.id)
            db.rollback()
            failures.append({"id": mr.id, "item_name": item_name, "reason": "系统错误"})

    if ok_ids:
        try:
            from app.services.attribute_matcher import run_attribute_matching
            run_attribute_matching(db, ok_ids)
        except Exception:
            logger.exception("post-batch attribute matching failed for ids=%s", ok_ids)
            db.rollback()
        try:
            audit_price(db, ok_ids)
        except Exception:
            logger.exception("post-batch price audit failed for ids=%s", ok_ids)
            db.rollback()

    return {
        "success": success,
        "failed": len(failures),
        "failures": failures,
    }


@router.post("/{clean_job_id}/batch-confirm")
def batch_confirm(clean_job_id: int, payload: dict, db: Session = Depends(get_db)):
    """一键批量确认。支持 ids 模式与 filter 模式。"""
    mode = (payload or {}).get("mode")
    if mode == "ids":
        ids = payload.get("ids") or []
        if not isinstance(ids, list) or not ids:
            raise HTTPException(status_code=400, detail="ids 不能为空")
        if len(ids) > _BATCH_IDS_LIMIT:
            raise HTTPException(status_code=400, detail=f"单次最多确认 {_BATCH_IDS_LIMIT} 条")
        targets = (
            db.query(MatchResult)
            .filter(
                MatchResult.clean_job_id == clean_job_id,
                MatchResult.id.in_(ids),
            )
            .all()
        )
        # 保持前端传入顺序（顺便标出请求里但库里查不到的 id）
        by_id = {mr.id: mr for mr in targets}
        ordered = [by_id[i] for i in ids if i in by_id]
        missing = [i for i in ids if i not in by_id]
        result = _run_batch_confirm(db, clean_job_id, ordered)
        for i in missing:
            result["failures"].append({"id": i, "item_name": None, "reason": "状态已变更"})
            result["failed"] += 1
        return {
            "total": len(ids),
            "matched_total": len(ids),
            "truncated": False,
            **result,
        }
    if mode == "filter":
        f = payload.get("filter") or {}
        q = _build_review_queue_query(
            db, clean_job_id,
            tab=f.get("tab") or "",
            keyword=(f.get("keyword") or None),
            search_by=f.get("search_by") or "item_name",
            category_name=(f.get("category_name") or None),
            sort_by=f.get("sort_by") or "default",
        )
        matched_total = q.count()
        truncated = matched_total > _BATCH_FILTER_LIMIT
        rows = q.limit(_BATCH_FILTER_LIMIT).all()
        targets = [mr for mr, _rd, _model in rows]
        result = _run_batch_confirm(db, clean_job_id, targets)
        return {
            "total": len(targets),
            "matched_total": matched_total,
            "truncated": truncated,
            **result,
        }
    raise HTTPException(status_code=400, detail="mode 必须为 ids 或 filter")


@router.get("/{clean_job_id}/batch-confirm/preview")
def batch_confirm_preview(
    clean_job_id: int,
    tab: str = Query(...),
    keyword: Optional[str] = Query(None),
    search_by: str = Query("item_name"),
    category_name: Optional[str] = Query(None),
    sort_by: str = Query("default"),
    db: Session = Depends(get_db),
):
    q = _build_review_queue_query(
        db, clean_job_id, tab=tab, keyword=keyword, search_by=search_by,
        category_name=category_name, sort_by=sort_by,
    )
    rows = q.all()  # preview 不做上限（只统计），若 review 反馈慢再加

    dist: Counter = Counter()
    total_valid = 0
    total_invalid = 0
    for mr, _rd, _model in rows:
        cand_model = _pick_top_candidate(db, mr)
        if _candidate_is_valid(mr, cand_model):
            total_valid += 1
            dist[(cand_model.brand_code, cand_model.model_code)] += 1
        else:
            total_invalid += 1
    top = dist.most_common(20)
    return {
        "total_valid": total_valid,
        "total_invalid": total_invalid,
        "candidate_distribution": [
            {"brand_code": bc, "model_code": mc, "count": c}
            for (bc, mc), c in top
        ],
    }


# ── 单条撤销：回到操作前的原状态 ─────────────────────────────────────────

@router.post("/items/{match_id}/revert", response_model=MatchResultOut)
def revert_match(match_id: int, db: Session = Depends(get_db)):
    """撤销最近一次人工操作，把该条记录还原到操作前的 status/model_id/review 字段。

    只有 status 为 confirmed/excluded/disputed 且有 prev_* 快照的记录支持撤销；
    执行成功后 prev_* 快照会清空（暂不支持多级撤销）。
    """
    mr = db.query(MatchResult).filter(MatchResult.id == match_id).first()
    if not mr:
        raise HTTPException(status_code=404, detail="匹配记录不存在")
    if mr.match_status not in MANUAL_TERMINAL_STATUSES:
        raise HTTPException(status_code=400, detail="当前记录没有可撤销的历史操作")

    # 已确认的记录如果之前把 URL 映射写成新型号，撤销时不动 URL 映射库——
    # 避免误伤后来同链接的匹配；如需一并回滚需要单独在页面上处理。
    if mr.prev_match_status is not None:
        mr.match_status = mr.prev_match_status
        mr.model_id = mr.prev_model_id
        mr.matched_by = mr.prev_matched_by or "auto"
        mr.match_source = mr.prev_match_source
        mr.dispute_reason = mr.prev_dispute_reason
        mr.review_note = mr.prev_review_note
        mr.reviewed_at = mr.prev_reviewed_at
    else:
        # 老数据没有快照（迁移前误操作的历史记录），兜底重置为 pending
        mr.match_status = "pending"
        mr.model_id = None
        mr.matched_by = "auto"
        mr.match_source = None
        mr.dispute_reason = None
        mr.review_note = None
        mr.reviewed_at = None
    _clear_prev_state(mr)

    # 撤销后如果又回到有 model_id 的 matched/confirmed，可以重新跑属性匹配；
    # 但为了避免撤销引起额外副作用，这里保持简单：不重跑属性/价格审核。
    db.commit()
    db.refresh(mr)

    rd = db.query(RawDataRecord).filter(RawDataRecord.id == mr.raw_data_id).first()
    model_info = db.query(ModelRecord).filter(ModelRecord.id == mr.model_id).first() if mr.model_id else None
    return MatchResultOut(
        id=mr.id,
        clean_job_id=mr.clean_job_id,
        raw_data_id=mr.raw_data_id,
        model_id=mr.model_id,
        match_status=mr.match_status,
        matched_by=mr.matched_by,
        match_source=mr.match_source,
        price_flag=mr.price_flag,
        price_ref=float(mr.price_ref) if mr.price_ref is not None else None,
        sales_coefficient=float(mr.sales_coefficient) if mr.sales_coefficient is not None else None,
        dispute_reason=mr.dispute_reason,
        review_note=mr.review_note,
        reviewed_at=mr.reviewed_at,
        item_name=rd.item_name if rd else None,
        item_url=rd.item_url if rd else None,
        brand_raw=rd.brand_raw if rd else None,
        model_code=model_info.model_code if model_info else None,
        brand_code=model_info.brand_code if model_info else None,
        sales_qty=rd.sales_qty if rd else None,
        revertible=False,
    )


# ── 禁用 / 启用 ────────────────────────────────────────────────────────────

from pydantic import BaseModel as _PydanticBase
from typing import Optional as _Opt


class _DisableIn(_PydanticBase):
    reason: _Opt[str] = None


class _AvgPriceDisableIn(_PydanticBase):
    threshold: float = 200.0


class _CoefficientIn(_PydanticBase):
    coefficient: object


def _quantity_preview(cleaned_qty: Optional[int], raw_qty: Optional[int], coefficient) -> tuple[Optional[int], Optional[int]]:
    corrected_qty = cleaned_qty if cleaned_qty is not None else raw_qty
    if corrected_qty is None:
        return None, None
    if coefficient is None:
        return corrected_qty, corrected_qty
    return corrected_qty, round(float(corrected_qty) * float(coefficient))


def _reviewed_row_payload(mr, rd, model=None, cat=None, attr_count: int = 0, cleaned_qty: Optional[int] = None) -> MatchResultOut:
    corrected_qty, adjusted_qty = _quantity_preview(cleaned_qty, rd.sales_qty if rd else None, mr.sales_coefficient)
    return MatchResultOut(
        id=mr.id,
        clean_job_id=mr.clean_job_id,
        raw_data_id=mr.raw_data_id,
        model_id=mr.model_id,
        match_status=mr.match_status,
        matched_by=mr.matched_by,
        match_source=mr.match_source,
        is_disabled=mr.is_disabled,
        disable_reason=mr.disable_reason,
        brand_identified=mr.brand_identified,
        price_flag=mr.price_flag,
        price_ref=float(mr.price_ref) if mr.price_ref is not None else None,
        sales_coefficient=float(mr.sales_coefficient) if mr.sales_coefficient is not None else None,
        dispute_reason=mr.dispute_reason,
        review_note=mr.review_note,
        reviewed_at=mr.reviewed_at,
        item_name=rd.item_name if rd else None,
        item_url=rd.item_url if rd else None,
        brand_raw=rd.brand_raw if rd else None,
        model_code=model.model_code if model else None,
        brand_code=model.brand_code if model else None,
        attr_count=attr_count or 0,
        sales_qty=rd.sales_qty if rd else None,
        corrected_sales_qty=corrected_qty,
        adjusted_sales_qty=adjusted_qty,
        category_name=cat.name if cat else None,
        revertible=_is_revertible(mr),
    )


@router.get("/{clean_job_id}/reviewed", response_model=PaginatedResponse)
def list_reviewed(
    clean_job_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """分页查询已匹配/已确认行，用于量价审核与销量系数调整。"""
    clean_job = db.query(CleanJobRecord).filter(CleanJobRecord.id == clean_job_id).first()
    dispatch_batch_id = clean_job.dispatch_batch_id if clean_job else None
    if dispatch_batch_id is not None:
        di_join_cond = (
            (DispatchItem.raw_data_id == MatchResult.raw_data_id) &
            (DispatchItem.batch_id == dispatch_batch_id)
        )
    else:
        di_join_cond = (DispatchItem.raw_data_id == None)  # noqa: E711

    q = (
        db.query(
            MatchResult,
            RawDataRecord,
            ModelRecord,
            Category,
            func.count(MatchResultAttr.id).label("attr_count"),
            func.max(CleanedDataRecord.corrected_sales_qty).label("corrected_sales_qty"),
        )
        .join(RawDataRecord, MatchResult.raw_data_id == RawDataRecord.id)
        .outerjoin(ModelRecord, MatchResult.model_id == ModelRecord.id)
        .outerjoin(DispatchItem, di_join_cond)
        .outerjoin(Category, DispatchItem.category_code == Category.code)
        .outerjoin(MatchResultAttr, MatchResultAttr.match_result_id == MatchResult.id)
        .outerjoin(
            CleanedDataRecord,
            (CleanedDataRecord.clean_job_id == MatchResult.clean_job_id) &
            (CleanedDataRecord.raw_data_id == MatchResult.raw_data_id),
        )
        .filter(
            MatchResult.clean_job_id == clean_job_id,
            MatchResult.match_status.in_(["matched", "url_matched", "confirmed"]),
        )
        .group_by(MatchResult.id, RawDataRecord.id, ModelRecord.id, Category.id)
    )
    total = q.count()
    rows = q.order_by(MatchResult.id).offset((page - 1) * page_size).limit(page_size).all()
    items = [
        _reviewed_row_payload(mr, rd, model, cat, attr_count, cleaned_qty)
        for mr, rd, model, cat, attr_count, cleaned_qty in rows
    ]
    return PaginatedResponse(total=total, page=page, page_size=page_size, items=items)


@router.patch("/{match_id}/coefficient", response_model=MatchResultOut)
def update_sales_coefficient(match_id: int, payload: _CoefficientIn, db: Session = Depends(get_db)):
    """设置或清除单条匹配结果的销量调整系数。"""
    coefficient = payload.coefficient
    if coefficient is not None:
        if isinstance(coefficient, bool) or not isinstance(coefficient, (int, float)):
            raise HTTPException(status_code=400, detail="coefficient 必须是数字或 null")
        if coefficient < 0 or coefficient > 999.9999:
            raise HTTPException(status_code=400, detail="coefficient 必须在 0 到 999.9999 之间")

    mr = db.query(MatchResult).filter(MatchResult.id == match_id).first()
    if not mr:
        raise HTTPException(status_code=404, detail="匹配记录不存在")

    mr.sales_coefficient = coefficient
    db.commit()
    db.refresh(mr)

    row = (
        db.query(
            MatchResult,
            RawDataRecord,
            ModelRecord,
            Category,
            func.count(MatchResultAttr.id).label("attr_count"),
            func.max(CleanedDataRecord.corrected_sales_qty).label("corrected_sales_qty"),
        )
        .join(RawDataRecord, MatchResult.raw_data_id == RawDataRecord.id)
        .outerjoin(ModelRecord, MatchResult.model_id == ModelRecord.id)
        .outerjoin(Category, ModelRecord.category_code == Category.code)
        .outerjoin(MatchResultAttr, MatchResultAttr.match_result_id == MatchResult.id)
        .outerjoin(
            CleanedDataRecord,
            (CleanedDataRecord.clean_job_id == MatchResult.clean_job_id) &
            (CleanedDataRecord.raw_data_id == MatchResult.raw_data_id),
        )
        .filter(MatchResult.id == match_id)
        .group_by(MatchResult.id, RawDataRecord.id, ModelRecord.id, Category.id)
        .first()
    )
    return _reviewed_row_payload(*row)


@router.patch("/{match_id}/disable", response_model=MatchResultOut)
def disable_match(match_id: int, payload: _DisableIn, db: Session = Depends(get_db)):
    """单条禁用"""
    mr = db.query(MatchResult).filter(MatchResult.id == match_id).first()
    if not mr:
        raise HTTPException(status_code=404, detail="匹配记录不存在")
    mr.is_disabled = 1
    mr.disable_reason = payload.reason
    db.commit()
    db.refresh(mr)
    rd = db.query(RawDataRecord).filter(RawDataRecord.id == mr.raw_data_id).first()
    return MatchResultOut(
        id=mr.id, clean_job_id=mr.clean_job_id, raw_data_id=mr.raw_data_id,
        model_id=mr.model_id, match_status=mr.match_status, matched_by=mr.matched_by,
        match_source=mr.match_source, is_disabled=mr.is_disabled,
        disable_reason=mr.disable_reason,
        item_name=rd.item_name if rd else None,
        brand_raw=rd.brand_raw if rd else None,
    )


@router.patch("/{match_id}/enable", response_model=MatchResultOut)
def enable_match(match_id: int, db: Session = Depends(get_db)):
    """单条启用（清除禁用状态）"""
    mr = db.query(MatchResult).filter(MatchResult.id == match_id).first()
    if not mr:
        raise HTTPException(status_code=404, detail="匹配记录不存在")
    mr.is_disabled = 0
    mr.disable_reason = None
    db.commit()
    db.refresh(mr)
    rd = db.query(RawDataRecord).filter(RawDataRecord.id == mr.raw_data_id).first()
    return MatchResultOut(
        id=mr.id, clean_job_id=mr.clean_job_id, raw_data_id=mr.raw_data_id,
        model_id=mr.model_id, match_status=mr.match_status, matched_by=mr.matched_by,
        match_source=mr.match_source, is_disabled=mr.is_disabled,
        disable_reason=mr.disable_reason,
        item_name=rd.item_name if rd else None,
        brand_raw=rd.brand_raw if rd else None,
    )


@router.post("/{clean_job_id}/avg-price-disable")
def avg_price_disable(
    clean_job_id: int,
    payload: _AvgPriceDisableIn,
    db: Session = Depends(get_db),
):
    """批量均价禁用：price < threshold 的 matched/confirmed 行"""
    rows = (
        db.query(MatchResult)
        .join(RawDataRecord, MatchResult.raw_data_id == RawDataRecord.id)
        .filter(
            MatchResult.clean_job_id == clean_job_id,
            MatchResult.match_status.in_(["url_matched", "matched", "confirmed"]),
            MatchResult.is_disabled == 0,
            RawDataRecord.price < payload.threshold,
        )
        .all()
    )
    for mr in rows:
        mr.is_disabled = 1
        mr.disable_reason = "avg_price"
    db.commit()
    return {"disabled_count": len(rows)}


@router.get("/{clean_job_id}/disabled", response_model=PaginatedResponse)
def list_disabled(
    clean_job_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """分页查询禁用列表"""
    q = (
        db.query(MatchResult, RawDataRecord)
        .join(RawDataRecord, MatchResult.raw_data_id == RawDataRecord.id)
        .filter(
            MatchResult.clean_job_id == clean_job_id,
            MatchResult.is_disabled == 1,
        )
    )
    total = q.count()
    rows = q.offset((page - 1) * page_size).limit(page_size).all()
    items = [
        MatchResultOut(
            id=mr.id, clean_job_id=mr.clean_job_id, raw_data_id=mr.raw_data_id,
            model_id=mr.model_id, match_status=mr.match_status, matched_by=mr.matched_by,
            match_source=mr.match_source, is_disabled=mr.is_disabled,
            disable_reason=mr.disable_reason,
            item_name=rd.item_name, brand_raw=rd.brand_raw,
        )
        for mr, rd in rows
    ]
    return PaginatedResponse(total=total, page=page, page_size=page_size, items=items)
