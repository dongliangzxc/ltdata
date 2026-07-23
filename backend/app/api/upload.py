import os
import shutil
import uuid
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import func, or_, select, tuple_, text
from sqlalchemy.orm import Session
from app.models.database import get_db
from app.models.schemas import (
    CleanJobItemRecord,
    CleanedDataRecord,
    FilteredItem,
    UploadFileRecord,
    UploadDownloadJob,
    RawDataRecord,
    UploadFileOut,
    UploadDownloadJobOut,
    RawDataOut,
    ColumnTemplate,
)
from app.services.excel_parser import parse_raw_excel, parse_with_mapping
from app.core.config import settings
from app.services.import_helper import (
    col_fingerprint as _ih_col_fingerprint,
    read_columns as _ih_read_columns,
    find_best_template as _ih_find_best_template,
    cleanup_old_tmp as _ih_cleanup_old_tmp,
)
import threading
from datetime import datetime
from app.models.database import SessionLocal
from app.models.schemas import UploadConfirmJob
from app.utils.time_utils import format_beijing_datetime

# 内存进度表：job_id → 0-100，线程结束后清除
_upload_progress: dict[int, int] = {}


def _update_upload_job_progress(
    db: Session,
    job: UploadConfirmJob,
    *,
    status=None,
    stage=None,
    stage_label=None,
    progress=None,
    total_rows=None,
    processed_rows=None,
    inserted_rows=None,
    skipped_rows=None,
    error_msg=None,
    finished_at=None,
) -> None:
    """Persist upload job progress fields in an isolated transaction."""
    del db  # keep the public signature, but never commit the caller's import session
    progress_db = SessionLocal()
    try:
        progress_job = progress_db.query(UploadConfirmJob).filter_by(id=job.id).first()
        if not progress_job:
            return
        if status is not None:
            progress_job.status = status
        if stage is not None:
            progress_job.stage = stage
        if stage_label is not None:
            progress_job.stage_label = stage_label
        if progress is not None:
            progress_job.progress = max(0, min(100, progress))
        if total_rows is not None:
            progress_job.total_rows = total_rows
        if processed_rows is not None:
            progress_job.processed_rows = processed_rows
        if inserted_rows is not None:
            progress_job.inserted_rows = inserted_rows
        if skipped_rows is not None:
            progress_job.skipped_rows = skipped_rows
        if error_msg is not None:
            progress_job.error_msg = error_msg
        if finished_at is not None:
            progress_job.finished_at = finished_at
        progress_db.commit()
        _upload_progress[job.id] = progress_job.progress
    finally:
        progress_db.close()


def _get_upload_job_progress_state(job_id: int) -> dict:
    """Read current upload job progress fields from an isolated session."""
    progress_db = SessionLocal()
    try:
        progress_job = progress_db.query(UploadConfirmJob).filter_by(id=job_id).first()
        if not progress_job:
            return {}
        return {
            "stage": progress_job.stage,
            "stage_label": progress_job.stage_label,
            "progress": progress_job.progress,
        }
    finally:
        progress_db.close()


def _is_upload_job_cancelled(job_id: int) -> bool:
    progress_db = SessionLocal()
    try:
        progress_job = progress_db.query(UploadConfirmJob).filter_by(id=job_id).first()
        return bool(progress_job and progress_job.status == "cancelled")
    finally:
        progress_db.close()


def _mark_interrupted_upload_jobs(db: Session) -> None:
    jobs = db.query(UploadConfirmJob).filter(
        UploadConfirmJob.status == "running",
        UploadConfirmJob.id.notin_(list(_upload_progress.keys()) or [-1]),
    ).all()
    if not jobs:
        return
    for job in jobs:
        job.status = "error"
        job.stage = "interrupted"
        job.stage_label = "任务已中断"
        job.error_msg = "后端服务重启，后台处理线程已中断，请重新上传"
        job.finished_at = datetime.utcnow()
    db.commit()


