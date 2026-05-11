from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.models.database import get_db
from app.models.schemas import CleanJobRecord, CleanedDataRecord, CleanJobOut, CleanedDataOut
from app.services.data_cleaner import run_clean

router = APIRouter(prefix="/api/clean", tags=["clean"])


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


@router.get("/jobs", response_model=list[CleanJobOut])
def list_clean_jobs(db: Session = Depends(get_db)):
    return db.query(CleanJobRecord).order_by(CleanJobRecord.created_at.desc()).all()


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
