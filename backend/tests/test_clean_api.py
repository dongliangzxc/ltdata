from datetime import datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.clean import router
from app.models.database import get_db
from app.models.schemas import (
    Category,
    CleanJobItemRecord,
    CleanJobRecord,
    CleanedDataRecord,
    DispatchBatch,
    DispatchItem,
    MatchResult,
    RawDataRecord,
    UploadFileRecord,
)


def _make_client(db, *, raise_server_exceptions=True):
    app = FastAPI()
    app.include_router(router)

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    return TestClient(app, raise_server_exceptions=raise_server_exceptions)


def test_run_dispatch_batch_clean_creates_one_job_per_category(db):
    client = _make_client(db)
    file_record = UploadFileRecord(filename="dispatch-clean.xlsx", platform="jd", row_count=2, status="done")
    db.add(file_record)
    db.flush()
    first_raw = RawDataRecord(
        file_id=file_record.id,
        platform="jd",
        month=202605,
        item_id="laser-tv-1",
        item_name="海信激光电视",
        brand_raw="海信",
        sales_qty=10,
        sales_amount=1000,
    )
    second_raw = RawDataRecord(
        file_id=file_record.id,
        platform="jd",
        month=202605,
        item_id="tv-1",
        item_name="普通电视",
        brand_raw="TCL",
        sales_qty=5,
        sales_amount=500,
    )
    db.add_all([first_raw, second_raw])
    db.flush()
    batch = DispatchBatch(file_id=file_record.id, status="done", total_rows=2, dispatched_rows=3, unmatched_rows=0)
    db.add(batch)
    db.flush()
    db.add_all([
        DispatchItem(batch_id=batch.id, raw_data_id=first_raw.id, category_code="projector", matched_rule_id=1),
        DispatchItem(batch_id=batch.id, raw_data_id=first_raw.id, category_code="tv", matched_rule_id=2),
        DispatchItem(batch_id=batch.id, raw_data_id=second_raw.id, category_code="tv", matched_rule_id=3),
    ])
    db.commit()

    response = client.post(f"/api/clean/run-dispatch-batch", json={"dispatch_batch_id": batch.id, "rules": {"dedup": True}})

    assert response.status_code == 200
    payload = response.json()
    assert payload["dispatch_batch_id"] == batch.id
    assert [job["dispatch_category_code"] for job in payload["jobs"]] == ["projector", "tv"]
    jobs = db.query(CleanJobRecord).order_by(CleanJobRecord.dispatch_category_code).all()
    assert [(job.dispatch_category_code, job.row_in, job.row_out) for job in jobs] == [
        ("projector", 1, 1),
        ("tv", 2, 2),
    ]
    assert db.query(CleanedDataRecord).count() == 3


def test_list_clean_jobs_returns_beijing_time_and_scope_description(db):
    client = _make_client(db)
    category = Category(code="projector", name="投影仪")
    file_record = UploadFileRecord(
        filename="jd-projector-202605.xlsx",
        platform="jd",
        month_range="202605",
        row_count=10,
        status="done",
    )
    db.add_all([category, file_record])
    db.flush()
    batch = DispatchBatch(file_id=file_record.id, status="done", total_rows=10, dispatched_rows=8, unmatched_rows=2)
    db.add(batch)
    db.flush()
    job = CleanJobRecord(
        file_ids=[file_record.id],
        rules={"dedup": True},
        status="done",
        row_in=8,
        row_out=7,
        dispatch_batch_id=batch.id,
        dispatch_category_code="projector",
        created_at=datetime(2026, 5, 27, 1, 2, 3),
    )
    db.add(job)
    db.commit()

    response = client.get("/api/clean/jobs")

    assert response.status_code == 200
    payload = response.json()
    assert payload[0]["created_at"] == "2026-05-27 09:02:03"
    assert payload[0]["scope_desc"] == (
        f"分发批次#{batch.id} / 品类：投影仪（projector） / 平台：jd / "
        "月份：202605 / 文件：jd-projector-202605.xlsx"
    )


