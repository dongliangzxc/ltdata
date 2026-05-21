import io
from typing import List, Optional
from urllib.parse import quote
import pandas as pd
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import func, distinct, asc, desc
from app.models.database import get_db
from app.models.schemas import RawDataRecord, RawDataOut, PaginatedResponse

router = APIRouter(prefix="/api/rawdata", tags=["rawdata"])

SORTABLE_FIELDS = {
    "sales_qty": RawDataRecord.sales_qty,
    "sales_amount": RawDataRecord.sales_amount,
    "price": RawDataRecord.price,
    "month": RawDataRecord.month,
}

def build_query(
    db,
    file_id,
    platform,
    month,
    brand_std,
    brand_raw=None,
    item_name=None,
    price_min=None,
    price_max=None,
    months=None,
):
    q = db.query(RawDataRecord)
    if file_id is not None:
        q = q.filter(RawDataRecord.file_id == file_id)
    if platform and platform.strip():
        q = q.filter(RawDataRecord.platform.ilike(f"%{platform.strip()}%"))
    if months:
        q = q.filter(RawDataRecord.month.in_(months))
    elif month is not None:
        q = q.filter(RawDataRecord.month == month)
    if brand_std and brand_std.strip():
        q = q.filter(RawDataRecord.brand_std.ilike(f"%{brand_std.strip()}%"))
    if brand_raw and brand_raw.strip():
        q = q.filter(RawDataRecord.brand_raw.ilike(f"%{brand_raw.strip()}%"))
    if item_name and item_name.strip():
        q = q.filter(RawDataRecord.item_name.ilike(f"%{item_name.strip()}%"))
    if price_min is not None:
        q = q.filter(RawDataRecord.price >= price_min)
    if price_max is not None:
        q = q.filter(RawDataRecord.price <= price_max)
    return q


EXPORT_COLUMNS = [
    ("platform",     "平台"),
    ("month",        "月份"),
    ("category_lv0", "一级品类"),
    ("brand_raw",    "品牌原始值"),
    ("brand_std",    "标准品牌"),
    ("model_std",    "型号"),
    ("item_name",    "宝贝名称"),
    ("shop_name",    "店铺"),
    ("item_id",      "商品ID"),
    ("item_url",     "商品链接"),
    ("sales_qty",    "销量"),
    ("sales_amount", "销售额"),
    ("price",        "价格"),
    ("ref_price",    "参考价"),
]


@router.get("/export")
def export_raw_data(
    file_id: Optional[int] = Query(None),
    platform: Optional[str] = Query(None),
    month: Optional[int] = Query(None),
    months: Optional[List[int]] = Query(None),
    brand_std: Optional[str] = Query(None),
    brand_raw: Optional[str] = Query(None),
    item_name: Optional[str] = Query(None),
    price_min: Optional[float] = Query(None, ge=0),
    price_max: Optional[float] = Query(None, ge=0),
    db: Session = Depends(get_db),
):
    """导出原始数据为 Excel，支持与列表相同的过滤参数。"""
    rows = build_query(
        db,
        file_id,
        platform,
        month,
        brand_std,
        brand_raw,
        item_name,
        price_min,
        price_max,
        months,
    ).order_by(RawDataRecord.id).all()
    data = [
        {label: getattr(r, field, None) for field, label in EXPORT_COLUMNS}
        for r in rows
    ]
    df = pd.DataFrame(data, columns=[label for _, label in EXPORT_COLUMNS])
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="原始数据")
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote('rawdata_export.xlsx')}"},
    )


@router.get("", response_model=PaginatedResponse)
def list_raw_data(
    file_id: Optional[int] = Query(None),
    platform: Optional[str] = Query(None),
    month: Optional[int] = Query(None),
    months: Optional[List[int]] = Query(None),
    brand_std: Optional[str] = Query(None),
    brand_raw: Optional[str] = Query(None),
    item_name: Optional[str] = Query(None),
    price_min: Optional[float] = Query(None, ge=0),
    price_max: Optional[float] = Query(None, ge=0),
    sort_by: Optional[str] = Query(None),
    sort_order: Optional[str] = Query("desc"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
):
    q = build_query(db, file_id, platform, month, brand_std, brand_raw, item_name, price_min, price_max, months)
    total = q.count()

    # 排序
    if sort_by and sort_by in SORTABLE_FIELDS:
        col = SORTABLE_FIELDS[sort_by]
        q = q.order_by(desc(col) if sort_order == "desc" else asc(col))
    else:
        q = q.order_by(RawDataRecord.id)

    items = q.offset((page - 1) * page_size).limit(page_size).all()
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
    months: Optional[List[int]] = Query(None),
    brand_std: Optional[str] = Query(None),
    brand_raw: Optional[str] = Query(None),
    item_name: Optional[str] = Query(None),
    price_min: Optional[float] = Query(None, ge=0),
    price_max: Optional[float] = Query(None, ge=0),
    db: Session = Depends(get_db),
):
    q = build_query(db, file_id, platform, month, brand_std, brand_raw, item_name, price_min, price_max, months)
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
