import os
from pathlib import Path
from urllib.parse import quote
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from app.models.database import get_db
from app.models.schemas import CleanJobRecord
from app.services.exporter import export_match_job
from app.core.config import settings

router = APIRouter(prefix="/api/export", tags=["export"])

# 内存 token 映射（生产可改 Redis）
_token_map: dict[str, str] = {}


@router.post("")
def trigger_export(payload: dict, db: Session = Depends(get_db)):
    """
    触发导出。
    payload: {
        "clean_job_id": 1,
        "filename_prefix": "Soundbar 7-8月已处理"
    }
    """
    clean_job_id: int = payload.get("clean_job_id")
    filename_prefix: str = payload.get("filename_prefix", "已处理数据")

    if not clean_job_id:
        raise HTTPException(status_code=400, detail="clean_job_id 不能为空")

    job = db.query(CleanJobRecord).filter(CleanJobRecord.id == clean_job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="清洗任务不存在")

    files = export_match_job(db, clean_job_id, filename_prefix)
    if not files:
        raise HTTPException(status_code=404, detail="无可导出数据，请先执行型号匹配")

    # 注册 token
    for f in files:
        _token_map[f["token"]] = f["path"]

    return {
        "files": [
            {"filename": f["filename"], "token": f["token"], "rows": f["rows"], "pending_rows": f.get("pending_rows", 0)}
            for f in files
        ]
    }


@router.get("/download/{token}")
def download_file(token: str):
    """通过 token 下载导出文件"""
    file_path = _token_map.get(token)
    if not file_path or not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="文件不存在或已过期")

    filename = Path(file_path).name
    # 去掉 token 前缀还原原始文件名
    original_name = "_".join(filename.split("_")[1:]) if "_" in filename else filename

    return FileResponse(
        path=file_path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(original_name)}"},
    )