def test_list_clean_jobs_uses_legacy_scope_when_category_code_without_snapshot_markers(db):
    client = _make_client(db)
    category = Category(code="router", name="路由器")
    file_record = UploadFileRecord(
        filename="jd-router-202605.xlsx",
        platform="jd",
        month_range="202605",
        row_count=5,
        status="done",
    )
    db.add_all([category, file_record])
    db.flush()
    batch = DispatchBatch(file_id=file_record.id, status="done", total_rows=5, dispatched_rows=5, unmatched_rows=0)
    db.add(batch)
    db.flush()
    job = CleanJobRecord(
        file_ids=[file_record.id],
        rules={"dedup": True},
        status="done",
        row_in=5,
        row_out=5,
        dispatch_batch_id=batch.id,
        dispatch_category_code="router",
        category_code="router",
        created_at=datetime(2026, 5, 27, 1, 2, 3),
    )
    db.add(job)
    db.commit()

    response = client.get("/api/clean/jobs")

    assert response.status_code == 200
    payload = response.json()
    assert payload[0]["scope_desc"] == (
        f"分发批次#{batch.id} / 品类：路由器（router） / 平台：jd / "
        "月份：202605 / 文件：jd-router-202605.xlsx"
    )


def test_list_clean_jobs_returns_match_summary_counts(db):
    client = _make_client(db)
    job = CleanJobRecord(
        file_ids=[],
        rules={"dedup": True},
        status="reviewing",
        row_in=6,
        row_out=6,
        task_name="路由器 第1批",
        category_code="router",
    )
    db.add(job)
    db.flush()
    db.add_all([
        MatchResult(clean_job_id=job.id, raw_data_id=1, match_status="url_matched"),
        MatchResult(clean_job_id=job.id, raw_data_id=2, match_status="matched"),
        MatchResult(clean_job_id=job.id, raw_data_id=3, match_status="confirmed"),
        MatchResult(clean_job_id=job.id, raw_data_id=4, match_status="pending"),
        MatchResult(clean_job_id=job.id, raw_data_id=5, match_status="text_only"),
        MatchResult(clean_job_id=job.id, raw_data_id=6, match_status="disputed"),
    ])
    db.commit()

    response = client.get("/api/clean/jobs")

    assert response.status_code == 200
    payload = response.json()[0]
    assert payload["confirmed_count"] == 1
    assert payload["publishable_count"] == 3
    assert payload["pending_count"] == 2
    assert payload["disputed_count"] == 1


def test_get_clean_pool_summary_endpoint_returns_pending_counts(db):
    client = _make_client(db)
    category = Category(code="router", name="路由器")
    upload = UploadFileRecord(filename="router-pool.xlsx", platform="jd", row_count=1, status="done")
    db.add_all([category, upload])
    db.flush()

    raw = RawDataRecord(file_id=upload.id, platform="jd", item_id="sku-1", item_name="路由器1")
    db.add(raw)
    db.flush()

    batch = DispatchBatch(file_id=upload.id, status="done", total_rows=1, dispatched_rows=1, unmatched_rows=0)
    db.add(batch)
    db.flush()
    db.add(DispatchItem(batch_id=batch.id, raw_data_id=raw.id, category_code="router"))
    db.commit()

    response = client.get(f"/api/clean/pool/summary?dispatch_batch_id={batch.id}")

    assert response.status_code == 200
    assert response.json() == [{
        "category_code": "router",
        "category_name": "路由器",
        "platform": "jd",
        "current_batch_count": 1,
        "pending_count": 1,
        "active_job_count": 0,
    }]


