from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import stats_api
from app.api.stats_api import router
from app.core.auth_deps import require_admin
from app.core.permissions import is_admin_only_path
from app.models.database import Base, get_db
from app.models.schemas import (
    Category,
    CleanDuplicateRecord,
    CleanJobItemRecord,
    CleanJobRecord,
    DispatchBatch,
    DispatchItem,
    FilteredItem,
    ItemUrlMapping,
    MatchResult,
    PublishJob,
    RawDataRecord,
    UploadConfirmJob,
    UploadFileRecord,
    User,
)


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    try:
        yield sessionmaker(bind=engine)
    finally:
        Base.metadata.drop_all(engine)


@pytest.fixture
def client(session_factory, monkeypatch):
    app = FastAPI()
    app.include_router(router)

    def override_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    def refresh_sync():
        db = session_factory()
        try:
            stats_api._refresh_slow_counts(db)
        finally:
            db.close()
            stats_api._slow_count_cache["running"] = False

    monkeypatch.setattr(stats_api, "_slow_count_cache", {"values": {}, "computed_at": None, "running": False})
    monkeypatch.setattr(stats_api, "_refresh_slow_counts_in_background", refresh_sync)
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[require_admin] = lambda: User(username="admin", is_admin=1)
    return TestClient(app)


def _seed(db):
    # 2026-09-30 20:00 UTC 是北京时间 10 月，用于校验按北京时间分月
    upload = UploadFileRecord(filename="a.xlsx", platform="jd", row_count=3, status="done",
                              uploaded_at=datetime(2026, 9, 30, 20, 0))
    db.add(upload)
    db.add(UploadFileRecord(filename="b.xlsx", row_count=99, status="error",
                            uploaded_at=datetime(2026, 9, 1)))
    db.flush()
    db.add_all([RawDataRecord(file_id=upload.id, item_id=str(i)) for i in range(3)])
    db.add(UploadConfirmJob(status="done", inserted_rows=3, skipped_rows=2))
    db.add(Category(code="headphone", name="耳机"))

    finished = CleanJobRecord(status="reviewing", category_code="headphone", platform="jd",
                              row_in=10, row_out=8, row_filtered=2, created_at=datetime(2026, 9, 10))
    pending = CleanJobRecord(status="done", category_code="headphone", platform="jd",
                             row_in=5, row_out=5, created_at=datetime(2026, 9, 11))
    failed = CleanJobRecord(status="failed", category_code="camera", row_in=1, created_at=datetime(2026, 9, 12))
    archived = CleanJobRecord(status="archived", category_code="headphone", row_in=100,
                              created_at=datetime(2026, 9, 13))
    db.add_all([finished, pending, failed, archived])
    db.flush()

    db.add_all([
        MatchResult(clean_job_id=finished.id, raw_data_id=1, match_status="url_matched",
                    matched_by="auto", match_source="s0"),
        MatchResult(clean_job_id=finished.id, raw_data_id=2, match_status="confirmed",
                    matched_by="manual", match_source="manual", reviewed_at=datetime(2026, 10, 2)),
        MatchResult(clean_job_id=finished.id, raw_data_id=3, match_status="disputed"),
        MatchResult(clean_job_id=pending.id, raw_data_id=1, match_status="matched",
                    matched_by="auto", match_source="s1"),
        MatchResult(clean_job_id=pending.id, raw_data_id=3, match_status="text_only", match_source="s1"),
        MatchResult(clean_job_id=pending.id, raw_data_id=2, match_status="pending", is_disabled=1),
        MatchResult(clean_job_id=archived.id, raw_data_id=1, match_status="url_matched", match_source="s0"),
    ])
    db.add_all([
        PublishJob(clean_job_id=finished.id, status="done", published_count=2),
        PublishJob(clean_job_id=finished.id, status="done", published_count=2),
        PublishJob(clean_job_id=archived.id, status="done", published_count=50),
    ])
    db.add_all([
        ItemUrlMapping(platform="jd", item_id="1", model_id=1, source="url_import"),
        ItemUrlMapping(platform="jd", item_id="2", source="url_import"),
        ItemUrlMapping(platform="jd", item_id="3", model_id=2, source="match_confirm"),
    ])
    db.add(User(username="u1", hashed_password="x", is_active=1, last_login_at=datetime.utcnow()))
    db.add(User(username="u2", hashed_password="x", is_active=0))
    db.commit()


