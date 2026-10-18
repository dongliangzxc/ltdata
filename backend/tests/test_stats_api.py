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
    CleanJobRecord,
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
        "category_code": "headphone", "category_name": "耳机", "platform": "jd",
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
