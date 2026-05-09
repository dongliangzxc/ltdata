import os
import shutil
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from sqlalchemy import tuple_
from sqlalchemy.orm import Session
from app.models.database import get_db
from app.models.schemas import UploadFileRecord, RawDataRecord, UploadFileOut, RawDataOut
from app.services.excel_parser import parse_raw_excel
from app.core.config import settings

router = APIRouter(prefix="/api/upload", tags=["upload"])


@router.post("", response_model=dict)
async def upload_file(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """上传原始数据 Excel 文件，解析后写入数据库（相同 item_id+month+platform 自动去重）"""
    if not file.filename.endswith((".xlsx", ".xls", ".csv")):
        raise HTTPException(status_code=400, detail="只支持 .xlsx / .xls / .csv 格式文件")

    # 保存文件
    save_path = Path(settings.UPLOAD_DIR) / file.filename
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