DOMESTIC_UPLOAD_PLATFORMS = {
    "jd", "tm", "tb", "tmall", "taobao", "douyin",
    "京东", "天猫", "淘宝", "抖音",
}


router = APIRouter(prefix="/api/upload", tags=["upload"])


def _upload_download_job_out(job: UploadDownloadJob) -> dict:
    download_url = None
    if job.status == "done" and job.download_token:
        download_url = f"/api/upload/download-jobs/{job.id}/download"
    return {
        "job_id": job.id,
        "file_id": job.file_id,
        "status": job.status,
        "progress": job.progress,
        "filename": job.filename,
        "download_url": download_url,
        "error_msg": job.error_msg,
        "created_at": format_beijing_datetime(job.created_at) if job.created_at else None,
        "finished_at": format_beijing_datetime(job.finished_at) if job.finished_at else None,
    }


def _run_upload_download_job(job_id: int) -> None:
    db = SessionLocal()
    try:
        job = db.query(UploadDownloadJob).filter(UploadDownloadJob.id == job_id).first()
        if not job:
            return
        job.status = "running"
        job.progress = 10
        db.commit()

        record = db.query(UploadFileRecord).filter(UploadFileRecord.id == job.file_id).first()
        if record is None:
            job.status = "error"
            job.progress = 100
            job.error_msg = "上传记录不存在"
            job.finished_at = datetime.utcnow()
            db.commit()
            return

        safe_filename = Path(record.filename).name
        file_path = Path(settings.UPLOAD_DIR) / safe_filename
        if not file_path.exists() or not file_path.is_file():
            job.status = "error"
            job.progress = 100
            job.error_msg = "原始上传文件不存在，无法下载"
            job.finished_at = datetime.utcnow()
            db.commit()
            return

        job.progress = 80
        db.commit()
        job.filename = record.filename
        job.download_token = uuid.uuid4().hex
        job.status = "done"
        job.progress = 100
        job.error_msg = None
        job.finished_at = datetime.utcnow()
        db.commit()
    finally:
        db.close()