def test_stats_path_is_admin_only():
    assert is_admin_only_path("/api/stats/overview")
    assert is_admin_only_path("/api/users")
    assert not is_admin_only_path("/api/clean/jobs")


def test_stats_overview_aggregates(client, session_factory):
    db = session_factory()
    _seed(db)
    db.close()

    res = client.get("/api/stats/overview")
    assert res.status_code == 200
    first = res.json()["data"]
    # 慢计数首次请求只触发后台刷新，结果为 None；刷新完成后的请求读取缓存
    assert first["upload"]["raw_rows"] is None
    assert first["slow_counts_at"] is None

    data = client.get("/api/stats/overview").json()["data"]
    assert data["slow_counts_at"] is not None
    assert data["assets"]["historical_mappings"] == 0

    assert data["upload"]["file_count"] == 1
    assert data["upload"]["file_rows"] == 3
    assert data["upload"]["raw_rows"] == 3
    assert data["upload"]["dedup_skipped_rows"] == 2

    clean = data["clean"]
    assert clean["task_total"] == 3
    # finished 只剩 disputed（不计入任务待处理），pending 任务有 text_only + 干扰过滤的 pending
    assert clean["clean_finished"] == 1
    assert clean["has_pending"] == 1
    assert clean["failed"] == 1
    assert clean["archived"] == 1
    assert clean["row_in"] == 16
    assert clean["published_tasks"] == 1
    assert clean["published_rows"] == 4

    match = data["match"]
    assert match["total"] == 5
    assert match["url_matched"] == 1
    assert match["matched"] == 1
    assert match["confirmed"] == 1
    assert match["publishable"] == 3
    assert match["publishable_distinct"] == 2
    assert match["actionable"] == 2
    assert match["auto_matched"] == 2

    headphone = next(c for c in data["categories"] if c["category_code"] == "headphone")
    assert headphone == {
        "category_code": "headphone", "category_name": "耳机", "platform": "jd", "month": "2026-09",
        "tasks": 2, "total": 5, "publishable": 3, "url_matched": 1, "actionable": 2,
    }

    monthly = {m["month"]: m for m in data["monthly"]}
    assert monthly["2026-10"]["upload_files"] == 1
    assert monthly["2026-10"]["manual_reviewed"] == 1
    assert monthly["2026-09"]["tasks_created"] == 3
    assert monthly["2026-09"]["upload_files"] == 0

    assets = data["assets"]
    assert assets["url_mappings"] == 3
    assert assets["url_mappings_with_model"] == 2
    assert assets["users"] == 2
    assert assets["active_users"] == 1
    assert assets["login_users_30d"] == 1


