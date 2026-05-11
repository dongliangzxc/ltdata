"""
型号匹配 API
"""
import time
from threading import Thread
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.models.database import get_db, SessionLocal
from sqlalchemy import func
from app.models.schemas import (
    MatchResult, MatchResultOut, MatchSummary,
    CleanJobRecord, RawDataRecord, ModelRecord,
    MatchResultAttr, MatchResultCandidate, MatchCandidateOut, ItemUrlMapping, Category,
    PaginatedResponse,
)
from app.services.matcher import run_match

router = APIRouter(prefix="/api/match", tags=["match"])

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
            pending=0, confirmed=0, excluded=0, disabled=0,
        )

    total = len(rows)
    status_count: dict[str, int] = {}
    for r in rows:
        status_count[r.match_status] = status_count.get(r.match_status, 0) + 1

    disabled_count = sum(1 for r in rows if r.is_disabled == 1)
    unidentified_brand_count = sum(1 for r in rows if getattr(r, 'brand_identified', 1) == 0 and r.match_status == "pending")

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
        matched=status_count.get("matched", 0),
        text_only=status_count.get("text_only", 0),
        pending=status_count.get("pending", 0),
        confirmed=status_count.get("confirmed", 0),
        excluded=status_count.get("excluded", 0),
        disabled=disabled_count,
        unidentified_brand=unidentified_brand_count,
        missing_attrs=missing_attrs_count,
    )


@router.get("/{clean_job_id}/pending", response_model=PaginatedResponse)
def list_pending(
    clean_job_id: int,
    keyword: Optional[str] = Query(None),
    status: str = Query("pending"),
    brand_identified: Optional[int] = Query(None),
    category_name: Optional[str] = Query(None),
    sort_by: str = Query("default"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """分页查询待处理条目，status=pending 或 text_only"""
    allowed_statuses = {"pending", "text_only"}
    if status not in allowed_statuses:
        status = "pending"

    q = (
        db.query(MatchResult, RawDataRecord, ModelRecord, Category, func.count(MatchResultAttr.id).label("attr_count"))
        .join(RawDataRecord, MatchResult.raw_data_id == RawDataRecord.id)
        .outerjoin(ModelRecord, MatchResult.model_id == ModelRecord.id)
        .outerjoin(Category, ModelRecord.category_code == Category.code)
        .outerjoin(MatchResultAttr, MatchResultAttr.match_result_id == MatchResult.id)
        .filter(
            MatchResult.clean_job_id == clean_job_id,
            MatchResult.match_status == status,
        )
        .group_by(MatchResult.id, RawDataRecord.id, ModelRecord.id, Category.id)
    )
    if keyword:
        q = q.filter(RawDataRecord.item_name.ilike(f"%{keyword}%"))
    if brand_identified is not None:
        q = q.filter(MatchResult.brand_identified == brand_identified)
    if category_name:
        q = q.filter(Category.code == category_name)

    if sort_by == "sales_qty_desc":
        q = q.order_by(RawDataRecord.sales_qty.desc().nullslast())
    elif sort_by == "sales_qty_asc":
        q = q.order_by(RawDataRecord.sales_qty.asc().nullslast())

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
    列出已匹配/已确认但无属性标注的条目（用于「未补属性」Tab）。
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
        q = q.order_by(RawDataRecord.sales_qty.desc().nullslast())
    elif sort_by == "sales_qty_asc":
        q = q.order_by(RawDataRecord.sales_qty.asc().nullslast())

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

    if payload.get("excluded"):
        mr.match_status = "excluded"
        mr.model_id = None
        mr.matched_by = "manual"
    elif payload.get("model_id") is not None:
        model_id = int(payload["model_id"])
        m = db.query(ModelRecord).filter(ModelRecord.id == model_id).first()
        if not m:
            raise HTTPException(status_code=404, detail="型号不存在")
        prev_status = mr.match_status
        mr.model_id = model_id
        mr.match_status = "confirmed"
        mr.matched_by = "manual"

        # 方案 A：text_only 条目确认时，自动将 item_url 写入 URL 映射管理
        if prev_status == "text_only" and mr.raw_data_id:
            rd_for_url = db.query(RawDataRecord).filter(RawDataRecord.id == mr.raw_data_id).first()
            if rd_for_url and rd_for_url.item_url and rd_for_url.platform and rd_for_url.item_id:
                existing_mapping = db.query(ItemUrlMapping).filter_by(
                    platform=rd_for_url.platform, item_id=rd_for_url.item_id
                ).first()
                if existing_mapping:
                    existing_mapping.model_id = model_id
                    existing_mapping.item_url = rd_for_url.item_url
                else:
                    db.add(ItemUrlMapping(
                        platform=rd_for_url.platform,
                        item_id=rd_for_url.item_id,
                        item_url=rd_for_url.item_url,
                        model_id=model_id,
                        price=rd_for_url.price,
                    ))
    else:
        raise HTTPException(status_code=400, detail="需提供 model_id 或 excluded=true")

    db.commit()

    # 型号确认后触发属性匹配
    if mr.match_status in ("confirmed", "matched") and mr.model_id:
        from app.services.attribute_matcher import run_attribute_matching
        run_attribute_matching(db, [mr.id])

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
        item_name=rd.item_name if rd else None,
        brand_raw=rd.brand_raw if rd else None,
        model_code=model_info.model_code if model_info else None,
        brand_code=model_info.brand_code if model_info else None,
    )


# ── 禁用 / 启用 ────────────────────────────────────────────────────────────

from pydantic import BaseModel as _PydanticBase
from typing import Optional as _Opt


class _DisableIn(_PydanticBase):
    reason: _Opt[str] = None


class _AvgPriceDisableIn(_PydanticBase):
    threshold: float = 200.0


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
