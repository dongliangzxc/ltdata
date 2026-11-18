"""Reconcile actual outputs; never infer unrecorded historical duplicates."""
from app.services.clean_task_queue import BUSY_CLEAN_STATUSES


def clean_accounting(job, retained_count: int, filtered_count: int, duplicate_count: int) -> dict:
    complete = job.row_duplicated is not None
    input_count = job.row_in or 0
    difference = input_count - retained_count - filtered_count - duplicate_count if complete else None
    if job.status in BUSY_CLEAN_STATUSES:
        status = "processing"
    elif job.status in {"failed", "error"}:
        status = "failed"
    elif not complete:
        status = "legacy"
    else:
        status = "balanced" if difference == 0 else "mismatch"
    return dict(input_count=input_count, retained_count=retained_count, filtered_count=filtered_count,
                duplicate_count=duplicate_count, audit_complete=complete, difference=difference, status=status)
