"""
导出 API
- POST /api/export        触发异步导出，立即返回 job_id
- GET  /api/export/jobs   列出历史导出任务
- GET  /api/export/download/{token}  下载文件
- GET  /api/export/filters   导出筛选项
"""
import threading
from pathlib import Path
from urllib.parse import quote
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import func
from sqlalchemy.orm import Session
from app.core.auth_deps import get_current_user
from app.core.permissions import visible_category_codes
from app.models.database import get_db, SessionLocal
from app.models.schemas import CleanJobRecord, Category, ExportJob, ExportJobOut, User
from app.services.exporter import EXPORTABLE_CLEAN_JOB_STATUSES, export_match_filters, export_match_job
from app.services.export_guards import reserve_async_export_capacity

router = APIRouter(prefix="/api/export", tags=["export"])


def _visible_export_category_codes(db: Session, current_user: User) -> set[str] | None:
    if getattr(current_user, "is_admin", 0) == 1:
        return None
    permissions = getattr(current_user, "category_permissions", None)
    if not permissions:
        return None
    all_codes = [code for code, in db.query(Category.code).order_by(Category.sort_order, Category.name).all()]
    if not all_codes:
        return set(permissions)
    return set(visible_category_codes(current_user, all_codes))


def _ensure_export_category_visible(db: Session, current_user: User, category_code: str | None) -> None:
    if not category_code:
        return
    visible_codes = _visible_export_category_codes(db, current_user)
    if visible_codes is not None and category_code not in visible_codes:
        raise HTTPException(status_code=403, detail="无权限访问该品类")


def _filter_export_category(query, model, db: Session, current_user: User):
    visible_codes = _visible_export_category_codes(db, current_user)
    if visible_codes is None:
        return query
    return query.filter(model.category_code.in_(visible_codes))


def _parse_job_months(scope, fallback_month=None) -> list[int]:
    months = []
    if isinstance(scope, dict):
        scope_months = scope.get("months")
        if isinstance(scope_months, list):
            months = scope_months
    if not months and fallback_month is not None:
        months = [fallback_month]
    parsed: list[int] = []
    for month in months:
        try:
            parsed.append(int(month))
        except (TypeError, ValueError):
            continue
    return parsed


def _job_months(job: CleanJobRecord) -> list[int]:
    return _parse_job_months(job.source_scope, getattr(job, "month", None))


def _run_export_thread(export_job_id: int):
    db = SessionLocal()
    try:
        job = db.query(ExportJob).filter(ExportJob.id == export_job_id).first()
        if not job:
            return
        job.status = "running"
        db.commit()

        if job.clean_job_id is not None:
            files = export_match_job(db, job.clean_job_id, job.filename_prefix)
        else:
            files = export_match_filters(
                db,
                months=job.months or [],
                category_code=job.category_code or "",
                platforms=job.platforms or [],
                filename_prefix=job.filename_prefix,
            )

        if not files:
            job.status = "error"
            job.error_msg = "无可导出数据，请先执行型号匹配"
        else:
            f = files[0]
            job.status = "done"
            job.filename = f["filename"]
            job.token = f["token"]
            job.rows = f["rows"]
            job.pending_rows = f["pending_rows"]
        db.commit()
    except Exception as e:
        try:
            job = db.query(ExportJob).filter(ExportJob.id == export_job_id).first()
            if job:
                job.status = "error"
                job.error_msg = str(e)
                db.commit()
        except Exception:
            pass
    finally:
        db.close()


def _as_non_empty_int_list(value, field_name: str) -> list[int]:
    if not isinstance(value, list) or len(value) == 0:
        raise HTTPException(status_code=400, detail=f"{field_name} 不能为空")
    try:
        return [int(item) for item in value]
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail=f"{field_name} 必须是数字数组") from None


def _as_non_empty_str_list(value, field_name: str) -> list[str]:
    if not isinstance(value, list) or len(value) == 0:
        raise HTTPException(status_code=400, detail=f"{field_name} 不能为空")
    items = [str(item).strip() for item in value if str(item).strip()]
    if not items:
        raise HTTPException(status_code=400, detail=f"{field_name} 不能为空")
    return items


