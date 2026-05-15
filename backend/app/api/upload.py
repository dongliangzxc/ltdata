import os
import shutil
import uuid
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from sqlalchemy import tuple_
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
    """删除上传文件记录及其原始数据"""
    record = db.query(UploadFileRecord).filter(UploadFileRecord.id == file_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="文件记录不存在")
    db.delete(record)
    db.commit()
    return {"message": "已删除"}


# ─── P9: Two-phase upload ────────────────────────────────────

REQUIRED_FIELDS = {"item_id", "month", "platform", "item_name", "sales_qty", "sales_amount", "price"}


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


@router.post("/confirm")
async def upload_confirm(payload: dict, db: Session = Depends(get_db)):
    """Phase 2: Parse temp file with confirmed mapping and store data."""
    temp_file_id: str = payload.get("temp_file_id", "")
    mapping: dict = payload.get("mapping", {})
    ignore_columns: list = payload.get("ignore_columns", [])
    save_template_name = payload.get("save_template_name")
    template_id_use = payload.get("template_id")

    if not temp_file_id:
        raise HTTPException(status_code=400, detail="temp_file_id 不能为空")

    # Find temporary file
    tmp_dir = Path(settings.UPLOAD_DIR) / "tmp"
    matches = list(tmp_dir.glob(f"{temp_file_id}_*"))
    if not matches:
        raise HTTPException(status_code=404, detail="临时文件不存在或已过期，请重新上传")
    tmp_path = matches[0]
    original_filename = tmp_path.name[len(temp_file_id) + 1:]

    # Validate required fields are mapped
    mapped_targets = {v for v in mapping.values() if v != "__ext__"}
    missing = REQUIRED_FIELDS - mapped_targets
    if missing:
        raise HTTPException(
            status_code=422,
            detail=f"以下必填字段未映射：{', '.join(sorted(missing))}"
        )

    try:
        records, platform, month_range = parse_with_mapping(tmp_path, mapping, ignore_columns)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"文件解析失败: {e}")

    # Optionally save/update template
    saved_template_id = template_id_use
    if save_template_name:
        fp = _col_fingerprint(list(mapping.keys()))
        existing = db.query(ColumnTemplate).filter(
            ColumnTemplate.col_fingerprint == fp,
            ColumnTemplate.is_builtin == 0,
        ).first()
        if not existing:
            # Also check by name to avoid IntegrityError
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
            from sqlalchemy.exc import IntegrityError
            try:
                tmpl = ColumnTemplate(
                    name=save_template_name,
                    col_fingerprint=fp,
                    mapping=mapping,
                    ignore_columns=ignore_columns,
                    is_builtin=0,
                )
                db.add(tmpl)
                db.flush()
                saved_template_id = tmpl.id
            except IntegrityError:
                db.rollback()
                raise HTTPException(
                    status_code=409,
                    detail=f"模板名称「{save_template_name}」已存在，请使用不同的名称"
                )

    # Deduplication — batch the IN query to avoid oversized SQL (max 500 tuples/batch)
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

    # Write upload_files record
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

    # Write raw_data — use Core bulk INSERT for speed
    if to_insert:
        db.execute(
            RawDataRecord.__table__.insert(),
            [
                {
                    "file_id": file_record.id,
                    "platform": r.get("platform"),
                    "month": r.get("month"),
                    "category_lv0": r.get("category_lv0"),
                    "category_lv1": r.get("category_lv1"),
                    "category_lv2": r.get("category_lv2"),
                    "category_lv3": r.get("category_lv3"),
                    "category_lv4": r.get("category_lv4"),
                    "category_lv5": r.get("category_lv5"),
                    "item_id": str(r.get("item_id")) if r.get("item_id") else None,
                    "item_name": r.get("item_name"),
                    "item_image": r.get("item_image"),
                    "item_url": r.get("item_url"),
                    "ref_price": r.get("ref_price"),
                    "brand_raw": r.get("brand_raw"),
                    "shop_name": r.get("shop_name"),
                    "sales_qty": r.get("sales_qty"),
                    "sales_amount": r.get("sales_amount"),
                    "price": r.get("price"),
                    "brand_std": r.get("brand_std"),
                    "model_std": r.get("model_std"),
                    "extra_data": r.get("extra_data"),
                }
                for r in to_insert
            ],
        )
    db.commit()
    db.refresh(file_record)

    # Move temp file to permanent directory
    final_path = Path(settings.UPLOAD_DIR) / original_filename
    shutil.move(str(tmp_path), str(final_path))

    preview = records[:50]
    return {
        "file_id": file_record.id,
        "filename": original_filename,
        "platform": platform,
        "month_range": month_range,
        "row_count": len(records),
        "inserted": len(to_insert),
        "skipped": skipped,
        "preview": preview,
    }