def test_progress_stats_uses_latest_done_batch(client, session_factory):
    db = session_factory()
    upload = UploadFileRecord(filename="p.xlsx", platform="jd", row_count=3, status="done")
    db.add(upload)
    db.flush()
    raw = [
        RawDataRecord(file_id=upload.id, item_id=str(i), platform="JD")
        for i in range(3)
    ]
    raw[0].month = 202609
    raw[1].month = 202609
    raw[2].month = 202608
    db.add_all(raw)
    db.add(Category(code="headphone", name="耳机"))
    db.add(Category(code="camera", name="相机"))
    db.flush()

    done_batch = DispatchBatch(file_id=upload.id, status="done", total_rows=3, dispatched_rows=3)
    db.add(done_batch)
    db.flush()
    db.add_all([
        DispatchItem(batch_id=done_batch.id, raw_data_id=raw[0].id, category_code="headphone"),
        DispatchItem(batch_id=done_batch.id, raw_data_id=raw[1].id, category_code="headphone"),
        DispatchItem(batch_id=done_batch.id, raw_data_id=raw[2].id, category_code="camera"),
        # 新发起但未完成的分发批次不应被统计
        DispatchBatch(file_id=upload.id, status="running"),
    ])
    db.flush()

    job = CleanJobRecord(status="reviewing", category_code="headphone", platform="jd")
    db.add(job)
    db.flush()
    db.add_all([
        CleanJobItemRecord(clean_job_id=job.id, raw_data_id=raw[0].id, category_code="headphone",
                           platform="jd", dispatch_batch_id=done_batch.id),
        CleanJobItemRecord(clean_job_id=job.id, raw_data_id=raw[1].id, category_code="headphone",
                           platform="jd", dispatch_batch_id=done_batch.id),
        MatchResult(clean_job_id=job.id, raw_data_id=raw[0].id, match_status="url_matched"),
        MatchResult(clean_job_id=job.id, raw_data_id=raw[1].id, match_status="pending"),
    ])
    db.add(PublishJob(clean_job_id=job.id, status="done", published_count=1))
    db.commit()
    db.close()

    progress = client.get("/api/stats/overview").json()["data"]["progress"]
    assert progress["dispatchable"] == 3
    assert progress["processed"] == 1
    assert progress["matched"] == 1
    assert progress["pending"] == 1
    assert progress["published"] == 1

    by_month = {row["month"]: row for row in progress["months"]}
    assert by_month[202609]["dispatchable"] == 2
    assert by_month[202609]["processed"] == 1
    assert by_month[202609]["published"] == 1
    assert by_month[202608]["dispatchable"] == 1
    assert by_month[202608]["processed"] == 0

    # 慢计数刷新完成后可拿到每月上传入库行数
    progress = client.get("/api/stats/overview").json()["data"]["progress"]
    by_month = {row["month"]: row for row in progress["months"]}
    assert by_month[202609]["uploaded_rows"] == 2
    assert by_month[202608]["uploaded_rows"] == 1

    by_category = {
        (row["month"], row["category_code"], row["platform"]): row
        for row in progress["categories"]
    }
    assert by_category[(202609, "headphone", "jd")]["dispatched"] == 2
    assert by_category[(202609, "headphone", "jd")]["task_created"] == 2
    assert by_category[(202609, "headphone", "jd")]["task_count"] == 1
    assert by_category[(202609, "headphone", "jd")]["processed"] == 1
    assert by_category[(202609, "headphone", "jd")]["url_matched"] == 1
    assert by_category[(202609, "headphone", "jd")]["confirmed"] == 0
    assert by_category[(202609, "headphone", "jd")]["pending"] == 1
    assert by_category[(202609, "headphone", "jd")]["published"] == 1
    assert by_category[(202609, "headphone", "jd")]["last_processed_at"]
    assert by_category[(202608, "camera", "jd")]["dispatched"] == 1
    assert by_category[(202608, "camera", "jd")]["task_created"] == 0
    assert by_category[(202608, "camera", "jd")]["processed"] == 0


