import os
import shutil
import uuid
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from sqlalchemy import tuple_, text
from sqlalchemy.orm import Session
from app.models.database import get_db
from app.models.schemas import UploadFileRecord, RawDataRecord, UploadFileOut, RawDataOut, ColumnTemplate
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

# 内存进度表：job_id → 0-100，线程结束后清除
_upload_progress: dict[int, int] = {}

router = APIRouter(prefix="/api/upload", tags=["upload"])


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
def list_upload_files(db: Session = Depends(get_db)):
    """获取上传历史列表"""
    return db.query(UploadFileRecord).order_by(UploadFileRecord.uploaded_at.desc()).all()


@router.delete("/files/{file_id}")
def delete_upload_file(file_id: int, db: Session = Depends(get_db)):
    """删除上传文件记录及其原始数据（保留下游清洗/派发数据）"""
    record = db.query(UploadFileRecord).filter(UploadFileRecord.id == file_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="文件记录不存在")

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
):
    """后台线程：解析 Excel、去重、写库，更新 job 状态。"""
    db = SessionLocal()
    job = None
    try:
        job = db.query(UploadConfirmJob).filter_by(id=job_id).first()
        if not job:
            return
        job.status = "running"
        db.commit()
        _upload_progress[job_id] = 5

        # 1. 解析 Excel（5→40%）
        try:
            records, platform, month_range = parse_with_mapping(
                tmp_path, mapping, ignore_columns
            )
        except Exception as e:
            job.status = "error"
            job.error_msg = f"文件解析失败: {e}"
            job.finished_at = datetime.utcnow()
            db.commit()
            return
        _upload_progress[job_id] = 40

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
        _upload_progress[job_id] = 50

        # 3. 去重（50→60%）
        keys = [
            (str(r.get("item_id")), r.get("month"), r.get("platform"))
            for r in records
            if r.get("item_id") is not None
        ]
        existing_set: set = set()
        if keys:
            DEDUP_BATCH = 500
            for i in range(0, len(keys), DEDUP_BATCH):
                chunk = keys[i: i + DEDUP_BATCH]
                rows = db.query(
                    RawDataRecord.item_id, RawDataRecord.month, RawDataRecord.platform
                ).filter(
                    tuple_(RawDataRecord.item_id, RawDataRecord.month, RawDataRecord.platform).in_(chunk)
                ).all()
                existing_set.update((e.item_id, e.month, e.platform) for e in rows)
        to_insert = [
            r for r in records
            if (str(r.get("item_id")), r.get("month"), r.get("platform")) not in existing_set
        ]
        skipped = len(records) - len(to_insert)
        _upload_progress[job_id] = 60

        # 4. 写 upload_files 记录（60→65%）
        file_record = UploadFileRecord(
            filename=original_filename,
            platform=platform,
            month_range=month_range,
            row_count=len(records),
            status="done",
            template_id=saved_template_id,
        )
        db.add(file_record)
        db.flush()

        # 5. 批量写入 raw_data（65→90%）
        if to_insert:
            batch_size = 1000
            for i in range(0, len(to_insert), batch_size):
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
                _upload_progress[job_id] = 65 + int(25 * min(i + batch_size, len(to_insert)) / max(len(to_insert), 1))
        db.commit()
        db.refresh(file_record)
        _upload_progress[job_id] = 90

        # 6. 移动临时文件（90→95%）
        final_path = Path(settings.UPLOAD_DIR) / original_filename
        shutil.move(str(tmp_path), str(final_path))
        _upload_progress[job_id] = 95

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
        job.file_id     = file_record.id
        job.status      = "done"
        job.progress    = 100
        job.result_data = result
        job.finished_at = datetime.utcnow()
        db.commit()
        _upload_progress[job_id] = 100

    except Exception as e:
        try:
            job = db.query(UploadConfirmJob).filter_by(id=job_id).first()
            if job:
                job.status    = "error"
                job.error_msg = str(e)
                job.finished_at = datetime.utcnow()
                db.commit()
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
    job = UploadConfirmJob(status="pending")
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
        ),
        daemon=True,
    )
    t.start()

    return {"job_id": job.id, "status": "pending"}


@router.get("/confirm/jobs/{job_id}")
def get_upload_confirm_job(job_id: int, db: Session = Depends(get_db)):
    """轮询上传确认任务状态和进度。"""
    job = db.query(UploadConfirmJob).filter_by(id=job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")

    progress = _upload_progress.get(job_id, job.progress)
    resp: dict = {
        "job_id":   job.id,
        "status":   job.status,
        "progress": progress,
        "error_msg": job.error_msg,
    }
    if job.status == "done" and job.result_data:
        resp.update(job.result_data)
    return resp