def test_create_clean_task_endpoint_creates_snapshot_and_runs_clean_and_match(db, monkeypatch):
    client = _make_client(db)
    category = Category(code="router", name="路由器")
    upload = UploadFileRecord(filename="router-task.xlsx", platform="jd", row_count=1, status="done")
    db.add_all([category, upload])
    db.flush()

    raw = RawDataRecord(file_id=upload.id, platform="jd", item_id="sku-1", item_name="路由器1")
    db.add(raw)
    db.flush()

    batch = DispatchBatch(file_id=upload.id, status="done", total_rows=1, dispatched_rows=1, unmatched_rows=0)
    db.add(batch)
    db.flush()
    db.add(DispatchItem(batch_id=batch.id, raw_data_id=raw.id, category_code="router"))
    db.commit()

    run_match_calls = []

    def fake_run_match(match_db, clean_job_id):
        run_match_calls.append(clean_job_id)
        return {"total": 1, "matched": 0}

    monkeypatch.setattr("app.api.clean.run_match", fake_run_match)

    response = client.post("/api/clean/tasks", json={
        "category_code": "router",
        "platform": "jd",
        "dispatch_batch_id": batch.id,
        "task_name": "路由器 第1批",
        "rules": {"dedup": True},
    })

    assert response.status_code == 200
    payload = response.json()
    assert payload["snapshot_count"] == 1
    assert payload["match_status"] == "done"
    assert payload["job"]["task_name"] == "路由器 第1批"
    assert payload["job"]["category_code"] == "router"
    assert payload["job"]["platform"] == "jd"
    assert payload["job"]["status"] == "reviewing"
    assert run_match_calls == [payload["job"]["id"]]
    assert db.query(CleanJobItemRecord).filter_by(clean_job_id=payload["job"]["id"]).count() == 1
    assert db.query(CleanedDataRecord).filter_by(clean_job_id=payload["job"]["id"]).count() == 1


def test_create_clean_task_endpoint_rejects_when_no_pending_rows(db):
    client = _make_client(db)

    response = client.post("/api/clean/tasks", json={
        "category_code": "router",
        "platform": "jd",
    })

    assert response.status_code == 400
    assert "没有可创建任务的数据" in response.json()["detail"]


def _create_pending_router_dispatch(db, filename="router-task-failure.xlsx"):
    category = Category(code="router", name="路由器")
    upload = UploadFileRecord(filename=filename, platform="jd", row_count=1, status="done")
    db.add_all([category, upload])
    db.flush()
    raw = RawDataRecord(file_id=upload.id, platform="jd", item_id="sku-1", item_name="路由器1")
    db.add(raw)
    db.flush()
    batch = DispatchBatch(file_id=upload.id, status="done", total_rows=1, dispatched_rows=1, unmatched_rows=0)
    db.add(batch)
    db.flush()
    db.add(DispatchItem(batch_id=batch.id, raw_data_id=raw.id, category_code="router"))
    db.commit()
    return batch


def test_create_clean_task_endpoint_marks_job_failed_when_run_clean_raises(db, monkeypatch):
    client = _make_client(db, raise_server_exceptions=False)
    batch = _create_pending_router_dispatch(db, filename="router-clean-fails.xlsx")

    def fake_run_clean(failing_db, clean_job_id, *args, **kwargs):
        failing_db.add(CleanJobItemRecord(clean_job_id=None, raw_data_id=None, category_code=None))
        failing_db.flush()

    monkeypatch.setattr("app.api.clean.run_clean", fake_run_clean)

    response = client.post("/api/clean/tasks", json={
        "category_code": "router",
        "platform": "jd",
        "dispatch_batch_id": batch.id,
        "task_name": "路由器 第1批",
        "rules": {"dedup": True},
    })

    assert response.status_code == 500
    assert response.json()["detail"].startswith("创建清洗任务失败: ")
    job = db.query(CleanJobRecord).filter_by(task_name="路由器 第1批").one()
    assert job.status == "failed"
    assert db.query(CleanJobItemRecord).filter_by(clean_job_id=job.id).count() == 0
    pool_response = client.get(f"/api/clean/pool/summary?dispatch_batch_id={batch.id}")
    assert pool_response.status_code == 200
    assert pool_response.json()[0]["pending_count"] == 1