@router.post("", response_model=dict)
async def upload_file(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """上传原始数据 Excel 文件，解析后写入数据库（相同 item_id+month+platform 自动去重）"""
    if not file.filename.endswith((".xlsx", ".xls", ".csv")):
        raise HTTPException(status_code=400, detail="只支持 .xlsx / .xls / .csv 格式文件")

    # 保存文件
    safe_filename = Path(file.filename).name  # strips any directory components
    save_path = Path(settings.UPLOAD_DIR) / safe_filename
    with open(save_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    try:
        records, platform, month_range = parse_raw_excel(save_path)
    except Exception as e:
        os.remove(save_path)
        raise HTTPException(status_code=422, detail=f"文件解析失败: {str(e)}")

    # 去重：查出已存在的 (item_id, month, platform) 组合
    keys = {
        (str(r.get("item_id")), r.get("month"), r.get("platform"))
        for r in records
        if r.get("item_id") is not None
    }
    if keys:
        existing_rows = db.query(
            RawDataRecord.item_id, RawDataRecord.month, RawDataRecord.platform
        ).filter(
            tuple_(RawDataRecord.item_id, RawDataRecord.month, RawDataRecord.platform).in_(keys)
        ).all()
        existing_set = {(e.item_id, e.month, e.platform) for e in existing_rows}
        to_insert = [
            r for r in records
            if (str(r.get("item_id")), r.get("month"), r.get("platform")) not in existing_set
        ]
    else:
        to_insert = records

    skipped = len(records) - len(to_insert)

    # 写入 upload_files 表
    file_record = UploadFileRecord(
        filename=file.filename,
        platform=platform,
        month_range=month_range,
        row_count=len(to_insert),
        status="done",
    )
    db.add(file_record)
    db.flush()  # 获取 id

    # 批量写入 raw_data
    batch = []
    for r in to_insert:
        batch.append(RawDataRecord(
            file_id=file_record.id,
            platform=r.get("platform"),
            month=r.get("month"),
            category_lv0=r.get("category_lv0"),
            category_lv1=r.get("category_lv1"),
            category_lv2=r.get("category_lv2"),
            category_lv3=r.get("category_lv3"),
            category_lv4=r.get("category_lv4"),
            category_lv5=r.get("category_lv5"),
            item_id=str(r.get("item_id")) if r.get("item_id") else None,
            item_name=r.get("item_name"),
            item_image=r.get("item_image"),
            item_url=r.get("item_url"),
            ref_price=r.get("ref_price"),
            brand_raw=r.get("brand_raw"),
            shop_name=r.get("shop_name"),
            sales_qty=r.get("sales_qty"),
            sales_amount=r.get("sales_amount"),
            price=r.get("price"),
            brand_std=r.get("brand_std"),
            model_std=r.get("model_std"),
        ))
    db.bulk_save_objects(batch)
    db.commit()
    db.refresh(file_record)

    # 返回预览（前50行，取原始解析数据）
    preview = records[:50]
    return {
        "file_id": file_record.id,
        "filename": file.filename,
        "platform": platform,
        "month_range": month_range,
        "row_count": len(records),
        "inserted": len(to_insert),
        "skipped": skipped,
        "preview": preview,
    }



@router.get("/files", response_model=list[UploadFileOut])
def list_upload_files(
    data_region: Optional[str] = Query(None),
    data_year: Optional[int] = Query(None),
    data_month: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    """获取上传历史列表，支持按维度过滤"""
    q = db.query(UploadFileRecord).order_by(UploadFileRecord.uploaded_at.desc())
    if data_region == "domestic":
        q = q.filter(
            or_(
                UploadFileRecord.data_region == data_region,
                UploadFileRecord.data_region.is_(None)
                & func.lower(UploadFileRecord.platform).in_(DOMESTIC_UPLOAD_PLATFORMS),
            )
        )
    elif data_region is not None:
        q = q.filter(UploadFileRecord.data_region == data_region)
    if data_year is not None:
        q = q.filter(UploadFileRecord.data_year == data_year)
    if data_month is not None:
        q = q.filter(UploadFileRecord.data_month == data_month)
    return [
        {
            "id": record.id,
            "filename": record.filename,
            "platform": record.platform,
            "month_range": record.month_range,
            "row_count": record.row_count,
            "status": record.status,
            "template_id": record.template_id,
            "data_region": record.data_region,
            "data_year": record.data_year,
            "data_month": record.data_month,
            "uploaded_at": format_beijing_datetime(record.uploaded_at),
        }
        for record in q.all()
    ]


@router.get("/files/{file_id}/download")
def download_upload_file(file_id: int, db: Session = Depends(get_db)):
    """下载上传历史中的原始上传文件"""
    record = db.query(UploadFileRecord).filter(UploadFileRecord.id == file_id).first()
    if record is None:
        raise HTTPException(status_code=404, detail="上传记录不存在")

    safe_filename = Path(record.filename).name
    file_path = Path(settings.UPLOAD_DIR) / safe_filename
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="原始上传文件不存在，无法下载")

    return FileResponse(file_path, filename=record.filename)


@router.post("/files/{file_id}/download-jobs", response_model=UploadDownloadJobOut)
def create_upload_download_job(file_id: int, db: Session = Depends(get_db)):
    """创建上传历史原始文件后台下载准备任务"""
    record = db.query(UploadFileRecord).filter(UploadFileRecord.id == file_id).first()
    if record is None:
        raise HTTPException(status_code=404, detail="上传记录不存在")

    job = UploadDownloadJob(
        file_id=record.id,
        status="pending",
        progress=0,
        filename=record.filename,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    thread = threading.Thread(target=_run_upload_download_job, args=(job.id,), daemon=True)
    thread.start()
    return _upload_download_job_out(job)


@router.get("/download-jobs", response_model=list[UploadDownloadJobOut])
def list_upload_download_jobs(
    file_ids: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """列出上传历史原始文件下载准备任务"""
    q = db.query(UploadDownloadJob).order_by(UploadDownloadJob.created_at.desc(), UploadDownloadJob.id.desc())
    if file_ids:
        ids = [int(value) for value in file_ids.split(",") if value.strip().isdigit()]
        if ids:
            q = q.filter(UploadDownloadJob.file_id.in_(ids))
    return [_upload_download_job_out(job) for job in q.limit(limit).all()]


@router.get("/download-jobs/{job_id}", response_model=UploadDownloadJobOut)
def get_upload_download_job(job_id: int, db: Session = Depends(get_db)):
    """获取单个上传历史下载准备任务状态"""
    job = db.query(UploadDownloadJob).filter(UploadDownloadJob.id == job_id).first()
    if job is None:
        raise HTTPException(status_code=404, detail="下载任务不存在")
    return _upload_download_job_out(job)


@router.get("/download-jobs/{job_id}/download")
def download_upload_download_job_file(job_id: int, db: Session = Depends(get_db)):
    """下载已准备完成的上传历史原始文件"""
    job = db.query(UploadDownloadJob).filter(UploadDownloadJob.id == job_id).first()
    if job is None:
        raise HTTPException(status_code=404, detail="下载任务不存在")
    if job.status != "done" or not job.download_token:
        raise HTTPException(status_code=409, detail="下载任务尚未完成")

    safe_filename = Path(job.filename).name
    file_path = Path(settings.UPLOAD_DIR) / safe_filename
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="原始上传文件不存在，无法下载")
    return FileResponse(file_path, filename=job.filename)


@router.delete("/files/{file_id}")
def delete_upload_file(file_id: int, db: Session = Depends(get_db)):
    """删除上传文件记录及其原始数据；已有下游清洗任务时拒绝删除。"""
    record = db.query(UploadFileRecord).filter(UploadFileRecord.id == file_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="文件记录不存在")

    raw_data_ids = select(RawDataRecord.id).filter(RawDataRecord.file_id == file_id)
    has_downstream_refs = (
        db.query(CleanJobItemRecord.id).filter(CleanJobItemRecord.raw_data_id.in_(raw_data_ids)).first()
        or db.query(CleanedDataRecord.id).filter(CleanedDataRecord.raw_data_id.in_(raw_data_ids)).first()
        or db.query(FilteredItem.id).filter(FilteredItem.raw_data_id.in_(raw_data_ids)).first()
    )
    if has_downstream_refs:
        raise HTTPException(
            status_code=400,
            detail="该文件的数据已进入分发/清洗任务，不能直接删除。请先处理或保留相关清洗任务记录。",
        )

    # Batch-delete raw_data in one SQL — avoids 7000+ ORM cascade operations
    db.execute(text("DELETE FROM raw_data WHERE file_id = :fid"), {"fid": file_id})

    # Null out dispatch_batches.file_id to release FK before deleting the file record
    db.execute(text("UPDATE dispatch_batches SET file_id = NULL WHERE file_id = :fid"), {"fid": file_id})

    # Delete file record
    db.delete(record)
    db.commit()

    return {"message": "已删除"}


# ─── P9: Two-phase upload ────────────────────────────────────

REQUIRED_FIELDS = {"item_id", "month", "platform", "item_name", "sales_qty", "sales_amount", "price"}


def _run_upload_confirm_thread(
    job_id: int,
    tmp_path: str,
    original_filename: str,
    mapping: dict,
    ignore_columns: list,
    save_template_name,
    template_id_use,
    data_region: str | None = None,
    data_year: int | None = None,
    data_month: int | None = None,
):
    """后台线程：解析 Excel、去重、写库，更新 job 状态。"""
    db = SessionLocal()
    job = None
    try:
        job = db.query(UploadConfirmJob).filter_by(id=job_id).first()
        if not job:
            return
        _update_upload_job_progress(
            db,
            job,
            status="running",
            stage="reading",
            stage_label="正在读取文件",
            progress=5,
        )

        if _is_upload_job_cancelled(job_id):
            return

        # 1. 解析 Excel（5→40%）
        try:
            records, platform, month_range = parse_with_mapping(
                tmp_path, mapping, ignore_columns
            )
        except Exception as e:
            state = _get_upload_job_progress_state(job_id)
            _update_upload_job_progress(
                db,
                job,
                status="error",
                stage="error",
                stage_label="文件解析失败",
                progress=state.get("progress") or 0,
                error_msg=f"文件解析失败: {e}",
                finished_at=datetime.utcnow(),
            )
            return
        _update_upload_job_progress(
            db,
            job,
            stage="reading",
            stage_label="文件读取完成",
            progress=40,
            total_rows=len(records),
            processed_rows=len(records),
        )

        # 2. 可选保存模板（40→50%）
        saved_template_id = template_id_use
        if save_template_name:
            from sqlalchemy.exc import IntegrityError
            fp = _col_fingerprint(list(mapping.keys()))
            existing = db.query(ColumnTemplate).filter(
                ColumnTemplate.col_fingerprint == fp,
                ColumnTemplate.is_builtin == 0,
            ).first()
            if not existing:
                existing = db.query(ColumnTemplate).filter(
                    ColumnTemplate.name == save_template_name,
                    ColumnTemplate.is_builtin == 0,
                ).first()
            if existing:
                existing.name = save_template_name
                existing.mapping = mapping
                existing.ignore_columns = ignore_columns
                existing.col_fingerprint = fp
                db.flush()
                saved_template_id = existing.id
            else:
                tmpl = ColumnTemplate(
                    name=save_template_name,
                    col_fingerprint=fp,
                    mapping=mapping,
                    ignore_columns=ignore_columns,
                    is_builtin=0,
                )
                db.add(tmpl)
                nested = db.begin_nested()
                try:
                    db.flush()
                    nested.commit()
                    saved_template_id = tmpl.id
                except IntegrityError:
                    nested.rollback()
                    db.expunge(tmpl)
        # 3. 去重（50→60%）
        if _is_upload_job_cancelled(job_id):
            return
        _update_upload_job_progress(
            db,
            job,
            stage="deduping",
            stage_label="正在去重检查",
            progress=45,
            processed_rows=0,
        )
        keys = [
            (str(r.get("item_id")), r.get("month"), r.get("platform"))
            for r in records
            if r.get("item_id") is not None
        ]
        existing_set: set = set()
        if keys:
            DEDUP_BATCH = 5000
            for i in range(0, len(keys), DEDUP_BATCH):
                if _is_upload_job_cancelled(job_id):
                    return
                chunk = keys[i: i + DEDUP_BATCH]
                rows = db.query(
                    RawDataRecord.item_id, RawDataRecord.month, RawDataRecord.platform
                ).filter(
                    tuple_(RawDataRecord.item_id, RawDataRecord.month, RawDataRecord.platform).in_(chunk)
                ).all()
                existing_set.update((e.item_id, e.month, e.platform) for e in rows)
                processed = min(i + DEDUP_BATCH, len(keys))
                _update_upload_job_progress(
                    db,
                    job,
                    stage="deduping",
                    stage_label="正在去重检查",
                    progress=45 + int(15 * processed / max(len(keys), 1)),
                    processed_rows=processed,
                )
        to_insert = [
            r for r in records
            if (str(r.get("item_id")), r.get("month"), r.get("platform")) not in existing_set
        ]
        skipped = len(records) - len(to_insert)
        _update_upload_job_progress(
            db,
            job,
            stage="deduping",
            stage_label="去重完成",
            progress=60,
            processed_rows=len(records),
            inserted_rows=0,
            skipped_rows=skipped,
        )

        if _is_upload_job_cancelled(job_id):
            return

        # 4. 写 upload_files 记录（60→65%）
        file_record = UploadFileRecord(
            filename=original_filename,
            platform=platform,
            month_range=month_range,
            row_count=len(records),
            status="done",
            template_id=saved_template_id,
            data_region=data_region,
            data_year=data_year,
            data_month=data_month,
        )
        db.add(file_record)
        db.flush()
        _update_upload_job_progress(
            db,
            job,
            stage="inserting",
            stage_label="正在写入数据",
            progress=65,
            processed_rows=0,
            inserted_rows=0,
        )

        # 5. 批量写入 raw_data（65→90%）
        if to_insert:
            batch_size = 5000
            for i in range(0, len(to_insert), batch_size):
                if _is_upload_job_cancelled(job_id):
                    db.rollback()
                    return
                chunk = to_insert[i: i + batch_size]
                db.execute(
                    RawDataRecord.__table__.insert(),
                    [
                        {
                            "file_id":      file_record.id,
                            "platform":     r.get("platform"),
                            "month":        r.get("month"),
                            "category_lv0": r.get("category_lv0"),
                            "category_lv1": r.get("category_lv1"),
                            "category_lv2": r.get("category_lv2"),
                            "category_lv3": r.get("category_lv3"),
                            "category_lv4": r.get("category_lv4"),
                            "category_lv5": r.get("category_lv5"),
                            "item_id":      str(r.get("item_id")) if r.get("item_id") else None,
                            "item_name":    r.get("item_name"),
                            "item_image":   r.get("item_image"),
                            "item_url":     r.get("item_url"),
                            "ref_price":    r.get("ref_price"),
                            "brand_raw":    r.get("brand_raw"),
                            "shop_name":    r.get("shop_name"),
                            "sales_qty":    r.get("sales_qty"),
                            "sales_amount": r.get("sales_amount"),
                            "price":        r.get("price"),
                            "brand_std":    r.get("brand_std"),
                            "model_std":    r.get("model_std"),
                            "extra_data":   r.get("extra_data"),
                        }
                        for r in chunk
                    ],
                )
                inserted = min(i + batch_size, len(to_insert))
                _update_upload_job_progress(
                    db,
                    job,
                    stage="inserting",
                    stage_label="正在写入数据",
                    progress=65 + int(25 * inserted / max(len(to_insert), 1)),
                    processed_rows=inserted,
                    inserted_rows=inserted,
                    skipped_rows=skipped,
                )
        db.commit()
        db.refresh(file_record)
        _update_upload_job_progress(
            db,
            job,
            stage="finalizing",
            stage_label="正在收尾",
            progress=90,
            processed_rows=len(records),
            inserted_rows=len(to_insert),
            skipped_rows=skipped,
        )

        # 6. 移动临时文件（90→95%）
        final_path = Path(settings.UPLOAD_DIR) / original_filename
        shutil.move(str(tmp_path), str(final_path))
        _update_upload_job_progress(
            db,
            job,
            stage="finalizing",
            stage_label="正在生成结果",
            progress=95,
        )

        # 7. 写 done（95→100%）
        result = {
            "file_id":     file_record.id,
            "filename":    original_filename,
            "platform":    platform,
            "month_range": month_range,
            "row_count":   len(records),
            "total_rows":  len(records),
            "inserted":    len(to_insert),
            "skipped":     skipped,
            "preview":     records[:50],
        }
        job.file_id = file_record.id
        job.status = "done"
        job.stage = "done"
        job.stage_label = "处理完成"
        job.progress = 100
        job.total_rows = len(records)
        job.processed_rows = len(records)
        job.inserted_rows = len(to_insert)
        job.skipped_rows = skipped
        job.result_data = result
        job.finished_at = datetime.utcnow()
        db.commit()
        _upload_progress[job_id] = 100

    except Exception as e:
        try:
            db.rollback()
            job = db.query(UploadConfirmJob).filter_by(id=job_id).first()
            if job:
                state = _get_upload_job_progress_state(job_id)
                current_stage = state.get("stage_label") or state.get("stage")
                _update_upload_job_progress(
                    db,
                    job,
                    status="error",
                    stage="error",
                    stage_label="处理失败",
                    progress=state.get("progress") or 0,
                    error_msg=f"{current_stage}: {e}",
                    finished_at=datetime.utcnow(),
                )
        except Exception:
            pass
    finally:
        _upload_progress.pop(job_id, None)
        db.close()


def _col_fingerprint(columns: list) -> str:
    return _ih_col_fingerprint(columns)



def _find_best_template(columns: list, db: Session):
    """Return (best_template, match_score 0-100). Tries exact fingerprint first, then Jaccard."""
    return _ih_find_best_template(columns, "sales", db)


def _cleanup_old_tmp(tmp_dir: Path, max_age_hours: int = 24) -> None:
    """Remove temp files older than max_age_hours hours."""
    _ih_cleanup_old_tmp(tmp_dir, max_age_hours)


def _read_columns(file_path) -> list:
    return _ih_read_columns(Path(file_path))


@router.post("/headers")
async def upload_headers(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Phase 1: Save temp file, return column names + suggested template."""
    if not file.filename.endswith((".xlsx", ".xls", ".csv")):
        raise HTTPException(status_code=400, detail="只支持 .xlsx / .xls / .csv 格式文件")

    tmp_dir = Path(settings.UPLOAD_DIR) / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    _cleanup_old_tmp(tmp_dir)  # best-effort cleanup of stale temp files

    temp_file_id = str(uuid.uuid4())
    safe_filename = Path(file.filename).name  # strips any directory components
    save_path = tmp_dir / f"{temp_file_id}_{safe_filename}"
    with open(save_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    try:
        columns = _read_columns(save_path)
    except Exception as e:
        os.remove(save_path)
        raise HTTPException(status_code=422, detail=f"无法读取文件表头：{e}")

    best_tmpl, score = _find_best_template(columns, db)

    suggested = None
    if best_tmpl:
        suggested = {
            "id": best_tmpl.id,
            "name": best_tmpl.name,
            "platform": best_tmpl.platform,
            "mapping": best_tmpl.mapping,
            "ignore_columns": best_tmpl.ignore_columns or [],
        }

    return {
        "temp_file_id": temp_file_id,
        "filename": file.filename,
        "columns": columns,
        "suggested_template": suggested,
        "match_score": score,
    }


@router.post("/confirm", status_code=202)
async def upload_confirm(payload: dict, db: Session = Depends(get_db)):
    """Phase 2: 异步处理——立即返回 job_id，后台线程解析+写库。"""
    temp_file_id: str = payload.get("temp_file_id", "")
    mapping: dict = payload.get("mapping", {})
    ignore_columns: list = payload.get("ignore_columns", [])
    save_template_name = payload.get("save_template_name")
    template_id_use = payload.get("template_id")
    data_region: str | None = payload.get("data_region")
    data_year_raw = payload.get("data_year")
    data_year: int | None = int(data_year_raw) if data_year_raw is not None else None
    data_month_raw = payload.get("data_month")
    data_month: int | None = int(data_month_raw) if data_month_raw is not None else None

    if not temp_file_id:
        raise HTTPException(status_code=400, detail="temp_file_id 不能为空")

    # 找临时文件（同步检查，快）
    tmp_dir = Path(settings.UPLOAD_DIR) / "tmp"
    matches = list(tmp_dir.glob(f"{temp_file_id}_*"))
    if not matches:
        raise HTTPException(status_code=404, detail="临时文件不存在或已过期，请重新上传")
    tmp_path = matches[0]
    original_filename = tmp_path.name[len(temp_file_id) + 1:]

    # 校验必填字段映射（同步校验，快）
    mapped_targets = {v for v in mapping.values() if v != "__ext__"}
    missing = REQUIRED_FIELDS - mapped_targets
    if missing:
        raise HTTPException(
            status_code=422,
            detail=f"以下必填字段未映射：{', '.join(sorted(missing))}"
        )

    # 创建 job 记录
    job = UploadConfirmJob(
        status="pending",
        stage="pending",
        stage_label="等待处理",
        progress=0,
        filename=original_filename,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    t = threading.Thread(
        target=_run_upload_confirm_thread,
        args=(
            job.id,
            str(tmp_path),
            original_filename,
            mapping,
            ignore_columns,
            save_template_name,
            template_id_use,
            data_region,
            data_year,
            data_month,
        ),
        daemon=True,
    )
    t.start()

    return {"job_id": job.id, "status": "pending"}


def _upload_job_response(job: UploadConfirmJob) -> dict:
    resp = {
        "job_id": job.id,
        "file_id": job.file_id,
        "filename": job.filename,
        "status": job.status,
        "stage": job.stage,
        "stage_label": job.stage_label,
        "progress": job.progress,
        "total_rows": job.total_rows,
        "processed_rows": job.processed_rows,
        "inserted_rows": job.inserted_rows,
        "skipped_rows": job.skipped_rows,
        "error_msg": job.error_msg,
        "created_at": format_beijing_datetime(job.created_at),
        "finished_at": format_beijing_datetime(job.finished_at),
    }
    if job.status == "done" and job.result_data:
        resp.update(job.result_data)
    return resp


@router.get("/confirm/jobs")
def list_upload_confirm_jobs(
    status: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    _mark_interrupted_upload_jobs(db)
    q = db.query(UploadConfirmJob).filter(
        UploadConfirmJob.filename.isnot(None),
        UploadConfirmJob.filename != "",
    )
    if status:
        q = q.filter(UploadConfirmJob.status == status)
    else:
        q = q.filter(UploadConfirmJob.status.in_(["pending", "running", "error"]))
    jobs = q.order_by(UploadConfirmJob.created_at.desc(), UploadConfirmJob.id.desc()).limit(limit).all()
    return [_upload_job_response(job) for job in jobs]


@router.get("/confirm/jobs/{job_id}")
def get_upload_confirm_job(job_id: int, db: Session = Depends(get_db)):
    """轮询上传确认任务状态和进度。"""
    _mark_interrupted_upload_jobs(db)
    job = db.query(UploadConfirmJob).filter_by(id=job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")

    return _upload_job_response(job)


@router.post("/confirm/jobs/{job_id}/cancel")
def cancel_upload_confirm_job(job_id: int, db: Session = Depends(get_db)):
    job = db.query(UploadConfirmJob).filter_by(id=job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    if job.status not in ("pending", "running"):
        raise HTTPException(status_code=409, detail="任务已结束，不能取消")

    job.status = "cancelled"
    job.stage = "cancelled"
    job.stage_label = "已取消"
    job.error_msg = "用户取消上传处理"
    job.finished_at = datetime.utcnow()
    db.commit()
    db.refresh(job)
    _upload_progress.pop(job_id, None)
    return _upload_job_response(job)


@router.delete("/confirm/jobs/{job_id}")
def delete_upload_confirm_job(job_id: int, db: Session = Depends(get_db)):
    job = db.query(UploadConfirmJob).filter_by(id=job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    if job.status not in ("error", "cancelled"):
        raise HTTPException(status_code=409, detail="任务处理中，不能删除")

    db.delete(job)
    db.commit()
    _upload_progress.pop(job_id, None)
    return {"message": "已删除"}