def test_progress_excludes_deleted_category_without_deleting_history(client, session_factory):
    db = session_factory()
    upload = UploadFileRecord(filename="deleted-category.xlsx", status="done", row_count=5)
    kept = Category(code="headphone", name="耳机")
    deleted = Category(code="77", name="已删除品类")
    db.add_all([upload, kept, deleted])
    db.flush()
    raw = [
        RawDataRecord(file_id=upload.id, item_id=str(i), platform=platform, month=month)
        for i, (month, platform) in enumerate([
            (202610, "jd"), (202610, "tmall"), (202609, "jd"),
            (202608, "jd"), (202610, "jd"),
        ])
    ]
    db.add_all(raw)
    db.flush()
    batch = DispatchBatch(file_id=upload.id, status="done")
    kept_job = CleanJobRecord(status="reviewing", category_code="headphone", platform="jd")
    deleted_job = CleanJobRecord(status="reviewing", category_code="77", platform="jd")
    # A legacy job may identify its category only through dispatch_category_code.
    published_only_job = CleanJobRecord(status="published", dispatch_category_code="77", platform="jd")
    db.add_all([batch, kept_job, deleted_job, published_only_job])
    db.flush()
    for index, code in [(0, "headphone"), (0, "77"), (1, "77"), (2, "77"), (4, "headphone")]:
        db.add(DispatchItem(batch_id=batch.id, raw_data_id=raw[index].id, category_code=code))
    for job, index, code in [
        (kept_job, 0, "headphone"), (deleted_job, 0, "77"),
        (deleted_job, 1, "77"), (published_only_job, 3, "77"),
    ]:
        db.add(CleanJobItemRecord(clean_job_id=job.id, raw_data_id=raw[index].id, category_code=code))
    db.add_all([
        MatchResult(clean_job_id=kept_job.id, raw_data_id=raw[0].id, match_status="url_matched"),
        MatchResult(clean_job_id=deleted_job.id, raw_data_id=raw[0].id, match_status="url_matched"),
        MatchResult(clean_job_id=deleted_job.id, raw_data_id=raw[1].id, match_status="pending"),
        PublishJob(clean_job_id=kept_job.id, status="done", published_count=1),
        PublishJob(clean_job_id=deleted_job.id, status="done", published_count=2),
        PublishJob(clean_job_id=published_only_job.id, status="done", published_count=7),
    ])
    db.commit()

    before = client.get("/api/stats/progress").json()["data"]["progress"]
    assert before["dispatchable"] == 5
    assert before["published"] == 10
    db.delete(deleted)
    db.commit()

    # Both stats endpoints must drop the deleted category, including publication-only
    # rows, without dropping the same raw item from the surviving category.
    for endpoint in ("/api/stats/progress", "/api/stats/overview"):
        progress = client.get(endpoint).json()["data"]["progress"]
        assert progress["dispatchable"] == 2
        assert progress["task_created"] == 1
        assert progress["task_count"] == 1
        assert progress["not_task_created"] == 1
        assert progress["processed"] == progress["url_matched"] == 1
        assert progress["not_processed"] == 1
        assert progress["pending"] == progress["task_no_result"] == 0
        assert progress["published"] == 1
        assert [row["category_code"] for row in progress["categories"]] == ["headphone"]
        assert [row["month"] for row in progress["months"]] == [202610]
        month = progress["months"][0]
        assert month["dispatchable"] == month["task_created"] + month["not_task_created"]
        assert month["dispatchable"] == month["processed"] + month["not_processed"]

    assert db.query(RawDataRecord).count() == 5
    assert db.query(DispatchItem).filter_by(category_code="77").count() == 3
    assert db.query(CleanJobItemRecord).filter_by(category_code="77").count() == 3
    assert db.query(PublishJob).count() == 3
    db.close()


