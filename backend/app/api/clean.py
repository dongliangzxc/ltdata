from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.database import get_db
from app.models.schemas import (
    CleanJobRecord,
    CleanedDataRecord,
    CleanJobOut,
    CleanedDataOut,
    DispatchBatch,
    DispatchItem,
    UploadFileRecord,
)
from app.services.data_cleaner import run_clean

router = APIRouter(prefix="/api/clean", tags=["clean"])


def _format_beijing_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    return (value + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S")


def _build_clean_scope_desc(db: Session, job: CleanJobRecord) -> str:
    files = []
    if job.file_ids:
        files = db.query(UploadFileRecord).filter(UploadFileRecord.id.in_(job.file_ids)).all()
    platforms = sorted({f.platform for f in files if f.platform})
    months = sorted({f.month_range for f in files if f.month_range})

    parts = []
    if platforms:
        parts.append(f"平台：{'、'.join(platforms)}")
    if job.dispatch_category_code:
        parts.append(f"品类：{job.dispatch_category_code}")
    if months:
        parts.append(f"月份：{'、'.join(months)}")
    if parts:
        return " / ".join(parts)
    if job.file_ids:
        return "、".join(f"文件#{file_id}" for file_id in job.file_ids)
    return "-"


def _clean_job_to_dict(db: Session, job: CleanJobRecord) -> dict:
    return {
        "id": job.id,
        "file_ids": job.file_ids,
        "rules": job.rules,
        "status": job.status,
        "row_in": job.row_in,
        "row_out": job.row_out,
        "row_filtered": job.row_filtered,
        "dispatch_batch_id": job.dispatch_batch_id,
        "dispatch_category_code": job.dispatch_category_code,
        "created_at": _format_beijing_datetime(job.created_at),
        "scope_desc": _build_clean_scope_desc(db, job),
    }


def _run_clean_for_dispatch_category(
    db: Session,
    file_id: int,
    rules: dict,
    dispatch_batch_id: int,
    dispatch_category_code: str,
) -> CleanJobRecord:
    from app.models.schemas import RawDataRecord

    raw_data_ids = select(DispatchItem.raw_data_id).filter(
        DispatchItem.batch_id == dispatch_batch_id,
        DispatchItem.category_code == dispatch_category_code,
    )
    row_in = db.query(RawDataRecord).filter(RawDataRecord.id.in_(raw_data_ids)).count()
    job = CleanJobRecord(
        file_ids=[file_id],
        rules=rules,
        status="processing",
        row_in=row_in,
        row_out=0,
        dispatch_batch_id=dispatch_batch_id,
        dispatch_category_code=dispatch_category_code,
    )
    db.add(job)
    db.flush()

    try:
        row_out = run_clean(db, job.id, [file_id], rules, dispatch_batch_id, dispatch_category_code)
        job.row_out = row_out
        job.status = "done"
        db.commit()
        db.refresh(job)
    except Exception as e:
        job.status = "error"
        db.commit()
        raise HTTPException(status_code=500, detail=f"清洗失败: {str(e)}")

    return job


@router.post("/run", response_model=CleanJobOut)
def run_clean_job(payload: dict, db: Session = Depends(get_db)):
    """
    执行数据清洗任务。
    payload: {
      "file_ids": [1,2],
      "rules": { "dedup": true },
      "dispatch_batch_id": 1,          // 可选
      "dispatch_category_code": "SPK"  // 可选
    }
    """
    file_ids: list[int] = payload.get("file_ids", [])
    rules: dict = payload.get("rules", {"dedup": True})
    dispatch_batch_id: int | None = payload.get("dispatch_batch_id")
    dispatch_category_code: str | None = payload.get("dispatch_category_code")

    if not file_ids:
        raise HTTPException(status_code=400, detail="file_ids 不能为空")

    # 统计输入行数
    from app.models.schemas import RawDataRecord, DispatchItem
    if dispatch_batch_id and dispatch_category_code:
        raw_data_ids = (
            db.query(DispatchItem.raw_data_id)
            .filter(
                DispatchItem.batch_id == dispatch_batch_id,
                DispatchItem.category_code == dispatch_category_code,
            )
            .subquery()
        )
        row_in = db.query(RawDataRecord).filter(RawDataRecord.id.in_(raw_data_ids)).count()
    else:
        row_in = db.query(RawDataRecord).filter(RawDataRecord.file_id.in_(file_ids)).count()

    # 创建 job 记录
    job = CleanJobRecord(
        file_ids=file_ids,
        rules=rules,
        status="processing",
        row_in=row_in,
        row_out=0,
        dispatch_batch_id=dispatch_batch_id,
        dispatch_category_code=dispatch_category_code,
    )
    db.add(job)
    db.flush()

    try:
        row_out = run_clean(db, job.id, file_ids, rules, dispatch_batch_id, dispatch_category_code)
        job.row_out = row_out
        job.status = "done"
        db.commit()
        db.refresh(job)
    except Exception as e:
        job.status = "error"
        db.commit()
        raise HTTPException(status_code=500, detail=f"清洗失败: {str(e)}")

    return job


@router.post("/run-dispatch-batch")
def run_dispatch_batch_clean(payload: dict, db: Session = Depends(get_db)):
    dispatch_batch_id: int | None = payload.get("dispatch_batch_id")
    rules: dict = payload.get("rules", {"dedup": True})

    if not dispatch_batch_id:
        raise HTTPException(status_code=400, detail="dispatch_batch_id 不能为空")

    batch = db.query(DispatchBatch).filter(DispatchBatch.id == dispatch_batch_id).first()
    if not batch:
        raise HTTPException(status_code=404, detail="分发批次不存在")
    if batch.status != "done":
        raise HTTPException(status_code=400, detail="只能清洗已完成的分发批次")
    if not batch.file_id:
        raise HTTPException(status_code=400, detail="分发批次缺少文件信息")

    category_codes = [
        row[0]
        for row in db.query(DispatchItem.category_code)
        .filter(DispatchItem.batch_id == dispatch_batch_id)
        .distinct()
        .order_by(DispatchItem.category_code)
        .all()
    ]
    if not category_codes:
        raise HTTPException(status_code=400, detail="分发批次没有可清洗的类目")

    jobs = []
    for category_code in category_codes:
        job = _run_clean_for_dispatch_category(db, batch.file_id, rules, dispatch_batch_id, category_code)
        jobs.append(job)

    return {
        "dispatch_batch_id": dispatch_batch_id,
        "jobs": [CleanJobOut.model_validate(job) for job in jobs],
    }


@router.get("/jobs")
def list_clean_jobs(db: Session = Depends(get_db)):
    jobs = db.query(CleanJobRecord).order_by(CleanJobRecord.created_at.desc()).all()
    return [_clean_job_to_dict(db, job) for job in jobs]


@router.get("/jobs/{job_id}/preview")
def preview_clean_job(
    job_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    job = db.query(CleanJobRecord).filter(CleanJobRecord.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="清洗任务不存在")

    q = db.query(CleanedDataRecord).filter(CleanedDataRecord.clean_job_id == job_id)
    total = q.count()
    items = q.offset((page - 1) * page_size).limit(page_size).all()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [CleanedDataOut.model_validate(r) for r in items],
    }