@router.post("")
def trigger_export(
    payload: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    异步触发导出，立即返回 job_id。
    payload: {"clean_job_id": 1, "filename_prefix": "已处理数据"}
    payload: {"months": [202501], "category_code": "headphone", "platforms": ["jd"], "filename_prefix": "已处理数据"}
    """
    filename_prefix: str = str(payload.get("filename_prefix") or "已处理数据").strip() or "已处理数据"
    has_clean_job_id = "clean_job_id" in payload
    clean_job_id = payload.get("clean_job_id")
    has_filter_payload = any(key in payload for key in ("months", "category_code", "platforms"))

    if has_clean_job_id and has_filter_payload:
        raise HTTPException(status_code=400, detail="clean_job_id 不能同时与筛选条件使用")

    if has_clean_job_id:
        try:
            clean_job_id = int(clean_job_id)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="clean_job_id 必须为整数") from None
        job_record = db.query(CleanJobRecord).filter(CleanJobRecord.id == clean_job_id).first()
        if not job_record:
            raise HTTPException(status_code=404, detail="清洗任务不存在")
        _ensure_export_category_visible(db, current_user, job_record.category_code)
        job_kwargs = {"clean_job_id": clean_job_id, "months": None, "category_code": None, "platforms": None}
    else:
        months = _as_non_empty_int_list(payload.get("months"), "months")
        category_code = str(payload.get("category_code") or "").strip()
        platforms = _as_non_empty_str_list(payload.get("platforms"), "platforms")
        if not category_code:
            raise HTTPException(status_code=400, detail="category_code 不能为空")
        _ensure_export_category_visible(db, current_user, category_code)
        job_kwargs = {
            "clean_job_id": None,
            "months": months,
            "category_code": category_code,
            "platforms": platforms,
        }

    with reserve_async_export_capacity(db):
        export_job = ExportJob(
            filename_prefix=filename_prefix,
            status="pending",
            **job_kwargs,
        )
        db.add(export_job)
        db.commit()
        db.refresh(export_job)

    t = threading.Thread(target=_run_export_thread, args=(export_job.id,), daemon=True)
    t.start()

    return {"job_id": export_job.id, "status": export_job.status}


@router.get("/jobs")
def list_jobs(
    clean_job_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(ExportJob).order_by(ExportJob.created_at.desc())
    visible_codes = _visible_export_category_codes(db, current_user)
    if clean_job_id is not None:
        job_record = db.query(CleanJobRecord).filter(CleanJobRecord.id == clean_job_id).first()
        if job_record:
            _ensure_export_category_visible(db, current_user, job_record.category_code)
        query = query.filter(ExportJob.clean_job_id == clean_job_id)
    elif visible_codes is not None:
        query = query.filter(ExportJob.category_code.in_(visible_codes))
    jobs = query.all()
    return {"data": [ExportJobOut.model_validate(j) for j in jobs]}


@router.get("/filters")
def get_export_filters(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    visible_codes = _visible_export_category_codes(db, current_user)
    base_filters = [CleanJobRecord.status.in_(EXPORTABLE_CLEAN_JOB_STATUSES)]
    if visible_codes is not None:
        base_filters.append(CleanJobRecord.category_code.in_(visible_codes))
    source_scopes = db.query(CleanJobRecord.source_scope).filter(*base_filters).all()
    months = sorted({month for (scope,) in source_scopes for month in _parse_job_months(scope)}, reverse=True)
    platforms = sorted({
        platform
        for (platform,) in db.query(func.trim(CleanJobRecord.platform))
        .filter(*base_filters, CleanJobRecord.platform.isnot(None))
        .distinct()
        .all()
        if platform
    })
    category_codes = sorted({
        code
        for (code,) in db.query(func.trim(CleanJobRecord.category_code))
        .filter(*base_filters, CleanJobRecord.category_code.isnot(None))
        .distinct()
        .all()
        if code
    })
    categories = []
    if category_codes:
        category_names = {
            category.code: category.name
            for category in db.query(Category).filter(Category.code.in_(category_codes)).all()
        }
        categories = [
            {"code": code, "name": category_names.get(code) or code}
            for code in category_codes
        ]
    return {"months": months, "platforms": platforms, "categories": categories}


@router.get("/jobs/{job_id}", response_model=ExportJobOut)
def get_job(job_id: int, db: Session = Depends(get_db)):
    job = db.query(ExportJob).filter(ExportJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="导出任务不存在")
    return ExportJobOut.model_validate(job)


@router.get("/download/{token}")
def download_export(token: str, db: Session = Depends(get_db)):
    job = db.query(ExportJob).filter(ExportJob.token == token).first()
    if not job or not job.filename:
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
