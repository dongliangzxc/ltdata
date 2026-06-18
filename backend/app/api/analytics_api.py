"""Phase 6 analytics dashboard API."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.analytics_db import get_analytics_db
from app.models.database import get_db
from app.models.schemas import WorkbenchExportJob
from app.services.analytics_service import (
    build_analytics_query,
    content_disposition,
    get_analytics_detail_rows,
    get_analytics_filters,
    get_analytics_summary,
    mark_export_job_done,
    mark_export_job_error,
    write_detail_export_file,
    write_summary_export_file,
)
from app.services.export_guards import (
    MAX_SYNC_EXPORT_ROWS,
    ensure_export_row_limit,
    reserve_async_export_capacity,
)

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


def _filter_kwargs(
    year: Optional[int] = None,
    month: Optional[int] = None,
    brand: Optional[str] = None,
    category: Optional[str] = None,
    platform: Optional[str] = None,
    model_keyword: Optional[str] = None,
    item_keyword: Optional[str] = None,
) -> dict:
    return {
        "year": year,
        "month": month,
        "brand": brand,
        "category": category,
        "platform": platform,
        "model_keyword": model_keyword,
        "item_keyword": item_keyword,
    }


@router.get("/filters")
def filters(db: Session = Depends(get_analytics_db)):
    """Return available analytics filter dimensions."""
    return get_analytics_filters(db)


@router.get("/summary")
def summary(
    year: Optional[int] = Query(None),
    month: Optional[int] = Query(None, ge=1, le=12),
    brand: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    platform: Optional[str] = Query(None),
    model_keyword: Optional[str] = Query(None),
    item_keyword: Optional[str] = Query(None),
    group_by: str = Query("model"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    sort_by: str = Query("corrected_sales_qty_desc"),
    db: Session = Depends(get_analytics_db),
):
    """Return grouped analytics summary metrics."""
    return get_analytics_summary(
        db,
        **_filter_kwargs(year, month, brand, category, platform, model_keyword, item_keyword),
        group_by=group_by,
        page=page,
        page_size=page_size,
        sort_by=sort_by,
    )


@router.get("/export/summary")
def export_summary(
    year: Optional[int] = Query(None),
    month: Optional[int] = Query(None, ge=1, le=12),
    brand: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    platform: Optional[str] = Query(None),
    model_keyword: Optional[str] = Query(None),
    item_keyword: Optional[str] = Query(None),
    group_by: str = Query("model"),
    sort_by: str = Query("corrected_sales_qty_desc"),
    luotu_db: Session = Depends(get_db),
    analytics_db: Session = Depends(get_analytics_db),
):
    """Export current summary rows to Excel."""
    source_total = build_analytics_query(
        analytics_db,
        **_filter_kwargs(year, month, brand, category, platform, model_keyword, item_keyword),
    ).count()
    ensure_export_row_limit(source_total, max_rows=MAX_SYNC_EXPORT_ROWS, label="看板汇总导出")

    with reserve_async_export_capacity(luotu_db):
        job = WorkbenchExportJob(status="running", progress=10)
        luotu_db.add(job)
        luotu_db.commit()
        luotu_db.refresh(job)

    try:
        data = get_analytics_summary(
            analytics_db,
            **_filter_kwargs(year, month, brand, category, platform, model_keyword, item_keyword),
            group_by=group_by,
            paginate=False,
            sort_by=sort_by,
        )
        token, filename, _ = write_summary_export_file(data["rows"])
        mark_export_job_done(luotu_db, job, token, filename)
        return {
            "job_id": job.id,
            "status": "done",
            "download_url": f"/api/analytics/download/{token}",
        }
    except Exception as exc:
        mark_export_job_error(luotu_db, job, exc)
        raise


@router.get("/export/detail")
def export_detail(
    year: Optional[int] = Query(None),
    month: Optional[int] = Query(None, ge=1, le=12),
    brand: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    platform: Optional[str] = Query(None),
    model_keyword: Optional[str] = Query(None),
    item_keyword: Optional[str] = Query(None),
    fields: Optional[str] = Query(None),
    luotu_db: Session = Depends(get_db),
    analytics_db: Session = Depends(get_analytics_db),
):
    """Export current detail rows to Excel."""
    source_total = build_analytics_query(
        analytics_db,
        **_filter_kwargs(year, month, brand, category, platform, model_keyword, item_keyword),
    ).count()
    ensure_export_row_limit(source_total, max_rows=MAX_SYNC_EXPORT_ROWS, label="看板明细导出")

    with reserve_async_export_capacity(luotu_db):
        job = WorkbenchExportJob(status="running", progress=10)
        luotu_db.add(job)
        luotu_db.commit()
        luotu_db.refresh(job)

    try:
        rows = get_analytics_detail_rows(
            analytics_db,
            **_filter_kwargs(year, month, brand, category, platform, model_keyword, item_keyword),
        )
        token, filename, _ = write_detail_export_file(rows, fields)
        mark_export_job_done(luotu_db, job, token, filename)
        return {
            "job_id": job.id,
            "status": "done",
            "download_url": f"/api/analytics/download/{token}",
        }
    except Exception as exc:
        mark_export_job_error(luotu_db, job, exc)
        raise


@router.get("/download/{token}")
def download(token: str, db: Session = Depends(get_db)):
    """Download an analytics export file by token."""
    job = db.query(WorkbenchExportJob).filter_by(file_token=token).first()
    if not job or not job.filename:
        raise HTTPException(status_code=404, detail="文件不存在或已过期")

    from pathlib import Path

    file_path = Path(settings.EXPORT_DIR) / f"{token}_{job.filename}"
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="文件已被清理，请重新导出")

    return FileResponse(
        path=str(file_path),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": content_disposition(job.filename)},
    )
