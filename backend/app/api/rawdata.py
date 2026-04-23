from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, distinct
from app.models.database import get_db
from app.models.schemas import RawDataRecord, RawDataOut, PaginatedResponse

router = APIRouter(prefix="/api/rawdata", tags=["rawdata"])


def build_query(
    db: Session,
    file_id: Optional[int],
    platform: Optional[str],
    month: Optional[int],
    brand_std: Optional[str],
):
    q = db.query(RawDataRecord)
    if file_id is not None:
        q = q.filter(RawDataRecord.file_id == file_id)
    if platform:
        q = q.filter(RawDataRecord.platform.ilike(f"%{platform}%"))
    if month is not None:
        q = q.filter(RawDataRecord.month == month)
    if brand_std:
        q = q.filter(RawDataRecord.brand_std.ilike(f"%{brand_std}%"))
    return q


@router.get("", response_model=PaginatedResponse)
def list_raw_data(
    file_id: Optional[int] = Query(None),
    platform: Optional[str] = Query(None),
    month: Optional[int] = Query(None),
    brand_std: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
):
    q = build_query(db, file_id, platform, month, brand_std)
    total = q.count()
    items = q.order_by(RawDataRecord.id).offset((page - 1) * page_size).limit(page_size).all()
    return PaginatedResponse(
        total=total,
        page=page,
        page_size=page_size,
        items=[RawDataOut.model_validate(r) for r in items],
    )


@router.get("/stats")
def get_stats(
    file_id: Optional[int] = Query(None),
    platform: Optional[str] = Query(None),
    month: Optional[int] = Query(None),
    brand_std: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    q = build_query(db, file_id, platform, month, brand_std)
    result = q.with_entities(
        func.sum(RawDataRecord.sales_qty).label("total_qty"),
        func.sum(RawDataRecord.sales_amount).label("total_amount"),
        func.count(distinct(RawDataRecord.brand_std)).label("brand_count"),
        func.count(distinct(RawDataRecord.model_std)).label("model_count"),
    ).one()
    return {
        "total_qty": int(result.total_qty or 0),
        "total_amount": float(result.total_amount or 0),
        "brand_count": int(result.brand_count or 0),
        "model_count": int(result.model_count or 0),
    }


@router.get("/filters")
def get_filters(db: Session = Depends(get_db)):
    """返回可用的筛选枚举值"""
    platforms = [r[0] for r in db.query(distinct(RawDataRecord.platform)).filter(RawDataRecord.platform.isnot(None)).all()]
    months = sorted([r[0] for r in db.query(distinct(RawDataRecord.month)).filter(RawDataRecord.month.isnot(None)).all()])
    brands = sorted([r[0] for r in db.query(distinct(RawDataRecord.brand_std)).filter(RawDataRecord.brand_std.isnot(None)).all()])
    return {"platforms": platforms, "months": months, "brands": brands}
