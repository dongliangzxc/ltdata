"""
查询工作台 API
- 针对已清洗数据做多条件筛选、分页查询
- 全量导出为 Excel
"""
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import quote

import pandas as pd
from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse
from sqlalchemy import distinct
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.database import get_db
from app.models.schemas import CleanedDataRecord

router = APIRouter(prefix="/api/workbench", tags=["workbench"])

# 导出文件 token 映射（内存，与 export.py 独立）
_token_map: dict[str, str] = {}


def _build_query(db: Session, params: dict):
    """根据筛选参数构建 SQLAlchemy Query"""
    q = db.query(CleanedDataRecord)

    if params.get("clean_job_id"):
        q = q.filter(CleanedDataRecord.clean_job_id == int(params["clean_job_id"]))
    if params.get("month"):
        q = q.filter(CleanedDataRecord.month == int(params["month"]))
    if params.get("platform"):
        q = q.filter(CleanedDataRecord.platform == params["platform"])
    if params.get("brand_raw"):
        q = q.filter(CleanedDataRecord.brand_raw == params["brand_raw"])
    if params.get("category_lv1"):
        q = q.filter(CleanedDataRecord.category_lv1 == params["category_lv1"])
    if params.get("category_lv2"):
        q = q.filter(CleanedDataRecord.category_lv2 == params["category_lv2"])
    if params.get("keyword"):
        q = q.filter(CleanedDataRecord.item_name.ilike(f"%{params['keyword']}%"))

    return q


@router.get("/filters")
def get_filters(
    clean_job_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    """获取可用的筛选项枚举值（月份、平台、品牌、一级类目）"""
    q = db.query(CleanedDataRecord)
    if clean_job_id:
        q = q.filter(CleanedDataRecord.clean_job_id == clean_job_id)

    months = sorted(
        [r[0] for r in q.with_entities(distinct(CleanedDataRecord.month)).all() if r[0]],
        reverse=True,
    )
    platforms = sorted(
        [r[0] for r in q.with_entities(distinct(CleanedDataRecord.platform)).all() if r[0]]
    )
    brands = sorted(
        [r[0] for r in q.with_entities(distinct(CleanedDataRecord.brand_raw)).all() if r[0]]
    )
    categories = sorted(
        [r[0] for r in q.with_entities(distinct(CleanedDataRecord.category_lv1)).all() if r[0]]
    )

    return {
        "months": months,
        "platforms": platforms,
        "brands": brands,
        "categories": categories,
    }


@router.get("/data")
def query_data(
    clean_job_id: Optional[int] = Query(None),
    month: Optional[int] = Query(None),
    platform: Optional[str] = Query(None),
    brand_raw: Optional[str] = Query(None),
    category_lv1: Optional[str] = Query(None),
    category_lv2: Optional[str] = Query(None),
    keyword: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """多条件筛选清洗数据，分页返回"""
    params = dict(
        clean_job_id=clean_job_id,
        month=month,
        platform=platform,
        brand_raw=brand_raw,
        category_lv1=category_lv1,
        category_lv2=category_lv2,
        keyword=keyword,
    )
    q = _build_query(db, params)
    total = q.count()
    rows = (
        q.order_by(CleanedDataRecord.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    items = [
        {
            "id": r.id,
            "month": r.month,
            "platform": r.platform,
            "item_name": r.item_name,
            "brand_raw": r.brand_raw,
            "shop_name": r.shop_name,
            "ref_price": float(r.ref_price) if r.ref_price is not None else None,
            "sales_qty": r.sales_qty,
            "category_lv1": r.category_lv1,
            "category_lv2": r.category_lv2,
            "category_lv3": r.category_lv3,
            "item_url": r.item_url,
        }
        for r in rows
    ]

    return {"total": total, "page": page, "page_size": page_size, "items": items}


@router.post("/export")
def export_data(
    payload: dict,
    db: Session = Depends(get_db),
):
    """全量导出筛选结果为 Excel，返回下载 token"""
    params = {k: v for k, v in payload.items() if v not in (None, "", [])}
    q = _build_query(db, params)
    total = q.count()

    if total == 0:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="没有符合条件的数据")

    rows = q.order_by(CleanedDataRecord.id.desc()).all()

    records = [
        {
            "月份": r.month,
            "平台": r.platform,
            "宝贝名称": r.item_name,
            "品牌": r.brand_raw,
            "店铺": r.shop_name,
            "参考价格": float(r.ref_price) if r.ref_price is not None else None,
            "销量": r.sales_qty,
            "一级类目": r.category_lv1,
            "二级类目": r.category_lv2,
            "三级类目": r.category_lv3,
            "宝贝链接": r.item_url,
        }
        for r in rows
    ]

    df = pd.DataFrame(records)

    export_dir = Path(settings.EXPORT_DIR if hasattr(settings, "EXPORT_DIR") else "/app/exports")
    export_dir.mkdir(parents=True, exist_ok=True)

    token = uuid.uuid4().hex
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"查询结果_{ts}_{total}条.xlsx"
    filepath = export_dir / f"{token}_{filename}"

    df.to_excel(str(filepath), index=False)

    _token_map[token] = str(filepath)

    return {"token": token, "filename": filename, "rows": total}


@router.get("/download/{token}")
def download_export(token: str):
    """通过 token 下载导出文件"""
    from fastapi import HTTPException
    file_path = _token_map.get(token)
    if not file_path or not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="文件不存在或已过期")

    filename = Path(file_path).name
    original_name = "_".join(filename.split("_")[1:]) if "_" in filename else filename

    return FileResponse(
        path=file_path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(original_name)}"},
    )
