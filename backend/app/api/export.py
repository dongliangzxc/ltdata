"""
导出 API
- POST /api/export        触发异步导出，立即返回 job_id
- GET  /api/export/jobs   列出历史导出任务
- GET  /api/export/download/{token}  下载文件
"""
import os
import threading
from pathlib import Path
from urllib.parse import quote
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from app.models.database import get_db, SessionLocal
from app.models.schemas import CleanJobRecord, ExportJob, ExportJobOut
from app.services.exporter import export_match_job
from app.services.export_guards import reserve_async_export_capacity

router = APIRouter(prefix="/api/export", tags=["export"])


def _run_export_thread(export_job_id: int, clean_job_id: int, filename_prefix: str):
    db = SessionLocal()
    try:
        job = db.query(ExportJob).filter(ExportJob.id == export_job_id).first()
        if not job:
            return
        job.status = "running"
        db.commit()

        files = export_match_job(db, clean_job_id, filename_prefix)

        if not files:
            job.status = "error"
            job.error_msg = "无可导出数据，请先执行型号匹配"
        else:
            f = files[0]
            job.status       = "done"
            job.filename     = f["filename"]
            job.token        = f["token"]
            job.rows         = f["rows"]
            job.pending_rows = f["pending_rows"]
        db.commit()
    except Exception as e:
        try:
            job = db.query(ExportJob).filter(ExportJob.id == export_job_id).first()
            if job:
                job.status    = "error"
                job.error_msg = str(e)
                db.commit()
        except Exception:
            pass
    finally:
        db.close()


@router.post("")
def trigger_export(payload: dict, db: Session = Depends(get_db)):
    """
    异步触发导出，立即返回 job_id。
    payload: {"clean_job_id": 1, "filename_prefix": "已处理数据"}
    """
    clean_job_id: int = payload.get("clean_job_id")
    filename_prefix: str = payload.get("filename_prefix", "已处理数据")

    if not clean_job_id:
        raise HTTPException(status_code=400, detail="clean_job_id 不能为空")

    job_record = db.query(CleanJobRecord).filter(CleanJobRecord.id == clean_job_id).first()
    if not job_record:
        raise HTTPException(status_code=404, detail="清洗任务不存在")

    with reserve_async_export_capacity(db):
        export_job = ExportJob(
            clean_job_id=clean_job_id,
            filename_prefix=filename_prefix,
            status="pending",
        )
        db.add(export_job)
        db.commit()
        db.refresh(export_job)

    t = threading.Thread(
        target=_run_export_thread,
        args=(export_job.id, clean_job_id, filename_prefix),
        daemon=True,
    )
    t.start()

    return {"job_id": export_job.id, "status": "pending"}


@router.get("/jobs")
def list_export_jobs(
    clean_job_id: int | None = None,
    db: Session = Depends(get_db),
):
    """列出导出任务历史，可按 clean_job_id 过滤"""
    q = db.query(ExportJob)
    if clean_job_id is not None:
        q = q.filter(ExportJob.clean_job_id == clean_job_id)
    jobs = q.order_by(ExportJob.id.desc()).limit(50).all()
    return {"data": [ExportJobOut.model_validate(j) for j in jobs]}


@router.get("/jobs/{job_id}")
def get_export_job(job_id: int, db: Session = Depends(get_db)):
    """查单个导出任务状态"""
    job = db.query(ExportJob).filter(ExportJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="导出任务不存在")
    return ExportJobOut.model_validate(job)


@router.get("/download/{token}")
def download_file(token: str, db: Session = Depends(get_db)):
    """通过 token 下载导出文件"""
    job = db.query(ExportJob).filter(ExportJob.token == token).first()
    if not job or not job.token:
        raise HTTPException(status_code=404, detail="文件不存在或已过期")

    from app.core.config import settings
    from pathlib import Path as _Path
    export_dir = _Path(settings.EXPORT_DIR)
    file_path = export_dir / f"{token}_{job.filename}"

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="文件已被清理，请重新导出")

    return FileResponse(
        path=str(file_path),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(job.filename)}"},
    )
