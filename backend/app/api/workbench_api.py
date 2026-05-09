"""
查询工作台 API — 查询 luotu_analytics.published_items（已发布的分析数据）
支持多条件筛选、分页查询、全量导出 Excel
"""
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Optional
from urllib.parse import quote

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import distinct
from sqlalchemy.orm import Session

from app.models.analytics_db import get_analytics_db, PublishedItem, PublishedItemSpec

router = APIRouter(prefix="/api/workbench", tags=["workbench"])


class WorkbenchExportParams(BaseModel):
    month:         Optional[int] = None
    platform:      Optional[str] = None
    brand_code:    Optional[str] = None
    model_code:    Optional[str] = None
    category_name: Optional[str] = None
    keyword:       Optional[str] = None
    statuses: List[str] = ["matched", "confirmed", "url_matched"]
    year:     Optional[int] = None
    quarter:  Optional[int] = None

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
            "calc_price":             float(r.calc_price) if r.calc_price is not None else None,
            "corrected_sales_qty":    r.corrected_sales_qty,
            "corrected_sales_amount": float(r.corrected_sales_amount) if r.corrected_sales_amount is not None else None,
            "category_name": r.category_name,
            "category_lv0": r.category_lv0,
            "category_lv1": r.category_lv1,
            "category_lv2": r.category_lv2,
            "item_url": r.item_url,
        }
        for r in rows
    ]

    return {"total": total, "page": page, "page_size": page_size, "items": items}


@router.post("/export")
def export_data(payload: WorkbenchExportParams, db: Session = Depends(get_analytics_db)):
    """全量导出筛选结果为 Excel"""
    params = {
        "month":         payload.month,
        "platform":      payload.platform,
        "brand_code":    payload.brand_code,
        "model_code":    payload.model_code,
        "category_name": payload.category_name,
        "keyword":       payload.keyword,
    }
    params = {k: v for k, v in params.items() if v not in (None, "", [])}
    q = _build_query(db, params)

    # year + quarter / year-only month range filter
    if payload.year and payload.quarter:
        start_month = payload.year * 100 + (payload.quarter - 1) * 3 + 1
        end_month   = payload.year * 100 + payload.quarter * 3
        q = q.filter(PublishedItem.month >= start_month, PublishedItem.month <= end_month)
    elif payload.year:
        start_month = payload.year * 100 + 1
        end_month   = payload.year * 100 + 12
        q = q.filter(PublishedItem.month >= start_month, PublishedItem.month <= end_month)

    # NOTE: PublishedItem has no match_status column; statuses filter is intentionally skipped.

    total = q.count()

    if total == 0:
        raise HTTPException(status_code=404, detail="没有符合条件的数据")

    rows = q.order_by(PublishedItem.id.desc()).all()

    records = [
        {
            "_id": r.id,
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
            "计算价格":   float(r.calc_price) if r.calc_price is not None else None,
            "修正销量":   r.corrected_sales_qty,
            "修正销售额": float(r.corrected_sales_amount) if r.corrected_sales_amount is not None else None,
            "一级类目": r.category_lv1,
            "二级类目": r.category_lv2,
            "三级类目": r.category_lv3,
            "宝贝链接": r.item_url,
        }
        for r in rows
    ]

    df = pd.DataFrame(records)

    # 追加属性列（来自 published_item_specs）
    item_ids = [rec["_id"] for rec in records]
    spec_rows = (
        db.query(PublishedItemSpec)
        .filter(PublishedItemSpec.published_item_id.in_(item_ids))
        .all()
    )
    spec_index: dict = {}
    for s in spec_rows:
        spec_index.setdefault(s.published_item_id, {})[s.spec_name] = s.spec_value or ""
    all_attr_names = sorted({name for attrs in spec_index.values() for name in attrs})
    for attr_name in all_attr_names:
        df[f"attr_{attr_name}"] = [
            spec_index.get(rec["_id"], {}).get(attr_name, "")
            for rec in records
        ]

    # 删除内部辅助列
    df.drop(columns=["_id"], inplace=True)

    export_dir = Path("/app/exports")
    export_dir.mkdir(parents=True, exist_ok=True)

    token = uuid.uuid4().hex
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"分析数据_{ts}_{total}条.xlsx"
    filepath = export_dir / f"{token}_{filename}"
    df.to_excel(str(filepath), index=False)

    _token_map[token] = str(filepath)
    return {"token": token, "filename": filename, "rows": total}


@router.get("/item-attrs/{published_item_id}")
def get_item_attrs(
    published_item_id: int,
    db: Session = Depends(get_analytics_db),
):
    """按 published_item_id 返回属性列表 [{attr_name, attr_value}]"""
    specs = (
        db.query(PublishedItemSpec)
        .filter(PublishedItemSpec.published_item_id == published_item_id)
        .order_by(PublishedItemSpec.spec_name)
        .all()
    )
    return [{"attr_name": s.spec_name, "attr_value": s.spec_value} for s in specs]


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
