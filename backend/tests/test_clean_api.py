from datetime import datetime

import pytest
from sqlalchemy import event

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.clean import router
from app.services.clean_task_snapshot import get_monthly_clean_pool
from app.models.database import get_db
from app.models.schemas import (
    Category,
    CleanJobItemRecord,
    CleanJobRecord,
    CleanedDataRecord,
    DispatchBatch,
    DispatchItem,
    FilteredItem,
    InterventionRule,
    ItemUrlMapping,
    MatchResult,
    MatchResultAttr,
    MatchResultCandidate,
    ModelRecord,
    PublishJob,
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


def test_list_clean_jobs_batches_category_lookup_for_same_category(db):
    client = _make_client(db)
    category = Category(code="soundbar", name="回音壁")
    db.add(category)
    db.flush()
    db.add_all([
        CleanJobRecord(
            file_ids=[],
            rules={"dedup": True},
            status="done",
            task_name=f"回音壁 / jd / {index}",
            category_code="soundbar",
            platform="jd",
            source_scope={"months": [202605]},
        )
        for index in range(3)
    ])
    db.commit()

    category_selects = 0

    def count_category_selects(conn, cursor, statement, parameters, context, executemany):
        nonlocal category_selects
        normalized = " ".join(statement.lower().split())
        if normalized.startswith("select") and " from categories " in normalized:
            category_selects += 1

    event.listen(db.bind, "before_cursor_execute", count_category_selects)
    try:
        response = client.get("/api/clean/jobs")
    finally:
        event.remove(db.bind, "before_cursor_execute", count_category_selects)

    assert response.status_code == 200
    assert len(response.json()) == 3
    assert category_selects == 1


def test_list_clean_jobs_applies_limit_before_serializing_jobs(db):
    client = _make_client(db)
    db.add_all([
        CleanJobRecord(
            file_ids=[],
            rules={"dedup": True},
            status="done",
            task_name=f"任务{index}",
            category_code="soundbar",
            platform="jd",
            source_scope={"months": [202605]},
            created_at=datetime(2026, 1, index + 1),
        )
        for index in range(3)
    ])
    db.commit()

    response = client.get("/api/clean/jobs", params={"limit": 2})

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 2
    assert [item["task_name"] for item in payload] == ["任务2", "任务1"]


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


def test_list_clean_jobs_includes_month_for_monthly_task(db):
    client = _make_client(db)
    job = CleanJobRecord(
        file_ids=[],
        rules={"dedup": True},
        status="reviewing",
        task_name="回音壁 / jd / 202605",
        category_code="soundbar",
        platform="jd",
        source_scope={"months": [202605], "platforms": ["jd"], "dispatch_batch_ids": [], "file_ids": []},
    )
    db.add(job)
    db.commit()

    response = client.get("/api/clean/jobs")

    assert response.status_code == 200
    jobs_by_id = {item["id"]: item for item in response.json()}
    assert jobs_by_id[job.id]["month"] == 202605


@pytest.mark.parametrize("source_scope", [
    {"months": [202605, 202606]},
    {"months": ["bad"]},
    {"months": None},
])
def test_list_clean_jobs_returns_no_month_for_malformed_source_scope(db, source_scope):
    client = _make_client(db)
    job = CleanJobRecord(
        file_ids=[],
        rules={"dedup": True},
        status="reviewing",
        task_name="回音壁 / jd / malformed",
        category_code="soundbar",
        platform="jd",
        source_scope=source_scope,
    )
    db.add(job)
    db.commit()

    response = client.get("/api/clean/jobs")

    assert response.status_code == 200
    jobs_by_id = {item["id"]: item for item in response.json()}
    assert jobs_by_id[job.id]["month"] is None


def test_list_clean_jobs_filters_active_and_archived_views(db):
    client = _make_client(db)
    active_job = CleanJobRecord(
        file_ids=[],
        rules={"dedup": True},
        status="done",
        task_name="活跃任务",
        category_code="camera",
        platform="jd",
        source_scope={"months": [202605]},
    )
    archived_job = CleanJobRecord(
        file_ids=[],
        rules={"dedup": True},
        status="archived",
        task_name="已删除任务",
        category_code="camera",
        platform="jd",
        source_scope={"months": [202605]},
    )
    db.add_all([active_job, archived_job])
    db.commit()

    active_response = client.get("/api/clean/jobs")
    assert active_response.status_code == 200
    assert [item["id"] for item in active_response.json()] == [active_job.id]

    archived_response = client.get("/api/clean/jobs", params={"view": "archived"})
    assert archived_response.status_code == 200
    archived_payload = archived_response.json()
    assert [item["id"] for item in archived_payload] == [archived_job.id]
    assert archived_payload[0]["status"] == "archived"

    all_response = client.get("/api/clean/jobs", params={"view": "all"})
    assert all_response.status_code == 200
    assert {item["id"] for item in all_response.json()} == {active_job.id, archived_job.id}


def test_delete_clean_job_archives_task_and_hides_from_default_list(db):
    client = _make_client(db)
    job = CleanJobRecord(
        file_ids=[],
        rules={"dedup": True},
        status="done",
        task_name="待删除任务",
        category_code="camera",
        platform="jd",
        source_scope={"months": [202605]},
    )
    db.add(job)
    db.commit()

    response = client.delete(f"/api/clean/jobs/{job.id}")

    assert response.status_code == 200
    assert response.json()["status"] == "archived"
    db.refresh(job)
    assert job.status == "archived"

    active_response = client.get("/api/clean/jobs")
    assert [item["id"] for item in active_response.json()] == []

    archived_response = client.get("/api/clean/jobs", params={"view": "archived"})
    assert [item["id"] for item in archived_response.json()] == [job.id]


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


def test_get_monthly_clean_pool_uses_category_scoped_query_when_limited(db):
    categories = [
        Category(code="action_cameras", name="运动相机"),
        Category(code="router", name="路由器"),
    ]
    upload = UploadFileRecord(filename="monthly-scoped-limit.xlsx", platform="jd", row_count=4, status="done")
    db.add_all([*categories, upload])
    db.flush()

    rows = [
        RawDataRecord(file_id=upload.id, platform="jd", month=202601, item_id="cam-1", item_name="相机1"),
        RawDataRecord(file_id=upload.id, platform="jd", month=202602, item_id="cam-2", item_name="相机2"),
        RawDataRecord(file_id=upload.id, platform="jd", month=202601, item_id="router-1", item_name="路由1"),
        RawDataRecord(file_id=upload.id, platform="jd", month=202602, item_id="router-2", item_name="路由2"),
    ]
    db.add_all(rows)
    db.flush()
    batch = DispatchBatch(file_id=upload.id, status="done", total_rows=4, dispatched_rows=4, unmatched_rows=0)
    db.add(batch)
    db.flush()
    db.add_all([
        DispatchItem(batch_id=batch.id, raw_data_id=rows[0].id, category_code="action_cameras"),
        DispatchItem(batch_id=batch.id, raw_data_id=rows[1].id, category_code="action_cameras"),
        DispatchItem(batch_id=batch.id, raw_data_id=rows[2].id, category_code="router"),
        DispatchItem(batch_id=batch.id, raw_data_id=rows[3].id, category_code="router"),
    ])
    db.commit()

    grouped_dispatch_queries = []

    def collect_grouped_queries(conn, cursor, statement, parameters, context, executemany):
        normalized = " ".join(statement.lower().split())
        if " from dispatch_items " in normalized and " group by " in normalized:
            grouped_dispatch_queries.append(normalized)

    event.listen(db.bind, "before_cursor_execute", collect_grouped_queries)
    try:
        result = get_monthly_clean_pool(db, limit=1)
    finally:
        event.remove(db.bind, "before_cursor_execute", collect_grouped_queries)

    assert [row["category_code"] for row in result] == ["action_cameras"]
    assert len(grouped_dispatch_queries) == 1
    assert "dispatch_items.category_code =" in grouped_dispatch_queries[0]



def test_get_monthly_clean_pool_applies_limit_before_returning_all_groups(db):
    client = _make_client(db)
    categories = [Category(code=f"cat{index}", name=f"品类{index}") for index in range(3)]
    upload = UploadFileRecord(filename="monthly-limit.xlsx", platform="jd", row_count=3, status="done")
    db.add_all([*categories, upload])
    db.flush()

    rows = [
        RawDataRecord(
            file_id=upload.id,
            platform="jd",
            month=202605 + index,
            item_id=f"item-{index}",
            item_name=f"商品{index}",
        )
        for index in range(3)
    ]
    db.add_all(rows)
    db.flush()
    batch = DispatchBatch(file_id=upload.id, status="done", total_rows=3, dispatched_rows=3, unmatched_rows=0)
    db.add(batch)
    db.flush()
    db.add_all([
        DispatchItem(batch_id=batch.id, raw_data_id=row.id, category_code=category.code)
        for row, category in zip(rows, categories)
    ])
    db.commit()

    response = client.get("/api/clean/pool/monthly", params={"limit": 2})

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 2
    assert [item["category_code"] for item in payload] == ["cat0", "cat1"]


def test_get_monthly_clean_pool_groups_pending_by_category_platform_month(db):
    client = _make_client(db)
    category = Category(code="soundbar", name="回音壁")
    upload = UploadFileRecord(filename="monthly-pool.xlsx", platform="jd", row_count=3, status="done")
    db.add_all([category, upload])
    db.flush()

    first = RawDataRecord(file_id=upload.id, platform="jd", month=202605, item_id="sb-1", item_name="索尼回音壁")
    second = RawDataRecord(file_id=upload.id, platform="京东", month=202605, item_id="sb-2", item_name="三星回音壁")
    third = RawDataRecord(file_id=upload.id, platform="jd", month=202606, item_id="sb-3", item_name="BOSE回音壁")
    db.add_all([first, second, third])
    db.flush()

    batch = DispatchBatch(file_id=upload.id, status="done", total_rows=3, dispatched_rows=3, unmatched_rows=0)
    db.add(batch)
    db.flush()
    db.add_all([
        DispatchItem(batch_id=batch.id, raw_data_id=first.id, category_code="soundbar"),
        DispatchItem(batch_id=batch.id, raw_data_id=second.id, category_code="soundbar"),
        DispatchItem(batch_id=batch.id, raw_data_id=third.id, category_code="soundbar"),
    ])
    db.commit()

    response = client.get("/api/clean/pool/monthly")

    assert response.status_code == 200
    assert response.json() == [
        {
            "category_code": "soundbar",
            "category_name": "回音壁",
            "platform": "jd",
            "month": 202605,
            "dispatched_count": 2,
            "pending_count": 2,
            "queued_count": 0,
            "existing_job_id": None,
            "existing_job_name": None,
            "existing_job_status": None,
        },
        {
            "category_code": "soundbar",
            "category_name": "回音壁",
            "platform": "jd",
            "month": 202606,
            "dispatched_count": 1,
            "pending_count": 1,
            "existing_job_id": None,
            "existing_job_name": None,
            "existing_job_status": None,
        },
    ]


def test_get_monthly_clean_pool_excludes_existing_snapshot_items_from_pending_count(db):
    client = _make_client(db)
    category = Category(code="soundbar", name="回音壁")
    upload = UploadFileRecord(filename="monthly-pending-exclusion.xlsx", platform="jd", row_count=2, status="done")
    db.add_all([category, upload])
    db.flush()

    first = RawDataRecord(file_id=upload.id, platform="jd", month=202605, item_id="sb-1", item_name="索尼回音壁")
    second = RawDataRecord(file_id=upload.id, platform="jd", month=202605, item_id="sb-2", item_name="三星回音壁")
    db.add_all([first, second])
    db.flush()

    batch = DispatchBatch(file_id=upload.id, status="done", total_rows=2, dispatched_rows=2, unmatched_rows=0)
    db.add(batch)
    db.flush()
    db.add_all([
        DispatchItem(batch_id=batch.id, raw_data_id=first.id, category_code="soundbar"),
        DispatchItem(batch_id=batch.id, raw_data_id=second.id, category_code="soundbar"),
    ])
    job = CleanJobRecord(
        file_ids=[],
        rules={"dedup": True},
        status="reviewing",
        task_name="回音壁 / 京东 / 202605",
        category_code="soundbar",
        platform="jd",
        source_scope={"months": [202605], "platforms": ["jd"], "dispatch_batch_ids": [], "file_ids": []},
    )
    db.add(job)
    db.flush()
    db.add(CleanJobItemRecord(
        clean_job_id=job.id,
        raw_data_id=first.id,
        category_code="soundbar",
        platform="jd",
        dispatch_batch_id=batch.id,
    ))
    db.commit()

    response = client.get("/api/clean/pool/monthly?category_code=soundbar&platform=jd&month=202605")

    assert response.status_code == 200
    assert response.json()[0]["pending_count"] == 1


def test_get_monthly_clean_pool_hides_scope_with_active_monthly_job(db):
    client = _make_client(db)
    category = Category(code="soundbar", name="回音壁")
    upload = UploadFileRecord(filename="monthly-existing.xlsx", platform="jd", row_count=1, status="done")
    db.add_all([category, upload])
    db.flush()

    raw = RawDataRecord(file_id=upload.id, platform="jd", month=202605, item_id="sb-1", item_name="索尼回音壁")
    db.add(raw)
    db.flush()
    batch = DispatchBatch(file_id=upload.id, status="done", total_rows=1, dispatched_rows=1, unmatched_rows=0)
    db.add(batch)
    db.flush()
    db.add(DispatchItem(batch_id=batch.id, raw_data_id=raw.id, category_code="soundbar"))
    job = CleanJobRecord(
        file_ids=[],
        rules={"dedup": True},
        status="reviewing",
        task_name="回音壁 / 京东 / 202605",
        category_code="soundbar",
        platform="jd",
        source_scope={"months": [202605], "platforms": ["jd"], "dispatch_batch_ids": [], "file_ids": []},
    )
    db.add(job)
    db.commit()

    response = client.get("/api/clean/pool/monthly?category_code=soundbar&platform=jd&month=202605")

    assert response.status_code == 200
    assert response.json() == []


def test_get_monthly_clean_pool_shows_scope_with_archived_monthly_job(db):
    client = _make_client(db)
    category = Category(code="soundbar", name="回音壁")
    upload = UploadFileRecord(filename="monthly-existing-alias.xlsx", platform="jd", row_count=1, status="done")
    db.add_all([category, upload])
    db.flush()

    raw = RawDataRecord(file_id=upload.id, platform="jd", month=202605, item_id="sb-1", item_name="索尼回音壁")
    db.add(raw)
    db.flush()
    batch = DispatchBatch(file_id=upload.id, status="done", total_rows=1, dispatched_rows=1, unmatched_rows=0)
    db.add(batch)
    db.flush()
    db.add(DispatchItem(batch_id=batch.id, raw_data_id=raw.id, category_code="soundbar"))
    job = CleanJobRecord(
        file_ids=[],
        rules={"dedup": True},
        status="archived",
        task_name="回音壁 / 京东 / 202605",
        category_code="soundbar",
        platform="jd",
        source_scope={"months": [202605], "platforms": ["jd"], "dispatch_batch_ids": [], "file_ids": []},
    )
    db.add(job)
    db.flush()
    db.add(CleanJobItemRecord(
        clean_job_id=job.id,
        raw_data_id=raw.id,
        category_code="soundbar",
        platform="jd",
        dispatch_batch_id=batch.id,
    ))
    db.commit()

    response = client.get("/api/clean/pool/monthly?category_code=soundbar&platform=jd&month=202605")

    assert response.status_code == 200
    assert response.json() == [
        {
            "category_code": "soundbar",
            "category_name": "回音壁",
            "platform": "jd",
            "month": 202605,
            "dispatched_count": 1,
            "pending_count": 0,
            "queued_count": 1,
            "existing_job_id": None,
            "existing_job_name": None,
            "existing_job_status": None,
        }
    ]


def test_monthly_pool_filter_supports_publish_warning_scope(db):
    client = _make_client(db)
    _create_monthly_pending_row(db, item_id="sb-1", month=202605)
    _create_monthly_pending_row(db, item_id="sb-2", month=202606)

    response = client.get("/api/clean/pool/monthly?category_code=soundbar&platform=jd&month=202605")

    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["month"] == 202605
    assert response.json()[0]["pending_count"] == 1


def test_monthly_pool_ignores_existing_job_with_malformed_month_scope(db):
    client = _make_client(db)
    _create_monthly_pending_row(db, item_id="sb-1", month=202605)
    job = CleanJobRecord(
        file_ids=[],
        rules={"dedup": True},
        status="reviewing",
        task_name="回音壁 / jd / malformed",
        category_code="soundbar",
        platform="jd",
        source_scope={"months": ["bad"], "platforms": ["jd"], "dispatch_batch_ids": [], "file_ids": []},
    )
    db.add(job)
    db.commit()

    response = client.get("/api/clean/pool/monthly?category_code=soundbar&platform=jd&month=202605")

    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["pending_count"] == 1
    assert response.json()[0]["existing_job_id"] is None


def test_upsert_monthly_clean_task_creates_new_monthly_task(db, monkeypatch):
    client = _make_client(db)
    _create_monthly_pending_row(db, item_id="sb-1")
    snapshot_calls = []

    def fake_upsert_monthly_task_snapshot(db_session, **kwargs):
        snapshot_calls.append(kwargs)
        job = CleanJobRecord(
            file_ids=[],
            rules={"dedup": True},
            status="reviewing",
            row_in=1,
            row_out=1,
            task_name="回音壁 / jd / 202605",
            category_code="soundbar",
            platform="jd",
            source_scope={"months": [202605], "platforms": ["jd"], "dispatch_batch_ids": [], "file_ids": []},
        )
        db_session.add(job)
        db_session.flush()
        return job, 1, "created", []

    monkeypatch.setattr("app.api.clean._run_clean_and_match_for_job", lambda *args, **kwargs: None)
    monkeypatch.setattr("app.api.clean.upsert_monthly_task_snapshot", fake_upsert_monthly_task_snapshot)

    response = client.post("/api/clean/tasks/upsert-monthly", json={
        "category_code": "soundbar",
        "platform": "jd",
        "month": 202605,
        "force_reclean": True,
    })

    assert response.status_code == 200
    payload = response.json()
    assert payload["action"] == "created"
    assert payload["snapshot_count"] == 1
    assert payload["match_status"] == "done"
    assert payload["job"]["task_name"] == "回音壁 / jd / 202605"
    assert payload["job"]["category_code"] == "soundbar"
    assert payload["job"]["platform"] == "jd"
    assert payload["job"]["source_scope"]["months"] == [202605]
    assert snapshot_calls and snapshot_calls[0]["force_reclean"] is True


def test_upsert_monthly_clean_task_appends_with_malformed_existing_scope_lists(db, monkeypatch):
    client = _make_client(db)
    first_raw, first_batch, first_upload = _create_monthly_pending_row(db, item_id="sb-1")
    job = CleanJobRecord(
        file_ids=[first_upload.id],
        rules={"dedup": True},
        status="reviewing",
        row_in=1,
        row_out=1,
        task_name="回音壁 / jd / 202605",
        category_code="soundbar",
        platform="jd",
        source_scope={"months": [202605], "platforms": "jd", "dispatch_batch_ids": None, "file_ids": [first_upload.id]},
    )
    db.add(job)
    db.flush()
    db.add(CleanJobItemRecord(clean_job_id=job.id, raw_data_id=first_raw.id, category_code="soundbar", platform="jd", dispatch_batch_id=first_batch.id))
    db.commit()

    _, second_batch, second_upload = _create_monthly_pending_row(db, item_id="sb-2")

    monkeypatch.setattr("app.api.clean.run_match", lambda match_db, clean_job_id, **kwargs: {"total": 2, "matched": 0})

    response = client.post("/api/clean/tasks/upsert-monthly", json={
        "category_code": "soundbar",
        "platform": "jd",
        "month": 202605,
    })

    assert response.status_code == 200
    payload = response.json()
    assert payload["action"] == "appended"
    assert payload["job"]["id"] == job.id
    assert payload["job"]["source_scope"]["months"] == [202605]
    assert payload["job"]["source_scope"]["platforms"] == ["jd"]
    assert payload["job"]["source_scope"]["dispatch_batch_ids"] == [second_batch.id]
    assert set(payload["job"]["source_scope"]["file_ids"]) == {first_upload.id, second_upload.id}



def test_upsert_monthly_clean_task_appends_skips_malformed_existing_scope_values(db, monkeypatch):
    client = _make_client(db)
    first_raw, first_batch, first_upload = _create_monthly_pending_row(db, item_id="sb-1")
    job = CleanJobRecord(
        file_ids=["bad"],
        rules={"dedup": True},
        status="reviewing",
        row_in=1,
        row_out=1,
        task_name="回音壁 / jd / 202605",
        category_code="soundbar",
        platform="jd",
        source_scope={
            "months": [202605, "bad"],
            "platforms": ["jd"],
            "dispatch_batch_ids": ["bad"],
            "file_ids": ["bad"],
        },
    )
    db.add(job)
    db.flush()
    db.add(CleanJobItemRecord(clean_job_id=job.id, raw_data_id=first_raw.id, category_code="soundbar", platform="jd", dispatch_batch_id=first_batch.id))
    db.commit()

    _, second_batch, second_upload = _create_monthly_pending_row(db, item_id="sb-2")

    monkeypatch.setattr("app.api.clean.run_clean", lambda *args, **kwargs: 2)
    monkeypatch.setattr("app.api.clean.run_match", lambda match_db, clean_job_id, **kwargs: {"total": 2, "matched": 0})

    response = client.post("/api/clean/tasks/upsert-monthly", json={
        "category_code": "soundbar",
        "platform": "jd",
        "month": 202605,
    })

    assert response.status_code == 200
    payload = response.json()
    assert payload["action"] == "appended"
    assert payload["job"]["source_scope"]["months"] == [202605]
    assert payload["job"]["source_scope"]["dispatch_batch_ids"] == [second_batch.id]
    assert payload["job"]["source_scope"]["file_ids"] == [second_upload.id]
    assert payload["job"]["file_ids"] == [second_upload.id]



def test_upsert_monthly_clean_task_restores_archived_monthly_task(db, monkeypatch):
    client = _make_client(db)
    raw, batch, upload = _create_monthly_pending_row(db, item_id="sb-1")
    job = CleanJobRecord(
        file_ids=[upload.id],
        rules={"dedup": True},
        status="archived",
        task_name="回音壁 / jd / 202605",
        category_code="soundbar",
        platform="jd",
        source_scope={"months": [202605], "platforms": ["jd"], "dispatch_batch_ids": [batch.id], "file_ids": [upload.id]},
    )
    db.add(job)
    db.flush()
    db.add(CleanJobItemRecord(
        clean_job_id=job.id,
        raw_data_id=raw.id,
        category_code="soundbar",
        platform="jd",
        dispatch_batch_id=batch.id,
    ))
    db.commit()

    monkeypatch.setattr("app.api.clean.run_clean", lambda *args, **kwargs: 1)
    monkeypatch.setattr("app.api.clean.run_match", lambda match_db, clean_job_id, **kwargs: {"total": 1, "matched": 0})

    response = client.post("/api/clean/tasks/upsert-monthly", json={
        "category_code": "soundbar",
        "platform": "jd",
        "month": 202605,
        "force_reclean": True,
    })

    assert response.status_code == 200
    payload = response.json()
    assert payload["action"] == "appended"
    assert payload["job"]["id"] == job.id
    assert payload["job"]["status"] == "reviewing"
    assert payload["snapshot_count"] == 1


def test_upsert_monthly_clean_task_appends_to_existing_task_and_reruns(db, monkeypatch):
    client = _make_client(db)
    first_raw, first_batch, first_upload = _create_monthly_pending_row(db, item_id="sb-1")
    job = CleanJobRecord(
        file_ids=[first_upload.id],
        rules={"dedup": True},
        status="reviewing",
        row_in=1,
        row_out=1,
        task_name="回音壁 / jd / 202605",
        category_code="soundbar",
        platform="jd",
        source_scope={"months": [202605], "platforms": ["jd"], "dispatch_batch_ids": [first_batch.id], "file_ids": [first_upload.id]},
    )
    db.add(job)
    db.flush()
    db.add(CleanJobItemRecord(clean_job_id=job.id, raw_data_id=first_raw.id, category_code="soundbar", platform="jd", dispatch_batch_id=first_batch.id))
    db.commit()

    _, second_batch, second_upload = _create_monthly_pending_row(db, item_id="sb-2")
    run_match_calls = []

    def fake_run_match(match_db, clean_job_id, **kwargs):
        run_match_calls.append(clean_job_id)
        return {"total": 2, "matched": 0}

    monkeypatch.setattr("app.api.clean.run_match", fake_run_match)

    response = client.post("/api/clean/tasks/upsert-monthly", json={
        "category_code": "soundbar",
        "platform": "jd",
        "month": 202605,
    })

    assert response.status_code == 200
    payload = response.json()
    assert payload["action"] == "appended"
    assert payload["snapshot_count"] == 1
    assert payload["job"]["id"] == job.id
    assert payload["job"]["status"] == "reviewing"
    assert set(payload["job"]["source_scope"]["dispatch_batch_ids"]) == {first_batch.id, second_batch.id}
    assert set(payload["job"]["source_scope"]["file_ids"]) == {first_upload.id, second_upload.id}
    assert db.query(CleanJobItemRecord).filter_by(clean_job_id=job.id).count() == 2
    assert db.query(CleanedDataRecord).filter_by(clean_job_id=job.id).count() == 2
    assert run_match_calls == [job.id]


@pytest.mark.parametrize(
    ("match_status", "extra_fields"),
    [
        ("confirmed", {"model_id": 1, "matched_by": "manual", "review_note": "已确认"}),
        ("excluded", {"disable_reason": "不属于分析范围", "is_disabled": 1}),
        ("disputed", {"dispute_reason": "型号不确定"}),
    ],
)
def test_upsert_monthly_clean_task_rejects_existing_review_state(db, match_status, extra_fields):
    client = _make_client(db)
    first_raw, first_batch, first_upload = _create_monthly_pending_row(db, item_id="sb-1")
    job = CleanJobRecord(
        file_ids=[first_upload.id],
        rules={"dedup": True},
        status="reviewing",
        row_in=1,
        row_out=1,
        task_name="回音壁 / jd / 202605",
        category_code="soundbar",
        platform="jd",
        source_scope={"months": [202605], "platforms": ["jd"], "dispatch_batch_ids": [first_batch.id], "file_ids": [first_upload.id]},
    )
    db.add(job)
    db.flush()
    db.add(CleanJobItemRecord(clean_job_id=job.id, raw_data_id=first_raw.id, category_code="soundbar", platform="jd", dispatch_batch_id=first_batch.id))
    db.add(MatchResult(clean_job_id=job.id, raw_data_id=first_raw.id, match_status=match_status, **extra_fields))
    db.commit()
    _create_monthly_pending_row(db, item_id="sb-2")

    response = client.post("/api/clean/tasks/upsert-monthly", json={
        "category_code": "soundbar",
        "platform": "jd",
        "month": 202605,
    })

    assert response.status_code == 400
    assert "已有人工处理或发布记录" in response.json()["detail"]
    assert db.query(CleanJobItemRecord).filter_by(clean_job_id=job.id).count() == 1


@pytest.mark.parametrize(
    "extra_fields",
    [
        {"is_disabled": 1},
        {"sales_coefficient": 0.8},
        {"dispute_reason": "原因待复核"},
        {"review_note": "人工备注"},
        {"reviewed_at": datetime.utcnow()},
    ],
)
def test_upsert_monthly_clean_task_rejects_existing_review_markers(db, extra_fields):
    client = _make_client(db)
    first_raw, first_batch, first_upload = _create_monthly_pending_row(db, item_id="sb-1")
    job = CleanJobRecord(
        file_ids=[first_upload.id],
        rules={"dedup": True},
        status="reviewing",
        row_in=1,
        row_out=1,
        task_name="回音壁 / jd / 202605",
        category_code="soundbar",
        platform="jd",
        source_scope={"months": [202605], "platforms": ["jd"], "dispatch_batch_ids": [first_batch.id], "file_ids": [first_upload.id]},
    )
    db.add(job)
    db.flush()
    db.add(CleanJobItemRecord(clean_job_id=job.id, raw_data_id=first_raw.id, category_code="soundbar", platform="jd", dispatch_batch_id=first_batch.id))
    db.add(MatchResult(clean_job_id=job.id, raw_data_id=first_raw.id, match_status="matched", **extra_fields))
    db.commit()
    _create_monthly_pending_row(db, item_id="sb-2")

    response = client.post("/api/clean/tasks/upsert-monthly", json={
        "category_code": "soundbar",
        "platform": "jd",
        "month": 202605,
    })

    assert response.status_code == 400
    assert "已有人工处理或发布记录" in response.json()["detail"]
    assert db.query(CleanJobItemRecord).filter_by(clean_job_id=job.id).count() == 1


def test_upsert_monthly_clean_task_rejects_existing_attrs(db):
    client = _make_client(db)
    first_raw, first_batch, first_upload = _create_monthly_pending_row(db, item_id="sb-1")
    job = CleanJobRecord(
        file_ids=[first_upload.id],
        rules={"dedup": True},
        status="reviewing",
        row_in=1,
        row_out=1,
        task_name="回音壁 / jd / 202605",
        category_code="soundbar",
        platform="jd",
        source_scope={"months": [202605], "platforms": ["jd"], "dispatch_batch_ids": [first_batch.id], "file_ids": [first_upload.id]},
    )
    db.add(job)
    db.flush()
    db.add(CleanJobItemRecord(clean_job_id=job.id, raw_data_id=first_raw.id, category_code="soundbar", platform="jd", dispatch_batch_id=first_batch.id))
    match_result = MatchResult(clean_job_id=job.id, raw_data_id=first_raw.id, match_status="matched")
    db.add(match_result)
    db.flush()
    db.add(MatchResultAttr(match_result_id=match_result.id, attr_name="尺寸", attr_value="65寸", rule_id=None))
    db.commit()
    _create_monthly_pending_row(db, item_id="sb-2")

    response = client.post("/api/clean/tasks/upsert-monthly", json={
        "category_code": "soundbar",
        "platform": "jd",
        "month": 202605,
    })

    assert response.status_code == 400
    assert "已有人工处理或发布记录" in response.json()["detail"]
    assert db.query(CleanJobItemRecord).filter_by(clean_job_id=job.id).count() == 1


def test_upsert_monthly_clean_task_rejects_existing_publish_history(db):
    client = _make_client(db)
    first_raw, first_batch, first_upload = _create_monthly_pending_row(db, item_id="sb-1")
    job = CleanJobRecord(
        file_ids=[first_upload.id],
        rules={"dedup": True},
        status="reviewing",
        row_in=1,
        row_out=1,
        task_name="回音壁 / jd / 202605",
        category_code="soundbar",
        platform="jd",
        source_scope={"months": [202605], "platforms": ["jd"], "dispatch_batch_ids": [first_batch.id], "file_ids": [first_upload.id]},
    )
    db.add(job)
    db.flush()
    db.add(CleanJobItemRecord(clean_job_id=job.id, raw_data_id=first_raw.id, category_code="soundbar", platform="jd", dispatch_batch_id=first_batch.id))
    db.add(PublishJob(clean_job_id=job.id, status="done", published_count=1))
    db.commit()
    _create_monthly_pending_row(db, item_id="sb-2")

    response = client.post("/api/clean/tasks/upsert-monthly", json={
        "category_code": "soundbar",
        "platform": "jd",
        "month": 202605,
    })

    assert response.status_code == 400
    assert "已有人工处理或发布记录" in response.json()["detail"]
    assert db.query(CleanJobItemRecord).filter_by(clean_job_id=job.id).count() == 1


@pytest.mark.parametrize("status", ["matching", "processing"])
def test_upsert_monthly_clean_task_rejects_processing_existing_task(db, status):
    client = _make_client(db)
    _create_monthly_pending_row(db, item_id="sb-1")
    job = CleanJobRecord(
        file_ids=[],
        rules={"dedup": True},
        status=status,
        task_name="回音壁 / jd / 202605",
        category_code="soundbar",
        platform="jd",
        source_scope={"months": [202605], "platforms": ["jd"], "dispatch_batch_ids": [], "file_ids": []},
    )
    db.add(job)
    db.commit()

    response = client.post("/api/clean/tasks/upsert-monthly", json={
        "category_code": "soundbar",
        "platform": "jd",
        "month": 202605,
    })

    assert response.status_code == 400
    assert "不能追加" in response.json()["detail"]


def test_run_match_rerun_clears_old_match_attrs(db, monkeypatch):
    from app.services.matcher import run_match

    upload = UploadFileRecord(filename="matcher-rerun.xlsx", platform="jd", row_count=1, status="done")
    db.add(upload)
    db.flush()
    raw = RawDataRecord(file_id=upload.id, platform="jd", month=202605, item_id="sb-1", item_name="未匹配回音壁")
    job = CleanJobRecord(file_ids=[upload.id], rules={"dedup": True}, status="reviewing", row_in=1, row_out=1)
    db.add_all([raw, job])
    db.flush()
    cleaned = CleanedDataRecord(clean_job_id=job.id, raw_data_id=raw.id, platform="jd", month=202605, item_id="sb-1", item_name="未匹配回音壁")
    old_match = MatchResult(clean_job_id=job.id, raw_data_id=raw.id, match_status="matched", matched_by="auto", model_id=1)
    db.add_all([cleaned, old_match])
    db.flush()
    old_match_id = old_match.id
    db.add(MatchResultAttr(match_result_id=old_match_id, attr_name="尺寸", attr_value="旧", rule_id=None))
    db.commit()

    monkeypatch.setattr("app.services.matcher.audit_price", lambda match_db, match_result_ids, commit=True: {"audited": 0})

    result = run_match(db, job.id)

    assert result["total"] == 1
    assert db.query(MatchResultAttr).filter_by(match_result_id=old_match_id).count() == 0


def test_upsert_monthly_clean_task_clears_old_filtered_items_on_rerun(db, monkeypatch):
    client = _make_client(db)
    first_raw, first_batch, first_upload = _create_monthly_pending_row(db, item_id="sb-1")
    job = CleanJobRecord(
        file_ids=[first_upload.id],
        rules={"dedup": True},
        status="reviewing",
        row_in=1,
        row_out=1,
        task_name="回音壁 / jd / 202605",
        category_code="soundbar",
        platform="jd",
        source_scope={"months": [202605], "platforms": ["jd"], "dispatch_batch_ids": [first_batch.id], "file_ids": [first_upload.id]},
    )
    db.add(job)
    db.flush()
    db.add_all([
        CleanJobItemRecord(clean_job_id=job.id, raw_data_id=first_raw.id, category_code="soundbar", platform="jd", dispatch_batch_id=first_batch.id),
        FilteredItem(clean_job_id=job.id, raw_data_id=first_raw.id, matched_keyword="stale"),
    ])
    db.commit()
    _create_monthly_pending_row(db, item_id="sb-2")

    monkeypatch.setattr("app.api.clean.run_match", lambda match_db, clean_job_id, **kwargs: {"total": 2, "matched": 0})

    response = client.post("/api/clean/tasks/upsert-monthly", json={
        "category_code": "soundbar",
        "platform": "jd",
        "month": 202605,
    })

    assert response.status_code == 200
    assert db.query(FilteredItem).filter_by(clean_job_id=job.id).count() == 0


def test_run_match_commit_false_passes_commit_false_to_audit_price(db, monkeypatch):
    from app.services.matcher import run_match

    model = ModelRecord(brand_code="SONY", model_code="HTA9", brand_name="索尼", model_name="HT-A9", category_code="soundbar")
    upload = UploadFileRecord(filename="audit-commit-false.xlsx", platform="jd", row_count=1, status="done")
    db.add_all([model, upload])
    db.flush()
    raw = RawDataRecord(file_id=upload.id, platform="jd", month=202605, item_id="sb-1", item_name="索尼 HTA9 回音壁", brand_raw="SONY")
    job = CleanJobRecord(file_ids=[upload.id], rules={"dedup": True}, status="reviewing", row_in=1, row_out=1)
    db.add_all([raw, job])
    db.flush()
    db.add(CleanedDataRecord(clean_job_id=job.id, raw_data_id=raw.id, platform="jd", month=202605, item_id="sb-1", item_name="索尼 HTA9 回音壁", brand_raw="SONY"))
    db.commit()
    audit_calls = []

    def fake_audit_price(match_db, match_result_ids, commit=True):
        audit_calls.append((list(match_result_ids), commit))
        return {"audited": len(match_result_ids)}

    monkeypatch.setattr("app.services.matcher.audit_price", fake_audit_price)

    result = run_match(db, job.id, commit=False)

    assert result["matched"] == 1
    assert len(audit_calls) == 1
    assert audit_calls[0][1] is False


def test_upsert_monthly_clean_task_preserves_existing_rules_when_not_provided(db, monkeypatch):
    client = _make_client(db)
    first_raw, first_batch, first_upload = _create_monthly_pending_row(db, item_id="sb-1")
    custom_rules = {"dedup": False, "custom": "keep"}
    job = CleanJobRecord(
        file_ids=[first_upload.id],
        rules=custom_rules,
        status="reviewing",
        row_in=1,
        row_out=1,
        task_name="回音壁 / jd / 202605",
        category_code="soundbar",
        platform="jd",
        source_scope={"months": [202605], "platforms": ["jd"], "dispatch_batch_ids": [first_batch.id], "file_ids": [first_upload.id]},
    )
    db.add(job)
    db.flush()
    db.add(CleanJobItemRecord(clean_job_id=job.id, raw_data_id=first_raw.id, category_code="soundbar", platform="jd", dispatch_batch_id=first_batch.id))
    db.commit()
    _create_monthly_pending_row(db, item_id="sb-2")

    monkeypatch.setattr("app.api.clean.run_match", lambda match_db, clean_job_id, **kwargs: {"total": 2, "matched": 0})

    response = client.post("/api/clean/tasks/upsert-monthly", json={
        "category_code": "soundbar",
        "platform": "jd",
        "month": 202605,
    })

    assert response.status_code == 200
    assert response.json()["job"]["rules"] == custom_rules
    db.refresh(job)
    assert job.rules == custom_rules


def test_rerun_with_current_rules_rejects_published_job(db):
    client = _make_client(db)
    job = CleanJobRecord(file_ids=[], status="published", row_in=1, row_out=1)
    db.add(job)
    db.flush()
    db.add(PublishJob(clean_job_id=job.id, status="done", published_count=1))
    db.commit()

    response = client.post(f"/api/clean/tasks/{job.id}/rerun-with-current-rules")

    assert response.status_code == 400
    assert response.json()["detail"] == "已发布任务不支持重新处理"


def test_rerun_with_current_rules_filters_rows_and_restores_manual_confirm(db):
    client = _make_client(db)
    category = Category(code="projector", name="投影仪")
    model = ModelRecord(brand_code="SONY", model_code="PX1", category_code="projector")
    upload = UploadFileRecord(filename="rerun.xlsx", platform="jd", status="done")
    db.add_all([category, model, upload])
    db.flush()
    job = CleanJobRecord(
        file_ids=[upload.id],
        rules={"dedup": True},
        status="reviewing",
        row_in=2,
        row_out=2,
        category_code="projector",
        dispatch_category_code="projector",
    )
    db.add(job)
    db.flush()
    keep_raw = RawDataRecord(file_id=upload.id, platform="jd", item_id="keep-1", item_url="https://item.jd.com/keep-1.html", item_name="索尼投影仪 PX1", brand_raw="SONY")
    filter_raw = RawDataRecord(file_id=upload.id, platform="jd", item_id="filter-1", item_url="https://item.jd.com/filter-1.html", item_name="投影仪支架", brand_raw="配件")
    db.add_all([keep_raw, filter_raw])
    db.flush()
    db.add_all([
        CleanJobItemRecord(clean_job_id=job.id, raw_data_id=keep_raw.id, category_code="projector"),
        CleanJobItemRecord(clean_job_id=job.id, raw_data_id=filter_raw.id, category_code="projector"),
        CleanedDataRecord(clean_job_id=job.id, raw_data_id=keep_raw.id, platform="jd", item_id="keep-1", item_name="索尼投影仪 PX1", brand_raw="SONY"),
        CleanedDataRecord(clean_job_id=job.id, raw_data_id=filter_raw.id, platform="jd", item_id="filter-1", item_name="投影仪支架", brand_raw="配件"),
        MatchResult(clean_job_id=job.id, raw_data_id=keep_raw.id, model_id=model.id, match_status="confirmed", matched_by="manual", match_source="manual"),
        MatchResult(clean_job_id=job.id, raw_data_id=filter_raw.id, match_status="pending"),
        InterventionRule(name="配件过滤", category_code="projector", action="filter", priority=10, conditions={"item_name_contains_any": ["支架"]}),
    ])
    db.commit()

    response = client.post(f"/api/clean/tasks/{job.id}/rerun-with-current-rules")

    assert response.status_code == 200
    body = response.json()
    assert body["row_out"] == 1
    assert body["filtered_count"] == 1
    assert body["restored_confirmed_count"] == 1
    assert body["pending_count"] == 0
    assert db.query(FilteredItem).filter_by(clean_job_id=job.id).count() == 1
    restored = db.query(MatchResult).filter_by(clean_job_id=job.id, raw_data_id=keep_raw.id).one()
    assert restored.match_status == "confirmed"
    assert restored.model_id == model.id
    assert restored.matched_by == "manual"
    assert db.query(ItemUrlMapping).filter_by(platform="jd", item_id="keep-1").one().model_id == model.id


def test_rerun_with_current_rules_restores_manual_excluded_row(db):
    client = _make_client(db)
    category = Category(code="camera", name="摄像机")
    upload = UploadFileRecord(filename="rerun-excluded.xlsx", platform="jd", status="done")
    db.add_all([category, upload])
    db.flush()
    job = CleanJobRecord(
        file_ids=[upload.id],
        rules={"dedup": True},
        status="reviewing",
        row_in=1,
        row_out=1,
        category_code="camera",
        dispatch_category_code="camera",
    )
    db.add(job)
    db.flush()
    raw = RawDataRecord(
        file_id=upload.id,
        platform="jd",
        item_id="excluded-1",
        item_url="https://item.jd.com/excluded-1.html",
        item_name="需要人工排除的摄像机",
        brand_raw="UNKNOWN",
    )
    db.add(raw)
    db.flush()
    reviewed_at = datetime(2026, 6, 1, 2, 3, 4)
    db.add_all([
        CleanJobItemRecord(clean_job_id=job.id, raw_data_id=raw.id, category_code="camera"),
        CleanedDataRecord(
            clean_job_id=job.id,
            raw_data_id=raw.id,
            platform="jd",
            item_id="excluded-1",
            item_url="https://item.jd.com/excluded-1.html",
            item_name="需要人工排除的摄像机",
            brand_raw="UNKNOWN",
        ),
        MatchResult(
            clean_job_id=job.id,
            raw_data_id=raw.id,
            match_status="excluded",
            matched_by="manual",
            match_source="manual",
            reviewed_at=reviewed_at,
            review_note="不属于本品类",
        ),
    ])
    db.commit()

    response = client.post(f"/api/clean/tasks/{job.id}/rerun-with-current-rules")

    assert response.status_code == 200
    body = response.json()
    assert body["restored_confirmed_count"] == 0
    assert body["restored_review_count"] == 1
    assert body["pending_count"] == 0
    restored = db.query(MatchResult).filter_by(clean_job_id=job.id, raw_data_id=raw.id).one()
    assert restored.match_status == "excluded"
    assert restored.model_id is None
    assert restored.matched_by == "manual"
    assert restored.match_source == "manual"
    assert restored.review_note == "不属于本品类"
    assert restored.reviewed_at == reviewed_at
    assert db.query(ItemUrlMapping).filter_by(platform="jd", item_id="excluded-1").first() is None


def test_rerun_with_current_rules_restores_manual_metadata_over_same_url_match(db):
    client = _make_client(db)
    category = Category(code="projector", name="投影仪")
    model = ModelRecord(brand_code="SONY", model_code="PX1", category_code="projector")
    upload = UploadFileRecord(filename="rerun-url.xlsx", platform="jd", status="done")
    db.add_all([category, model, upload])
    db.flush()
    job = CleanJobRecord(
        file_ids=[upload.id],
        rules={"dedup": True},
        status="reviewing",
        row_in=1,
        row_out=1,
        category_code="projector",
        dispatch_category_code="projector",
    )
    db.add(job)
    db.flush()
    raw = RawDataRecord(
        file_id=upload.id,
        platform="jd",
        item_id="url-1",
        item_url="https://item.jd.com/url-1.html",
        item_name="索尼投影仪 PX1",
        brand_raw="SONY",
    )
    db.add(raw)
    db.flush()
    reviewed_at = datetime(2026, 6, 1, 2, 3, 4)
    db.add_all([
        CleanJobItemRecord(clean_job_id=job.id, raw_data_id=raw.id, category_code="projector"),
        CleanedDataRecord(
            clean_job_id=job.id,
            raw_data_id=raw.id,
            platform="jd",
            item_id="url-1",
            item_url="https://item.jd.com/url-1.html",
            item_name="索尼投影仪 PX1",
            brand_raw="SONY",
        ),
        ItemUrlMapping(
            platform="jd",
            item_id="url-1",
            item_url="https://item.jd.com/url-1.html",
            model_id=model.id,
            brand_code="SONY",
            source="match_confirm",
        ),
        MatchResult(
            clean_job_id=job.id,
            raw_data_id=raw.id,
            model_id=model.id,
            match_status="confirmed",
            matched_by="manual",
            match_source="manual",
            reviewed_at=reviewed_at,
            review_note="人工确认保留",
        ),
    ])
    db.commit()

    response = client.post(f"/api/clean/tasks/{job.id}/rerun-with-current-rules")

    assert response.status_code == 200
    body = response.json()
    assert body["restored_confirmed_count"] == 1
    assert body["matched_count"] == 1
    assert body["pending_count"] == 0
    restored = db.query(MatchResult).filter_by(clean_job_id=job.id, raw_data_id=raw.id).one()
    assert restored.match_status == "confirmed"
    assert restored.model_id == model.id
    assert restored.matched_by == "manual"
    assert restored.match_source == "manual"
    assert restored.review_note == "人工确认保留"
    assert restored.reviewed_at == reviewed_at
    mapping = db.query(ItemUrlMapping).filter_by(platform="jd", item_id="url-1").one()
    assert mapping.model_id == model.id
    assert mapping.source == "match_confirm"


def test_upsert_monthly_clean_task_rejects_blank_platform(db):
    client = _make_client(db)

    response = client.post("/api/clean/tasks/upsert-monthly", json={
        "category_code": "soundbar",
        "platform": "   ",
        "month": 202605,
    })

    assert response.status_code == 422


def test_upsert_monthly_clean_task_rejects_invalid_month(db):
    client = _make_client(db)

    response = client.post("/api/clean/tasks/upsert-monthly", json={
        "category_code": "soundbar",
        "platform": "jd",
        "month": 202613,
    })

    assert response.status_code == 422


def test_upsert_monthly_clean_task_rolls_back_failed_rerun_and_allows_retry(db, monkeypatch):
    client = _make_client(db, raise_server_exceptions=False)
    _create_monthly_pending_row(db, item_id="sb-1")

    def failing_run_clean(*args, **kwargs):
        raise RuntimeError("clean failed")

    monkeypatch.setattr("app.api.clean.run_clean", failing_run_clean)

    response = client.post("/api/clean/tasks/upsert-monthly", json={
        "category_code": "soundbar",
        "platform": "jd",
        "month": 202605,
    })

    assert response.status_code == 500
    assert db.query(CleanJobRecord).filter_by(category_code="soundbar", platform="jd").count() == 0
    assert db.query(CleanJobItemRecord).filter_by(category_code="soundbar", platform="jd").count() == 0
    assert db.query(CleanedDataRecord).count() == 0
    assert db.query(MatchResult).count() == 0

    monkeypatch.setattr("app.api.clean.run_clean", lambda *args, **kwargs: 1)
    monkeypatch.setattr("app.api.clean.run_match", lambda match_db, clean_job_id, **kwargs: {"total": 1, "matched": 0})

    retry = client.post("/api/clean/tasks/upsert-monthly", json={
        "category_code": "soundbar",
        "platform": "jd",
        "month": 202605,
    })

    assert retry.status_code == 200
    assert retry.json()["action"] == "created"
    assert db.query(CleanJobRecord).filter_by(category_code="soundbar", platform="jd").count() == 1
    assert db.query(CleanJobItemRecord).filter_by(category_code="soundbar", platform="jd").count() == 1


def test_upsert_monthly_clean_task_clears_old_match_child_rows_on_rerun(db, monkeypatch):
    client = _make_client(db)
    first_raw, first_batch, first_upload = _create_monthly_pending_row(db, item_id="sb-1")
    job = CleanJobRecord(
        file_ids=[first_upload.id],
        rules={"dedup": True},
        status="reviewing",
        row_in=1,
        row_out=1,
        task_name="回音壁 / jd / 202605",
        category_code="soundbar",
        platform="jd",
        source_scope={"months": [202605], "platforms": ["jd"], "dispatch_batch_ids": [first_batch.id], "file_ids": [first_upload.id]},
    )
    db.add(job)
    db.flush()
    db.add(CleanJobItemRecord(clean_job_id=job.id, raw_data_id=first_raw.id, category_code="soundbar", platform="jd", dispatch_batch_id=first_batch.id))
    old_cleaned = CleanedDataRecord(clean_job_id=job.id, raw_data_id=first_raw.id, item_id="old-cleaned")
    old_match = MatchResult(clean_job_id=job.id, raw_data_id=first_raw.id, match_status="matched", matched_by="auto", model_id=1)
    db.add_all([old_cleaned, old_match])
    db.flush()
    old_match_id = old_match.id
    db.add(MatchResultCandidate(match_result_id=old_match_id, model_id=1, match_source="s1", score=10, rank=1))
    db.commit()
    _create_monthly_pending_row(db, item_id="sb-2")

    monkeypatch.setattr("app.api.clean.run_match", lambda match_db, clean_job_id, **kwargs: {"total": 2, "matched": 0})

    response = client.post("/api/clean/tasks/upsert-monthly", json={
        "category_code": "soundbar",
        "platform": "jd",
        "month": 202605,
    })

    assert response.status_code == 200
    assert db.query(MatchResult).filter_by(id=old_match_id).count() == 0
    assert db.query(MatchResultCandidate).filter_by(match_result_id=old_match_id).count() == 0
    assert db.query(MatchResultAttr).filter_by(match_result_id=old_match_id).count() == 0
    remaining_match_ids = {row.id for row in db.query(MatchResult.id).all()}
    assert all(
        candidate.match_result_id in remaining_match_ids
        for candidate in db.query(MatchResultCandidate).all()
    )
    assert all(
        attr.match_result_id in remaining_match_ids
        for attr in db.query(MatchResultAttr).all()
    )


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

    def fake_run_match(match_db, clean_job_id, **kwargs):
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