def test_progress_includes_system_filters_once_and_respects_current_task(client, session_factory):
    db = session_factory()
    upload = UploadFileRecord(filename="filters.xlsx", status="done")
    camera = Category(code="camera", name="摄像头")
    db.add_all([upload, camera, Category(code="headphone", name="耳机")])
    db.flush()
    raw = [RawDataRecord(file_id=upload.id, item_id=str(i), platform="tmall" if i == 2 else "jd",
                         month=202609 if i == 5 else 202610) for i in range(9)]
    db.add_all(raw)
    db.flush()
    old_batch = DispatchBatch(file_id=upload.id, status="done")
    db.add(old_batch)
    db.flush()
    batch = DispatchBatch(file_id=upload.id, status="done")
    job = CleanJobRecord(status="reviewing", category_code="headphone", platform="jd")
    archived = CleanJobRecord(status="archived", category_code="headphone", platform="jd")
    stale_job = CleanJobRecord(status="reviewing", category_code="headphone", platform="jd")
    camera_job = CleanJobRecord(status="reviewing", category_code="camera", platform="jd")
    db.add_all([batch, job, archived, stale_job, camera_job])
    db.flush()
    db.add(DispatchItem(batch_id=old_batch.id, raw_data_id=raw[8].id, category_code="headphone"))
    for i in range(8):
        db.add(DispatchItem(batch_id=batch.id, raw_data_id=raw[i].id, category_code="headphone"))
        db.add(CleanJobItemRecord(clean_job_id=archived.id if i == 4 else job.id,
                                 raw_data_id=raw[i].id, category_code="headphone"))
    db.add(DispatchItem(batch_id=batch.id, raw_data_id=raw[0].id, category_code="camera"))
    db.add(CleanJobItemRecord(clean_job_id=camera_job.id, raw_data_id=raw[0].id, category_code="camera"))
    db.add_all([
        MatchResult(clean_job_id=job.id, raw_data_id=raw[0].id, match_status="url_matched"),
        MatchResult(clean_job_id=job.id, raw_data_id=raw[1].id, match_status="pending"),
        MatchResult(clean_job_id=job.id, raw_data_id=raw[5].id, match_status="pending", is_disabled=1),
        CleanDuplicateRecord(clean_job_id=job.id, raw_data_id=raw[6].id, kept_raw_data_id=raw[0].id,
                             dedup_basis="item_id_month_shop", dedup_key={"item_id": "0", "month": 202610}),
    ])
    # Include stale filters alongside live results, duplicates of one filter, a
    # recovered filter, archived/other-task filters, and an old-batch-only item.
    for owner, i, recovered in [
        (job, 0, 0), (job, 1, 0), (job, 2, 0), (job, 2, 0), (job, 3, 1),
        (archived, 4, 0), (job, 5, 0), (stale_job, 7, 0), (job, 8, 0), (camera_job, 0, 0),
    ]:
        db.add(FilteredItem(clean_job_id=owner.id, raw_data_id=raw[i].id, is_recovered=recovered,
                            created_at=datetime(2026, 11, 24, 1, 0)))
    db.commit()

    for endpoint in ("/api/stats/overview", "/api/stats/progress"):
        progress = client.get(endpoint).json()["data"]["progress"]
        assert progress["dispatchable"] == 9
        assert progress["task_created"] == 8
        assert progress["processed"] == 4
        assert progress["system_filtered"] == 3
        assert progress["url_matched"] == progress["matched"] == 1
        assert progress["confirmed"] == progress["excluded_ignored"] == 0
        assert progress["pending"] == 1
        assert progress["task_no_result"] == 3  # recovered, duplicate-only, other task
        assert progress["not_task_created"] == 1  # archived task
        assert progress["not_processed"] == 5
        months = {row["month"]: row for row in progress["months"]}
        assert months[202610]["system_filtered"] == 2
        assert months[202609]["system_filtered"] == 1
        camera_row = next(row for row in progress["categories"] if row["category_code"] == "camera")
        assert camera_row["processed"] == camera_row["system_filtered"] == 1
        assert camera_row["completed_at"] == "2026-11-24 09:00:00"
        for row in [progress, *progress["months"]]:
            assert row["processed"] == (row["url_matched"] + row["auto_matched"]
                                        + row["confirmed"] + row["excluded_ignored"] + row["system_filtered"])
            assert row["task_created"] == row["processed"] + row["pending"] + row["task_no_result"]
        for row in progress["categories"]:
            assert row["processed"] <= row["task_created"] <= row["dispatched"]

    # Deleted categories remain excluded even if all their rows were filtered.
    db.delete(camera)
    db.commit()
    progress = client.get("/api/stats/progress").json()["data"]["progress"]
    assert progress["dispatchable"] == 8
    assert progress["system_filtered"] == 2
    assert progress["processed"] == 3
    db.close()


def test_slow_counts_refresh_only_when_expired(client, monkeypatch):
    calls = []
    monkeypatch.setattr(stats_api, "_refresh_slow_counts_in_background", lambda: calls.append(1))

    client.get("/api/stats/overview")
    client.get("/api/stats/overview")
    # 刷新进行中不重复触发
    assert len(calls) == 1

    stats_api._slow_count_cache.update(
        values={"raw_rows": 7, "historical_mappings": 1}, computed_at=datetime.utcnow(), running=False,
    )
    data = client.get("/api/stats/overview").json()["data"]
    assert data["upload"]["raw_rows"] == 7
    assert len(calls) == 1

    stats_api._slow_count_cache["computed_at"] = datetime.utcnow() - stats_api.SLOW_COUNT_TTL * 2
    data = client.get("/api/stats/overview").json()["data"]
    # 过期时先返回旧值，同时触发后台刷新
    assert data["upload"]["raw_rows"] == 7
    assert len(calls) == 2