def test_create_clean_task_endpoint_marks_job_failed_when_run_match_raises(db, monkeypatch):
    client = _make_client(db, raise_server_exceptions=False)
    batch = _create_pending_router_dispatch(db, filename="router-match-fails.xlsx")

    def fake_run_match(failing_db, clean_job_id):
        failing_db.add(CleanJobItemRecord(clean_job_id=None, raw_data_id=None, category_code=None))
        failing_db.flush()

    monkeypatch.setattr("app.api.clean.run_match", fake_run_match)

    response = client.post("/api/clean/tasks", json={
        "category_code": "router",
        "platform": "jd",
        "dispatch_batch_id": batch.id,
        "task_name": "路由器 第1批",
        "rules": {"dedup": True},
    })

    assert response.status_code == 500
    assert response.json()["detail"].startswith("创建清洗任务失败: ")
    job = db.query(CleanJobRecord).filter_by(task_name="路由器 第1批").one()
    assert job.status == "failed"


def test_clean_job_snapshot_models_have_task_fields(db):
    file_record = UploadFileRecord(filename="router-snapshot.xlsx", platform="jd", row_count=1, status="done")
    db.add(file_record)
    db.flush()

    job = CleanJobRecord(
        file_ids=[],
        rules={"dedup": True},
        status="created",
        task_name="路由器 2026-06-14 第1批",
        category_code="router",
        platform="jd",
        source_scope={"dispatch_batch_ids": [1], "file_ids": [9]},
    )
    db.add(job)
    db.flush()

    raw = RawDataRecord(file_id=file_record.id, platform="jd", item_name="测试路由器", item_id="sku-1")
    db.add(raw)
    db.flush()

    item = CleanJobItemRecord(
        clean_job_id=job.id,
        raw_data_id=raw.id,
        category_code="router",
        platform="jd",
        dispatch_batch_id=1,
    )
    db.add(item)
    db.commit()

    saved = db.query(CleanJobRecord).filter_by(id=job.id).one()
    assert saved.task_name == "路由器 2026-06-14 第1批"
    assert saved.category_code == "router"
    assert saved.platform == "jd"
    assert saved.source_scope == {"dispatch_batch_ids": [1], "file_ids": [9]}

    saved_item = db.query(CleanJobItemRecord).filter_by(clean_job_id=job.id).one()
    assert saved_item.raw_data_id == raw.id
    assert saved_item.category_code == "router"
    assert saved_item.platform == "jd"
    assert saved_item.dispatch_batch_id == 1


