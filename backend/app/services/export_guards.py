from contextlib import contextmanager
import fcntl
from pathlib import Path
import tempfile

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.schemas import ExportJob, WorkbenchExportJob

MAX_SYNC_EXPORT_ROWS = 20_000
MAX_RUNNING_EXPORT_JOBS = 2

RUNNING_STATUSES = ("pending", "running")
_EXPORT_LOCK_PATH = Path(tempfile.gettempdir()) / "luotu_export_capacity.lock"


def ensure_export_row_limit(total: int, *, max_rows: int, label: str = "导出") -> None:
    if total > max_rows:
        raise HTTPException(
            status_code=400,
            detail=f"{label}数据量过大（{total} 行），请缩小筛选范围后再导出，当前上限 {max_rows} 行",
        )


def ensure_async_export_capacity(db: Session) -> None:
    running_workbench_jobs = (
        db.query(WorkbenchExportJob)
        .filter(WorkbenchExportJob.status.in_(RUNNING_STATUSES))
        .count()
    )
    running_match_jobs = (
        db.query(ExportJob)
        .filter(ExportJob.status.in_(RUNNING_STATUSES))
        .count()
    )
    running_total = running_workbench_jobs + running_match_jobs
    if running_total >= MAX_RUNNING_EXPORT_JOBS:
        raise HTTPException(
            status_code=429,
            detail="当前导出任务较多，请稍后再试",
        )


@contextmanager
def reserve_async_export_capacity(db: Session):
    _EXPORT_LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _EXPORT_LOCK_PATH.open("w") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            ensure_async_export_capacity(db)
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
