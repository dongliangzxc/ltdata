"""Snapshot writes stay batched, ordered and part of the caller's transaction."""

import pytest
from sqlalchemy import event, func

from app.models.schemas import (
    Category, CleanJobItemRecord, CleanJobRecord, DispatchBatch, DispatchItem,
    RawDataRecord, UploadFileRecord,
)
from app.services.clean_task_snapshot import (
    create_category_task_snapshot, upsert_monthly_task_snapshot,
)


def _seed_dispatch_rows(db, count):
    if db.query(Category).filter_by(code="headphone").first() is None:
        db.add(Category(code="headphone", name="耳机"))
    upload = UploadFileRecord(filename="snapshot.xlsx", platform="jd", status="done")
    db.add(upload)
    db.flush()
    batch = DispatchBatch(file_id=upload.id, status="done")
    db.add(batch)
    db.flush()
    start = (db.query(func.max(RawDataRecord.id)).scalar() or 0) + 1
    raw_ids = list(range(start, start + count))
    db.bulk_insert_mappings(RawDataRecord, [
        dict(id=raw_id, file_id=upload.id, platform="京东", month=202603,
             item_id=f"sku-{raw_id}", item_name="耳机")
        for raw_id in raw_ids
    ])
    # Snapshot order follows dispatch order, including across write batches.
    raw_ids.reverse()
    db.bulk_insert_mappings(DispatchItem, [
        dict(batch_id=batch.id, raw_data_id=raw_id, category_code="headphone")
        for raw_id in raw_ids
    ])
    file_id, batch_id = upload.id, batch.id
    db.commit()
    return file_id, batch_id, raw_ids


def _monthly_snapshot(db, **kwargs):
    return upsert_monthly_task_snapshot(
        db, category_code="headphone", platform="jd", month=202603,
        rules={"dedup": True}, **kwargs,
    )


@pytest.mark.parametrize("entry_point", ["category", "monthly"])
def test_snapshot_batches_inserts_and_preserves_dispatch_order(db, entry_point):
    file_id, batch_id, raw_ids = _seed_dispatch_rows(db, 1005)
    insert_calls = []

    def record_insert(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO clean_job_items "):
            insert_calls.append((executemany, len(parameters)))

    engine = db.get_bind()
    event.listen(engine, "before_cursor_execute", record_insert)
    try:
        if entry_point == "monthly":
            job, count, action, snapshot_ids = _monthly_snapshot(db)
            assert action == "created"
        else:
            job, count = create_category_task_snapshot(
                db, category_code="headphone", platform="jd",
                dispatch_batch_id=batch_id, task_name="耳机清洗", rules={"dedup": True},
            )
    finally:
        event.remove(engine, "before_cursor_execute", record_insert)

    assert insert_calls == [(True, 1000), (True, 5)]
    assert count == job.row_in == 1005
    assert job.file_ids == [file_id]
    assert job.source_scope["dispatch_batch_ids"] == [batch_id]
    items = db.query(CleanJobItemRecord).filter_by(clean_job_id=job.id).order_by(CleanJobItemRecord.id).all()
    assert [item.raw_data_id for item in items] == raw_ids
    assert all(item.platform == "jd" and item.category_code == "headphone" for item in items)
    assert all(item.dispatch_batch_id == batch_id and item.created_at is not None for item in items)
    if entry_point == "monthly":
        assert snapshot_ids == [item.id for item in items]

    # The service must not commit individual batches.
    db.rollback()
    assert db.query(CleanJobRecord).count() == 0
    assert db.query(CleanJobItemRecord).count() == 0


def test_monthly_snapshot_append_returns_only_new_ids_in_dispatch_order(db):
    first_file, first_batch, first_raw_ids = _seed_dispatch_rows(db, 2)
    job, _, _, first_ids = _monthly_snapshot(db)
    job.status = "reviewing"
    job_id = job.id
    db.commit()
    second_file, second_batch, second_raw_ids = _seed_dispatch_rows(db, 3)

    job, count, action, new_ids = _monthly_snapshot(db)

    assert job.id == job_id
    assert action == "appended"
    assert count == 3
    assert job.row_in == 5
    assert job.file_ids == [first_file, second_file]
    assert job.source_scope["dispatch_batch_ids"] == [first_batch, second_batch]
    items = db.query(CleanJobItemRecord).filter_by(clean_job_id=job_id).order_by(CleanJobItemRecord.id).all()
    assert [item.raw_data_id for item in items] == first_raw_ids + second_raw_ids
    assert [item.id for item in items] == first_ids + new_ids
    assert set(first_ids).isdisjoint(new_ids)


def test_category_snapshot_batches_nullable_platform_with_other_platforms(db):
    _, batch_id, raw_ids = _seed_dispatch_rows(db, 3)
    db.query(RawDataRecord).filter_by(id=raw_ids[1]).update({"platform": None})
    db.commit()
    insert_calls = []

    def record_insert(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO clean_job_items "):
            insert_calls.append((executemany, len(parameters)))

    engine = db.get_bind()
    event.listen(engine, "before_cursor_execute", record_insert)
    try:
        job, count = create_category_task_snapshot(
            db, category_code="headphone", platform=None,
            dispatch_batch_id=batch_id, task_name="跨平台耳机", rules=None,
        )
    finally:
        event.remove(engine, "before_cursor_execute", record_insert)

    items = db.query(CleanJobItemRecord).filter_by(clean_job_id=job.id).order_by(CleanJobItemRecord.id).all()
    assert count == 3
    assert insert_calls == [(True, 3)]
    assert [item.raw_data_id for item in items] == raw_ids
    assert [item.platform for item in items] == ["jd", None, "jd"]


def test_monthly_snapshot_reclean_rolls_back_all_batches_on_write_failure(db):
    _, _, old_raw_ids = _seed_dispatch_rows(db, 2)
    job, _, _, old_ids = _monthly_snapshot(db)
    job.status = "reviewing"
    job_id = job.id
    db.commit()
    _seed_dispatch_rows(db, 1005)
    calls = 0

    def fail_second_insert(conn, cursor, statement, parameters, context, executemany):
        nonlocal calls
        if statement.startswith("INSERT INTO clean_job_items "):
            calls += 1
            if calls == 2:
                raise RuntimeError("second snapshot batch failed")

    engine = db.get_bind()
    event.listen(engine, "before_cursor_execute", fail_second_insert)
    try:
        with pytest.raises(RuntimeError, match="second snapshot batch failed"):
            _monthly_snapshot(db, force_reclean=True)
    finally:
        event.remove(engine, "before_cursor_execute", fail_second_insert)
        db.rollback()

    items = db.query(CleanJobItemRecord).filter_by(clean_job_id=job_id).order_by(CleanJobItemRecord.id).all()
    assert [item.id for item in items] == old_ids
    assert [item.raw_data_id for item in items] == old_raw_ids
    assert db.get(CleanJobRecord, job_id).row_in == 2