def test_clean_pool_summary_batch_scope_counts_only_batch_pending_items(db):
    from app.services.clean_task_snapshot import get_clean_pool_summary

    category = Category(code="router", name="路由器")
    first_upload = UploadFileRecord(filename="router-batch-1.xlsx", platform="jd", row_count=1, status="done")
    second_upload = UploadFileRecord(filename="router-batch-2.xlsx", platform="jd", row_count=1, status="done")
    db.add_all([category, first_upload, second_upload])
    db.flush()

    first_raw = RawDataRecord(file_id=first_upload.id, platform="jd", item_id="sku-1", item_name="路由器1")
    second_raw = RawDataRecord(file_id=second_upload.id, platform="jd", item_id="sku-2", item_name="路由器2")
    db.add_all([first_raw, second_raw])
    db.flush()

    first_batch = DispatchBatch(file_id=first_upload.id, status="done", total_rows=1, dispatched_rows=1, unmatched_rows=0)
    second_batch = DispatchBatch(file_id=second_upload.id, status="done", total_rows=1, dispatched_rows=1, unmatched_rows=0)
    db.add_all([first_batch, second_batch])
    db.flush()

    db.add_all([
        DispatchItem(batch_id=first_batch.id, raw_data_id=first_raw.id, category_code="router"),
        DispatchItem(batch_id=second_batch.id, raw_data_id=second_raw.id, category_code="router"),
    ])
    db.flush()

    job = CleanJobRecord(
        file_ids=[first_upload.id],
        rules={"dedup": True},
        status="reviewing",
        task_name="路由器 第1批",
        category_code="router",
        platform="jd",
    )
    db.add(job)
    db.flush()
    db.add(CleanJobItemRecord(
        clean_job_id=job.id,
        raw_data_id=first_raw.id,
        category_code="router",
        platform="jd",
        dispatch_batch_id=first_batch.id,
    ))
    db.commit()

    first_batch_rows = get_clean_pool_summary(db, dispatch_batch_id=first_batch.id)
    second_batch_rows = get_clean_pool_summary(db, dispatch_batch_id=second_batch.id)
    global_rows = get_clean_pool_summary(db)

    assert first_batch_rows == [{
        "category_code": "router",
        "category_name": "路由器",
        "platform": "jd",
        "current_batch_count": 1,
        "pending_count": 0,
        "active_job_count": 1,
    }]
    assert second_batch_rows == [{
        "category_code": "router",
        "category_name": "路由器",
        "platform": "jd",
        "current_batch_count": 1,
        "pending_count": 1,
        "active_job_count": 1,
    }]
    assert global_rows[0]["pending_count"] == 1


def test_clean_pool_summary_counts_pending_items_and_active_jobs(db):
    from app.models.schemas import Category, CleanJobItemRecord
    from app.services.clean_task_snapshot import get_clean_pool_summary

    category = Category(code="router", name="路由器")
    upload = UploadFileRecord(filename="router.xlsx", platform="jd", row_count=2, status="done")
    db.add_all([category, upload])
    db.flush()

    first_raw = RawDataRecord(file_id=upload.id, platform="jd", item_id="sku-1", item_name="路由器1")
    second_raw = RawDataRecord(file_id=upload.id, platform="jd", item_id="sku-2", item_name="路由器2")
    db.add_all([first_raw, second_raw])
    db.flush()

    batch = DispatchBatch(file_id=upload.id, status="done", total_rows=2, dispatched_rows=2, unmatched_rows=0)
    db.add(batch)
    db.flush()

    db.add_all([
        DispatchItem(batch_id=batch.id, raw_data_id=first_raw.id, category_code="router"),
        DispatchItem(batch_id=batch.id, raw_data_id=second_raw.id, category_code="router"),
    ])
    db.flush()

    job = CleanJobRecord(
        file_ids=[upload.id],
        rules={"dedup": True},
        status="reviewing",
        task_name="路由器 第1批",
        category_code="router",
        platform=None,
    )
    db.add(job)
    db.flush()
    db.add(CleanJobItemRecord(
        clean_job_id=job.id,
        raw_data_id=first_raw.id,
        category_code="router",
        platform="jd",
        dispatch_batch_id=batch.id,
    ))
    db.commit()

    rows = get_clean_pool_summary(db, dispatch_batch_id=batch.id)

    assert rows == [{
        "category_code": "router",
        "category_name": "路由器",
        "platform": "jd",
        "current_batch_count": 2,
        "pending_count": 1,
        "active_job_count": 1,
    }]


