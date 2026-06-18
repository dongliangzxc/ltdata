"""
查询工作台 API — 查询 luotu_analytics.published_items（已发布的分析数据）
支持多条件筛选、分页查询、异步导出 Excel（带进度）
"""
import os
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from openpyxl import Workbook
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import distinct
from sqlalchemy.orm import Session

from app.models.analytics_db import get_analytics_db, AnalyticsSession, PublishedItem, PublishedItemSpec
from app.models.database import get_db, SessionLocal
from app.models.schemas import MatchResult, ModelAlias, RawDataRecord, WorkbenchExportJob
from app.utils.time_utils import format_beijing_datetime
from app.services.export_guards import reserve_async_export_capacity

router = APIRouter(prefix="/api/workbench", tags=["workbench"])


class WorkbenchExportParams(BaseModel):
    year:          Optional[int] = None
    month:         Optional[int] = None
    category_name: Optional[str] = None
    platform:      Optional[str] = None
    brand_code:    Optional[str] = None
    model_code:    Optional[str] = None
    item_url:      Optional[str] = None
    keyword:       Optional[str] = None
    quarter:       Optional[int] = None


# 内存进度表：job_id → 0-100，线程结束后清除
_wb_progress: dict[int, int] = {}


_MATCH_SOURCE_LABELS = {
    "s0": "URL映射命中",
    "historical": "历史库命中",
    "s0.5": "规则命中",
    "s1": "品牌字段匹配",
    "s2": "标题品牌码匹配",
    "s3": "标题品牌名匹配",
    "s4": "型号码兜底匹配",
    "manual": "人工确认",
}


def _match_source_label(source: str | None) -> str:
    if not source:
        return "-"
    return _MATCH_SOURCE_LABELS.get(source, source)


def _year_from_month(month: int | None) -> int | None:
    if not month:
        return None
    return month // 100


def _load_workbench_context(rows: list[PublishedItem]) -> tuple[dict[int, tuple[MatchResult, RawDataRecord]], dict[str, list[str]]]:
    match_result_ids = [r.match_result_id for r in rows if r.match_result_id]
    if not match_result_ids:
        return {}, {}

    luotu_db = SessionLocal()
    try:
        match_rows = (
            luotu_db.query(MatchResult, RawDataRecord)
            .join(RawDataRecord, RawDataRecord.id == MatchResult.raw_data_id)
            .filter(MatchResult.id.in_(match_result_ids))
            .all()
        )
        match_index = {mr.id: (mr, raw) for mr, raw in match_rows}
        model_id_to_code = {
            match_index[r.match_result_id][0].model_id: r.model_code
            for r in rows
            if r.match_result_id in match_index and r.model_code
        }
        alias_index: dict[str, list[str]] = {}
        if model_id_to_code:
            alias_rows = (
                luotu_db.query(ModelAlias.alias_code, ModelAlias.model_id)
                .filter(ModelAlias.model_id.in_(model_id_to_code.keys()))
                .all()
            )
            for alias_code, model_id in alias_rows:
                model_code = model_id_to_code.get(model_id)
                if model_code and alias_code:
                    alias_index.setdefault(model_code, []).append(alias_code)
        return match_index, alias_index
    finally:
        luotu_db.close()


def _build_query(db: Session, params: dict):
    q = db.query(PublishedItem)

    if params.get("year") and params.get("quarter"):
        year = int(params["year"])
        start_m = year * 100 + (int(params["quarter"]) - 1) * 3 + 1
        end_m = year * 100 + int(params["quarter"]) * 3
        q = q.filter(PublishedItem.month >= start_m, PublishedItem.month <= end_m)
    elif params.get("year"):
        start_m = int(params["year"]) * 100 + 1
        end_m = int(params["year"]) * 100 + 12
        q = q.filter(PublishedItem.month >= start_m, PublishedItem.month <= end_m)
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
    if params.get("item_url"):
        q = q.filter(PublishedItem.item_url.ilike(f"%{params['item_url']}%"))
    if params.get("keyword"):
        q = q.filter(PublishedItem.item_name.ilike(f"%{params['keyword']}%"))

    return q


_EXPORT_DIR = Path("/app/exports")


