"""分发批次取数口径：每个文件的最新一次已完成分发批次。"""

from sqlalchemy import String, cast, func, or_

from app.models.schemas import DispatchBatch, UploadFileRecord


def latest_done_batch_subquery(db):
    """每个文件最新一次已完成分发批次的子查询。

    身份标识按「分发批次 batch_key → 上传文件 batch_key → file_id」依次回退。
    只按分发批次的 `batch_key` / `file_id` 二选一会有漏：同一文件既可能通过
    上传批次（带 `batch_key`）分发，也可能通过单文件（`batch_key` 为空）补分发，
    两种批次会被当成两个身份同时命中最新批次，导致分发结果被重复统计。
    单文件补分发时回退到该文件的 `upload_files.batch_key`，即可和上传批次归为
    同一身份；没有上传批次标识的单文件仍按 `file_id` 区分。
    """
    upload_batch_key = (
        db.query(UploadFileRecord.batch_key)
        .filter(UploadFileRecord.id == DispatchBatch.file_id)
        .correlate(DispatchBatch)
        .scalar_subquery()
    )
    batch_identity = func.coalesce(
        func.nullif(DispatchBatch.batch_key, ""),
        func.nullif(upload_batch_key, ""),
        cast(DispatchBatch.file_id, String),
    )
    return (
        db.query(
            batch_identity.label("batch_identity"),
            func.max(DispatchBatch.id).label("batch_id"),
        )
        .filter(
            DispatchBatch.status == "done",
            or_(DispatchBatch.file_id.isnot(None), DispatchBatch.batch_key.isnot(None)),
        )
        .group_by(batch_identity)
        .subquery()
    )