def test_create_category_task_locks_only_pending_snapshot_rows(db):
    from app.models.schemas import CleanJobItemRecord
    from app.services.clean_task_snapshot import create_category_task_snapshot

    upload = UploadFileRecord(filename="router.xlsx", platform="jd", row_count=2, status="done")
    db.add(upload)
    db.flush()

    first_raw = RawDataRecord(file_id=upload.id, platform="jd", item_id="sku-1", item_name="路由器1")
    second_raw = RawDataRecord(file_id=upload.id, platform="jd", item_id="sku-2", item_name="路由器2")
    db.add_all([first_raw, second_raw])
    db.flush()

    batch = DispatchBatch(file_id=upload.id, status="done", total_rows=2, dispatched_rows=2, unmatched_rows=0)
    db.add(batch)
    db.flush()

    db.add_all([
        DispatchItem(batch_id=batch.id, raw_data_id=first_raw.id, category_code="router"),
        DispatchItem(batch_id=batch.id, raw_data_id=second_raw.id, category_code="router"),
    ])
    db.commit()

    job, snapshot_count = create_category_task_snapshot(
        db,
        category_code="router",
        platform="jd",
        dispatch_batch_id=batch.id,
        task_name="路由器 第1批",
        rules={"dedup": True},
    )
    db.commit()

    assert snapshot_count == 2
    assert job.task_name == "路由器 第1批"
    assert job.category_code == "router"
    assert job.platform == "jd"
    assert job.source_scope == {"dispatch_batch_ids": [batch.id], "file_ids": [upload.id]}

    snapshot_raw_ids = [
        item.raw_data_id
        for item in db.query(CleanJobItemRecord)
        .filter(CleanJobItemRecord.clean_job_id == job.id)
        .order_by(CleanJobItemRecord.raw_data_id)
        .all()
    ]
    assert snapshot_raw_ids == [first_raw.id, second_raw.id]

    later_raw = RawDataRecord(file_id=upload.id, platform="jd", item_id="sku-3", item_name="路由器3")
    db.add(later_raw)
    db.flush()
    db.add(DispatchItem(batch_id=batch.id, raw_data_id=later_raw.id, category_code="router"))
    db.commit()

    existing_snapshot_raw_ids = [
        item.raw_data_id
        for item in db.query(CleanJobItemRecord)
        .filter(CleanJobItemRecord.clean_job_id == job.id)
        .order_by(CleanJobItemRecord.raw_data_id)
        .all()
    ]
    assert existing_snapshot_raw_ids == [first_raw.id, second_raw.id]


def test_category_task_treats_duplicate_dispatch_rows_as_one_pending_item(db):
    from app.models.schemas import Category, CleanJobItemRecord
    from app.services.clean_task_snapshot import create_category_task_snapshot, get_clean_pool_summary

    category = Category(code="router", name="路由器")
    upload = UploadFileRecord(filename="router-duplicate.xlsx", platform="jd", row_count=1, status="done")
    db.add_all([category, upload])
    db.flush()

    raw = RawDataRecord(file_id=upload.id, platform="jd", item_id="sku-1", item_name="路由器1")
    db.add(raw)
    db.flush()

    first_batch = DispatchBatch(file_id=upload.id, status="done", total_rows=1, dispatched_rows=1, unmatched_rows=0)
    second_batch = DispatchBatch(file_id=upload.id, status="done", total_rows=1, dispatched_rows=1, unmatched_rows=0)
    db.add_all([first_batch, second_batch])
    db.flush()
    db.add_all([
        DispatchItem(batch_id=first_batch.id, raw_data_id=raw.id, category_code="router"),
        DispatchItem(batch_id=second_batch.id, raw_data_id=raw.id, category_code="router"),
    ])
    db.commit()

    rows = get_clean_pool_summary(db)
    assert len(rows) == 1
    assert rows[0]["current_batch_count"] == 1
    assert rows[0]["pending_count"] == 1

    job, snapshot_count = create_category_task_snapshot(
        db,
        category_code="router",
        platform="jd",
        dispatch_batch_id=None,
        task_name="路由器 第1批",
        rules={"dedup": True},
    )
    db.commit()

    assert snapshot_count == 1
    snapshot_items = db.query(CleanJobItemRecord).filter(CleanJobItemRecord.clean_job_id == job.id).all()
    assert len(snapshot_items) == 1
    assert snapshot_items[0].raw_data_id == raw.id
    assert snapshot_items[0].category_code == "router"
    assert snapshot_items[0].dispatch_batch_id == first_batch.id


