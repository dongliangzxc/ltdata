"""
查询工作台 API — 查询 luotu_analytics.published_items（已发布的分析数据）
支持多条件筛选、分页查询、全量导出 Excel
"""
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import quote

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import distinct
from sqlalchemy.orm import Session

from app.models.analytics_db import get_analytics_db, PublishedItem

router = APIRouter(prefix="/api/workbench", tags=["workbench"])

_token_map: dict[str, str] = {}


def _build_query(db: Session, params: dict):
    q = db.query(PublishedItem)

    if params.get("month"):
        q = q.filter(PublishedItem.month == int(params["month"]))
    if params.get("platform"):
        q = q.filter(PublishedItem.platform == params["platform"])
    if params.get("brand_code"):
        q = q.filter(PublishedItem.brand_code == params["brand_code"])
    if params.get("model_code"):
        q = q.filter(PublishedItem.model_code == params["model_code"])
    if params.get("category_name"):
        q = q.filter(PublishedItem.category_name == params["category_name"])
    if params.get("category_lv1"):
        q = q.filter(PublishedItem.category_lv1 == params["category_lv1"])
    if params.get("category_lv2"):
        q = q.filter(PublishedItem.category_lv2 == params["category_lv2"])
    if params.get("keyword"):
        q = q.filter(PublishedItem.item_name.ilike(f"%{params['keyword']}%"))

    return q


@router.get("/filters")
def get_filters(db: Session = Depends(get_analytics_db)):
    """获取可用筛选枚举值"""
    def _vals(col):
        return sorted([r[0] for r in db.query(distinct(col)).all() if r[0]])

    months = sorted(
        [r[0] for r in db.query(distinct(PublishedItem.month)).all() if r[0]],
        reverse=True,
    )
    return {
        "months": months,
        "platforms": _vals(PublishedItem.platform),
        "brands": _vals(PublishedItem.brand_code),
        "models": _vals(PublishedItem.model_code),
        "categories": _vals(PublishedItem.category_name),
    }


@router.get("/data")
def query_data(
    month: Optional[int] = Query(None),
    platform: Optional[str] = Query(None),
    brand_code: Optional[str] = Query(None),
    model_code: Optional[str] = Query(None),
    category_name: Optional[str] = Query(None),
    category_lv1: Optional[str] = Query(None),
    category_lv2: Optional[str] = Query(None),
    keyword: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_analytics_db),
):
    params = dict(
        month=month, platform=platform, brand_code=brand_code,
        model_code=model_code, category_name=category_name,
        category_lv1=category_lv1,
        category_lv2=category_lv2, keyword=keyword,
    )
    q = _build_query(db, params)
    total = q.count()
    rows = (
        q.order_by(PublishedItem.id.desc())
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
            "brand_code": r.brand_code,
            "brand_name": r.brand_name,
            "model_code": r.model_code,
            "model_name": r.model_name,
            "shop_name": r.shop_name,
            "ref_price": float(r.ref_price) if r.ref_price is not None else None,
            "sales_qty": r.sales_qty,
            "category_name": r.category_name,
            "category_lv1": r.category_lv1,
            "category_lv2": r.category_lv2,
            "item_url": r.item_url,
        }
        for r in rows
    ]

    return {"total": total, "page": page, "page_size": page_size, "items": items}


@router.post("/export")
def export_data(payload: dict, db: Session = Depends(get_analytics_db)):
    """全量导出筛选结果为 Excel"""
    params = {k: v for k, v in payload.items() if v not in (None, "", [])}
    q = _build_query(db, params)
    total = q.count()

    if total == 0:
        raise HTTPException(status_code=404, detail="没有符合条件的数据")

    rows = q.order_by(PublishedItem.id.desc()).all()

    records = [
        {
            "月份": r.month,
            "平台": r.platform,
            "宝贝名称": r.item_name,
            "品牌代码": r.brand_code,
            "品牌名称": r.brand_name,
            "型号代码": r.model_code,
            "型号名称": r.model_name,
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

    export_dir = Path("/app/exports")
    export_dir.mkdir(parents=True, exist_ok=True)

    token = uuid.uuid4().hex
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"分析数据_{ts}_{total}条.xlsx"
    filepath = export_dir / f"{token}_{filename}"
    df.to_excel(str(filepath), index=False)

    _token_map[token] = str(filepath)
    return {"token": token, "filename": filename, "rows": total}


@router.get("/download/{token}")
def download_export(token: str):
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