def _run_wb_export_thread(job_id: int, params: dict):
    """后台线程：查询数据、构建 DataFrame、写 Excel，更新 job 状态。"""
    db = SessionLocal()          # luotu DB（存 job 记录）
    adb = AnalyticsSession()     # analytics DB（读数据）
    try:
        job = db.query(WorkbenchExportJob).filter_by(id=job_id).first()
        if not job:
            return
        job.status = "running"
        db.commit()
        _wb_progress[job_id] = 5

        # 1. 查询 PublishedItems（5→10%）
        q = _build_query(adb, params).order_by(PublishedItem.id.desc())

        total = q.count()
        if total == 0:
            job.status = "error"
            job.error_msg = "没有符合条件的数据"
            job.finished_at = datetime.utcnow()
            db.commit()
            return
        _wb_progress[job_id] = 10
        job.progress = 10
        db.commit()

        page_size = 5000
        spec_batch_size = 500
        all_attr_names: set[str] = set()
        for offset in range(0, total, page_size):
            page_rows = q.offset(offset).limit(page_size).all()
            item_ids = [r.id for r in page_rows]
            for i in range(0, len(item_ids), spec_batch_size):
                batch = item_ids[i: i + spec_batch_size]
                if not batch:
                    continue
                names = (
                    adb.query(distinct(PublishedItemSpec.spec_name))
                    .filter(PublishedItemSpec.published_item_id.in_(batch))
                    .all()
                )
                all_attr_names.update(name for (name,) in names if name)
            _wb_progress[job_id] = 10 + int(25 * min(offset + page_size, total) / max(total, 1))

        attr_columns = [f"attr_{name}" for name in sorted(all_attr_names)]
        base_columns = [
            "月份", "平台", "宝贝名称", "品牌代码", "品牌名称", "型号代码", "型号名称", "店铺",
            "参考价格", "销量", "计算价格", "修正销量", "修正销售额", "一级类目", "二级类目", "三级类目", "宝贝链接",
        ]
        _wb_progress[job_id] = 35

        # 2. 分页写 Excel（35→95%）
        _EXPORT_DIR.mkdir(parents=True, exist_ok=True)
        token = uuid.uuid4().hex
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"分析数据_{ts}_{total}条.xlsx"
        filepath = _EXPORT_DIR / f"{token}_{filename}"
        workbook = Workbook(write_only=True)
        worksheet = workbook.create_sheet(title="分析数据")
        worksheet.append(base_columns + attr_columns)

        for offset in range(0, total, page_size):
            page_rows = q.offset(offset).limit(page_size).all()
            item_ids = [r.id for r in page_rows]
            spec_index: dict[int, dict[str, str]] = {}
            for i in range(0, len(item_ids), spec_batch_size):
                batch = item_ids[i: i + spec_batch_size]
                if not batch:
                    continue
                spec_rows = (
                    adb.query(PublishedItemSpec)
                    .filter(PublishedItemSpec.published_item_id.in_(batch))
                    .all()
                )
                for s in spec_rows:
                    spec_index.setdefault(s.published_item_id, {})[s.spec_name] = s.spec_value or ""

            for r in page_rows:
                base_values = [
                    r.month,
                    r.platform,
                    r.item_name,
                    r.brand_code,
                    r.brand_name,
                    r.model_code,
                    r.model_name,
                    r.shop_name,
                    float(r.ref_price) if r.ref_price is not None else None,
                    r.sales_qty,
                    float(r.calc_price) if r.calc_price is not None else None,
                    r.corrected_sales_qty,
                    float(r.corrected_sales_amount) if r.corrected_sales_amount is not None else None,
                    r.category_lv1,
                    r.category_lv2,
                    r.category_lv3,
                    r.item_url,
                ]
                attrs = spec_index.get(r.id, {})
                worksheet.append(base_values + [attrs.get(name, "") for name in sorted(all_attr_names)])

            progress = 35 + int(60 * min(offset + page_size, total) / max(total, 1))
            _wb_progress[job_id] = progress
            job.progress = progress
            db.commit()

        workbook.save(str(filepath))
        _wb_progress[job_id] = 95

        # 6. 写 done（95→100%）
        job.status = "done"
        job.progress = 100
        job.file_token = token
        job.filename = filename
        job.finished_at = datetime.utcnow()
        db.commit()
        _wb_progress[job_id] = 100

    except Exception as e:
        try:
            job = db.query(WorkbenchExportJob).filter_by(id=job_id).first()
            if job:
                job.status = "error"
                job.error_msg = str(e)
                job.finished_at = datetime.utcnow()
                db.commit()
        except Exception:
            pass
    finally:
        _wb_progress.pop(job_id, None)
        db.close()
        adb.close()


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
        "years": sorted({m // 100 for m in months}, reverse=True),
        "months": months,
        "platforms": _vals(PublishedItem.platform),
        "brands": _vals(PublishedItem.brand_code),
        "models": _vals(PublishedItem.model_code),
        "categories": _vals(PublishedItem.category_name),
    }


@router.get("/data")
def query_data(
    year: Optional[int] = Query(None),
    month: Optional[int] = Query(None),
    category_name: Optional[str] = Query(None),
    platform: Optional[str] = Query(None),
    brand_code: Optional[str] = Query(None),
    model_code: Optional[str] = Query(None),
    item_url: Optional[str] = Query(None),
    category_lv1: Optional[str] = Query(None),
    category_lv2: Optional[str] = Query(None),
    keyword: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_analytics_db),
):
    params = dict(
        year=year, month=month, category_name=category_name,
        platform=platform, brand_code=brand_code,
        model_code=model_code, item_url=item_url,
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

    match_index, alias_index = _load_workbench_context(rows)

    items = []
    for index, r in enumerate(rows, start=(page - 1) * page_size + 1):
        match_info = match_index.get(r.match_result_id)
        match_result = match_info[0] if match_info else None
        raw_data = match_info[1] if match_info else None
        items.append({
            "id": r.id,
            "sequence": index,
            "year": _year_from_month(r.month),
            "month": r.month,
            "platform": r.platform,
            "item_name": r.item_name,
            "item_image": r.item_image,
            "item_url": r.item_url,
            "brand_raw": raw_data.brand_raw if raw_data else None,
            "brand_code": r.brand_code,
            "brand_name": r.brand_name,
            "model_code": r.model_code,
            "model_name": r.model_name,
            "model_aliases": alias_index.get(r.model_code or "", []),
            "judgement_type": _match_source_label(match_result.match_source if match_result else None),
            "operator": "-",
            "operated_at": format_beijing_datetime(match_result.updated_at if match_result else r.published_at),
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
        })

    return {"total": total, "page": page, "page_size": page_size, "items": items}


@router.post("/export", status_code=202)
def export_data(payload: WorkbenchExportParams, db: Session = Depends(get_db)):
    """异步触发工作台导出，立即返回 job_id。"""
    params = {
        "year":          payload.year,
        "month":         payload.month,
        "category_name": payload.category_name,
        "platform":      payload.platform,
        "brand_code":    payload.brand_code,
        "model_code":    payload.model_code,
        "item_url":      payload.item_url,
        "keyword":       payload.keyword,
        "quarter":       payload.quarter,
    }
    params = {k: v for k, v in params.items() if v not in (None, "", [])}

    with reserve_async_export_capacity(db):
        job = WorkbenchExportJob(status="pending")
        db.add(job)
        db.commit()
        db.refresh(job)

    t = threading.Thread(
        target=_run_wb_export_thread,
        args=(job.id, params),
        daemon=True,
    )
    t.start()

    return {"job_id": job.id, "status": "pending"}


@router.get("/export/jobs/{job_id}")
def get_wb_export_job(job_id: int, db: Session = Depends(get_db)):
    """轮询工作台导出任务状态和进度。"""
    job = db.query(WorkbenchExportJob).filter_by(id=job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="导出任务不存在")

    progress = _wb_progress.get(job_id, job.progress)
    download_url = (
        f"/api/workbench/download/{job.file_token}"
        if job.status == "done" and job.file_token
        else None
    )
    return {
        "job_id":       job.id,
        "status":       job.status,
        "progress":     progress,
        "download_url": download_url,
        "error_msg":    job.error_msg,
    }


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
def download_export(token: str, db: Session = Depends(get_db)):
    """通过 token 下载导出文件。"""
    job = db.query(WorkbenchExportJob).filter_by(file_token=token).first()
    if not job or not job.filename:
        raise HTTPException(status_code=404, detail="文件不存在或已过期")

    file_path = _EXPORT_DIR / f"{token}_{job.filename}"
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="文件已被清理，请重新导出")

    return FileResponse(
        path=str(file_path),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(job.filename)}"},
    )
