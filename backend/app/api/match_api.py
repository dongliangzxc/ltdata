"""
型号匹配 API
"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.models.database import get_db
from app.models.schemas import (
    MatchResult, MatchResultOut, MatchSummary,
    CleanJobRecord, RawDataRecord, ModelRecord,
    PaginatedResponse,
)
from app.services.matcher import run_match

router = APIRouter(prefix="/api/match", tags=["match"])


@router.post("/run", response_model=MatchSummary)
def run_match_job(payload: dict, db: Session = Depends(get_db)):
    """对清洗任务执行型号匹配，返回匹配统计"""
    clean_job_id: int = payload.get("clean_job_id")
    if not clean_job_id:
        raise HTTPException(status_code=400, detail="clean_job_id 不能为空")

    job = db.query(CleanJobRecord).filter(CleanJobRecord.id == clean_job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="清洗任务不存在")

    try:
        stats = run_match(db, clean_job_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"匹配失败: {str(e)}")

    return MatchSummary(
        clean_job_id=clean_job_id,
        total=stats["total"],
        matched=stats["matched"],
        pending=stats["pending"],
        confirmed=0,
        excluded=0,
    )


@router.get("/{clean_job_id}/summary", response_model=MatchSummary)
def get_match_summary(clean_job_id: int, db: Session = Depends(get_db)):
    """查看某次清洗任务的匹配统计"""
    rows = db.query(MatchResult).filter(MatchResult.clean_job_id == clean_job_id).all()
    if not rows:
        raise HTTPException(status_code=404, detail="该清洗任务暂无匹配结果，请先执行匹配")

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

    # 拼装 item_name / brand_raw
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