def test_clean_pool_summary_counts_active_jobs_for_matching_platform_or_all_platform(db):
    from app.models.schemas import Category
    from app.services.clean_task_snapshot import get_clean_pool_summary

    category = Category(code="router", name="路由器")
    upload = UploadFileRecord(filename="router-platforms.xlsx", platform=None, row_count=2, status="done")
    db.add_all([category, upload])
    db.flush()

    jd_raw = RawDataRecord(file_id=upload.id, platform="jd", item_id="jd-sku", item_name="京东路由器")
    tmall_raw = RawDataRecord(file_id=upload.id, platform="tmall", item_id="tmall-sku", item_name="天猫路由器")
    db.add_all([jd_raw, tmall_raw])
    db.flush()

    batch = DispatchBatch(file_id=upload.id, status="done", total_rows=2, dispatched_rows=2, unmatched_rows=0)
    db.add(batch)
    db.flush()
    db.add_all([
        DispatchItem(batch_id=batch.id, raw_data_id=jd_raw.id, category_code="router"),
        DispatchItem(batch_id=batch.id, raw_data_id=tmall_raw.id, category_code="router"),
    ])
    db.flush()

    db.add_all([
        CleanJobRecord(
            file_ids=[upload.id],
            rules={"dedup": True},
            status="reviewing",
            task_name="京东路由器 第1批",
            category_code="router",
            platform="jd",
        ),
        CleanJobRecord(
            file_ids=[upload.id],
            rules={"dedup": True},
            status="reviewing",
            task_name="全平台路由器 第1批",
            category_code="router",
            platform=None,
        ),
    ])
    db.commit()

    rows = get_clean_pool_summary(db, dispatch_batch_id=batch.id)
    active_counts = {row["platform"]: row["active_job_count"] for row in rows}

    assert active_counts == {"jd": 2, "tmall": 1}


def test_clean_pool_summary_and_task_creation_handle_platform_aliases(db):
    from app.models.schemas import Category, CleanJobItemRecord
    from app.services.clean_task_snapshot import create_category_task_snapshot, get_clean_pool_summary

    category = Category(code="router", name="路由器")
    upload = UploadFileRecord(filename="router-aliases.xlsx", platform="京东", row_count=2, status="done")
    db.add_all([category, upload])
    db.flush()

    first_raw = RawDataRecord(file_id=upload.id, platform="JingDong", item_id="sku-1", item_name="路由器1")
    second_raw = RawDataRecord(file_id=upload.id, platform="京东", item_id="sku-2", item_name="路由器2")
    db.add_all([first_raw, second_raw])
    db.flush()

    batch = DispatchBatch(file_id=upload.id, status="done", total_rows=2, dispatched_rows=2, unmatched_rows=0)
    db.add(batch)
    db.flush()
    db.add_all([
        DispatchItem(batch_id=batch.id, raw_data_id=first_raw.id, category_code="router"),
        DispatchItem(batch_id=batch.id, raw_data_id=second_raw.id, category_code="router"),
    ])
    db.commit()

    rows = get_clean_pool_summary(db, dispatch_batch_id=batch.id)

    assert rows == [{
        "category_code": "router",
        "category_name": "路由器",
        "platform": "jd",
        "current_batch_count": 2,
        "pending_count": 2,
        "active_job_count": 0,
    }]

    job, snapshot_count = create_category_task_snapshot(
        db,
        category_code="router",
        platform="京东",
        dispatch_batch_id=batch.id,
        task_name="京东路由器 第1批",
        rules={"dedup": True},
    )
    db.commit()

    assert snapshot_count == 2
    assert job.platform == "jd"
    snapshot_platforms = [
        item.platform
        for item in db.query(CleanJobItemRecord)
        .filter(CleanJobItemRecord.clean_job_id == job.id)
        .order_by(CleanJobItemRecord.raw_data_id)
        .all()
    ]
    assert snapshot_platforms == ["jd", "jd"]
