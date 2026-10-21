import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.core.auth_deps import get_current_user
from app.models.database import get_db
from app.api.match_api import router as match_router
from app.models.schemas import (
    CleanJobRecord,
    CleanedDataRecord,
    MatchResult,
    ItemExclusion,
    DispatchItem,
    Category,
    RawDataRecord,
    UploadFileRecord,
)
from app.services.matcher import run_match


class _Admin:
    is_admin = 1
    category_permissions = None


@pytest.fixture()
def match_client(db):
    app = FastAPI()
    app.include_router(match_router)

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: _Admin()
    return TestClient(app)


def _seed_ignored_row(db, *, status="pending", name="需要稍后处理"):
    upload = UploadFileRecord(filename="ignore.xlsx", status="done")
    db.add(upload)
    db.flush()
    job = CleanJobRecord(file_ids=[upload.id], status="reviewing", row_in=1, row_out=1)
    db.add(job)
    db.flush()
    raw = RawDataRecord(
        file_id=upload.id,
        platform="jd",
        item_id=f"ignore-{name}",
        item_name=name,
        brand_raw="Sony",
    )
    db.add(raw)
    db.flush()
    cleaned = CleanedDataRecord(
        clean_job_id=job.id,
        raw_data_id=raw.id,
        platform="jd",
        item_name=name,
        brand_raw="Sony",
    )
    db.add(cleaned)
    db.flush()
    mr = MatchResult(
        clean_job_id=job.id,
        raw_data_id=raw.id,
        match_status=status,
        matched_by="auto",
    )
    db.add(mr)
    db.commit()
    return job, raw, mr


def test_ignore_is_task_local_and_can_be_reverted(db, match_client):
    job, _raw, mr = _seed_ignored_row(db)

    response = match_client.put(
        f"/api/match/confirm/{mr.id}",
        json={"ignored": True, "reason": "这次不处理"},
    )
    assert response.status_code == 200
    assert response.json()["match_status"] == "ignored"
    db.refresh(mr)
    assert mr.match_status == "ignored"
    assert mr.model_id is None
    assert db.query(ItemExclusion).count() == 0

    summary = match_client.get(f"/api/match/{job.id}/summary")
    assert summary.status_code == 200
    assert summary.json()["ignored"] == 1

    listed = match_client.get(
        f"/api/match/{job.id}/pending", params={"status": "ignored"}
    )
    assert listed.status_code == 200
    assert listed.json()["total"] == 1

    reverted = match_client.post(f"/api/match/items/{mr.id}/revert")
    assert reverted.status_code == 200
    assert reverted.json()["match_status"] == "pending"


def test_batch_ignore_ids_only_changes_current_job_rows(db, match_client):
    job, _raw, first = _seed_ignored_row(db, name="第一条")
    second = _seed_ignored_row(db, name="第二条")[2]
    # Keep the two rows in one task for a true batch request.
    second.clean_job_id = job.id
    db.commit()

    response = match_client.post(
        f"/api/match/{job.id}/batch-ignore",
        json={"mode": "ids", "ids": [first.id, second.id]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ignored"] == 2
    assert body["failed"] == 0
    assert db.get(MatchResult, first.id).match_status == "ignored"
    assert db.get(MatchResult, second.id).match_status == "ignored"


def test_batch_restore_ids_returns_ignored_rows_to_previous_state(db, match_client):
    job, _raw, first = _seed_ignored_row(db, name="恢复第一条")
    second = _seed_ignored_row(db, name="恢复第二条")[2]
    second.clean_job_id = job.id
    db.commit()

    ignored = match_client.post(
        f"/api/match/{job.id}/batch-ignore",
        json={"mode": "ids", "ids": [first.id, second.id]},
    )
    assert ignored.status_code == 200

    restored = match_client.post(
        f"/api/match/{job.id}/batch-restore",
        json={"mode": "ids", "ids": [first.id, second.id]},
    )
    assert restored.status_code == 200
    body = restored.json()
    assert body["restored"] == 2
    assert body["failed"] == 0
    db.refresh(first)
    db.refresh(second)
    assert first.match_status == "pending"
    assert second.match_status == "pending"
    assert first.prev_match_status is None


def test_batch_restore_filter_only_restores_ignored_rows(db, match_client):
    job, _raw, first = _seed_ignored_row(db, name="只恢复已忽略")
    second = _seed_ignored_row(db, name="保持待处理")[2]
    second.clean_job_id = job.id
    db.commit()

    ignored = match_client.post(
        f"/api/match/{job.id}/batch-ignore",
        json={"mode": "ids", "ids": [first.id]},
    )
    assert ignored.status_code == 200

    restored = match_client.post(
        f"/api/match/{job.id}/batch-restore",
        json={"mode": "filter", "filter": {"tab": "ignored"}},
    )
    assert restored.status_code == 200
    assert restored.json()["restored"] == 1
    assert db.get(MatchResult, first.id).match_status == "pending"
    assert db.get(MatchResult, second.id).match_status == "pending"


def test_run_match_preserves_ignored_rows_on_rerun(db):
    job, raw, mr = _seed_ignored_row(db, name="保留忽略")
    mr.match_status = "ignored"
    mr.matched_by = "manual"
    mr.review_note = "本任务忽略"
    db.commit()

    stats = run_match(db, job.id)
    refreshed = db.query(MatchResult).filter_by(clean_job_id=job.id).one()
    assert stats["ignored"] == 1
    assert refreshed.raw_data_id == raw.id
    assert refreshed.match_status == "ignored"
    assert refreshed.review_note == "本任务忽略"


def test_batch_ignore_filter_honors_category_and_top_brands(db, match_client):
    db.add(Category(code="camera", name="摄像头"))
    db.flush()
    job, raw, first = _seed_ignored_row(db, name="品牌A商品")
    job.dispatch_batch_id = 101
    db.add(DispatchItem(batch_id=101, raw_data_id=raw.id, category_code="camera"))
    cleaned = db.query(CleanedDataRecord).filter_by(clean_job_id=job.id, raw_data_id=raw.id).one()
    cleaned.brand_std = "A"
    cleaned.sales_qty = 200
    raw.sales_qty = 200

    other_raw = RawDataRecord(
        file_id=raw.file_id,
        platform="jd",
        item_id="other",
        item_name="品牌B商品",
        brand_raw="B",
        sales_qty=100,
    )
    db.add(other_raw)
    db.flush()
    other_cleaned = CleanedDataRecord(
        clean_job_id=job.id,
        raw_data_id=other_raw.id,
        platform="jd",
        item_name=other_raw.item_name,
        brand_raw="B",
        brand_std="B",
        sales_qty=100,
    )
    db.add(other_cleaned)
    db.flush()
    second = MatchResult(
        clean_job_id=job.id,
        raw_data_id=other_raw.id,
        match_status="pending",
        matched_by="auto",
    )
    db.add(second)
    db.add(DispatchItem(batch_id=101, raw_data_id=other_raw.id, category_code="camera"))
    db.commit()

    response = match_client.post(
        f"/api/match/{job.id}/batch-ignore",
        json={
            "mode": "filter",
            "filter": {"tab": "pending", "category_name": "camera", "top_brands": 1},
        },
    )
    assert response.status_code == 200
    assert response.json()["ignored"] == 1
    assert db.get(MatchResult, second.id).match_status == "pending"
    assert db.get(MatchResult, first.id).match_status == "ignored"
