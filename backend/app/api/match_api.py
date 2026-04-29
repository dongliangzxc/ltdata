"""
型号匹配 API
"""
import time
from threading import Thread
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.models.database import get_db, SessionLocal
from app.models.schemas import (
    MatchResult, MatchResultOut, MatchSummary,
    CleanJobRecord, RawDataRecord, ModelRecord,
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
            total=0, matched=0, pending=0, confirmed=0, excluded=0,
        )

    total = len(rows)
    status_count: dict[str, int] = {}
    for r in rows:
        status_count[r.match_status] = status_count.get(r.match_status, 0) + 1

    return MatchSummary(
        clean_job_id=clean_job_id,
        total=total,
        matched=status_count.get("matched", 0),
        pending=status_count.get("pending", 0),
        confirmed=status_count.get("confirmed", 0),
        excluded=status_count.get("excluded", 0),
    )


@router.get("/{clean_job_id}/pending", response_model=PaginatedResponse)
def list_pending(
    clean_job_id: int,
    keyword: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """分页查询待确认条目（status=pending），支持关键词搜索宝贝名称"""
    q = (
        db.query(MatchResult, RawDataRecord)
        .join(RawDataRecord, MatchResult.raw_data_id == RawDataRecord.id)
        .filter(
            MatchResult.clean_job_id == clean_job_id,
            MatchResult.match_status == "pending",
        )
    )
    if keyword:
        q = q.filter(RawDataRecord.item_name.ilike(f"%{keyword}%"))

    total = q.count()
    rows = q.offset((page - 1) * page_size).limit(page_size).all()

    items = []
    for mr, rd in rows:
        items.append(MatchResultOut(
            id=mr.id,
            clean_job_id=mr.clean_job_id,
            raw_data_id=mr.raw_data_id,
            model_id=mr.model_id,
            match_status=mr.match_status,
            matched_by=mr.matched_by,
            item_name=rd.item_name,
            brand_raw=rd.brand_raw,
            model_code=None,
            brand_code=None,
        ))

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
        mr.model_id = model_id
        mr.match_status = "confirmed"
        mr.matched_by = "manual"
    else:
        raise HTTPException(status_code=400, detail="需提供 model_id 或 excluded=true")

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
            MatchResult.match_status.in_(["matched", "confirmed"]),
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
