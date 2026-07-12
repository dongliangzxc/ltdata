from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.models.database import get_db
from app.models.schemas import (
    MatchTransferLog, MatchResult, RawDataRecord, ModelRecord,
    CleanJobRecord, UploadFileRecord, Category, CleanedDataRecord,
    ItemUrlMapping, MatchResultCandidate, MatchResultAttr,
)
from app.api.match_api import router as match_router


@pytest.fixture()
def match_client(db):
    app = FastAPI()
    app.include_router(match_router)

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    return TestClient(app)


def test_match_transfer_log_model_persists(db):
    log = MatchTransferLog(
        match_result_id=1,
        raw_data_id=2,
        from_clean_job_id=10,
        to_clean_job_id=20,
        operator=None,
        transferred_at=datetime(2026, 7, 12, 10, 0, 0),
    )
    db.add(log)
    db.commit()

    fetched = db.query(MatchTransferLog).first()
    assert fetched.match_result_id == 1
    assert fetched.from_clean_job_id == 10
    assert fetched.to_clean_job_id == 20
    assert fetched.transferred_at.year == 2026


def _seed_transfer_case(db, *, item_name="DJI Osmo-Nano 运动相机", brand_raw="DJI"):
    upload = UploadFileRecord(filename="src.xlsx", status="done")
    db.add(upload)
    db.flush()

    src_job = CleanJobRecord(
        file_ids=[upload.id], task_name="智能门锁任务",
        category_code="smartlock", status="done",
    )
    dst_job = CleanJobRecord(
        file_ids=[upload.id], task_name="运动相机任务",
        category_code="camera", status="done",
    )
    db.add_all([src_job, dst_job])
    db.flush()

    model = ModelRecord(brand_code="DJI", model_code="Osmo-Nano", category_code="camera")
    db.add(model)
    db.flush()

    raw = RawDataRecord(
        file_id=upload.id, item_name=item_name, brand_raw=brand_raw,
        platform="jd", item_id=f"jd-{item_name}",
    )
    db.add(raw)
    db.flush()

    mr = MatchResult(
        clean_job_id=src_job.id, raw_data_id=raw.id,
        match_status="pending", matched_by="auto",
    )
    db.add(mr)
    db.commit()
    return src_job, dst_job, mr, model, raw


def test_transfer_moves_to_target_and_reruns_match(db, match_client):
    src_job, dst_job, mr, model, raw = _seed_transfer_case(db)

    resp = match_client.post(
        f"/api/match/items/{mr.id}/transfer",
        json={"target_clean_job_id": dst_job.id},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["clean_job_id"] == dst_job.id

    db.refresh(mr)
    assert mr.clean_job_id == dst_job.id
    # camera 品类下有 DJI Osmo-Nano 型号，S1 应命中
    assert mr.match_status in ("matched", "text_only", "url_matched")
    assert mr.model_id == model.id
    # prev_* 应全部清空
    assert mr.prev_match_status is None
    assert mr.prev_model_id is None
    assert mr.dispute_reason is None
    assert mr.review_note is None
    assert mr.reviewed_at is None

    log = db.query(MatchTransferLog).filter_by(match_result_id=mr.id).first()
    assert log is not None
    assert log.from_clean_job_id == src_job.id
    assert log.to_clean_job_id == dst_job.id
    assert log.raw_data_id == raw.id


def test_transfer_rejects_target_with_existing_raw_data(db, match_client):
    src_job, dst_job, mr, _, raw = _seed_transfer_case(db)
    # 在目标任务里预先塞一条同 raw_data_id 的 match_result
    dup = MatchResult(
        clean_job_id=dst_job.id, raw_data_id=raw.id,
        match_status="pending", matched_by="auto",
    )
    db.add(dup)
    db.commit()

    resp = match_client.post(
        f"/api/match/items/{mr.id}/transfer",
        json={"target_clean_job_id": dst_job.id},
    )
    assert resp.status_code == 400
    assert "已有该商品" in resp.json()["detail"]

    # 源记录不变
    db.refresh(mr)
    assert mr.clean_job_id == src_job.id
    # 没有日志
    assert db.query(MatchTransferLog).count() == 0


def test_transfer_rejects_same_job(db, match_client):
    src_job, _, mr, _, _ = _seed_transfer_case(db)
    resp = match_client.post(
        f"/api/match/items/{mr.id}/transfer",
        json={"target_clean_job_id": src_job.id},
    )
    assert resp.status_code == 400
    assert "当前任务" in resp.json()["detail"]


def test_transfer_rejects_unknown_target(db, match_client):
    _, _, mr, _, _ = _seed_transfer_case(db)
    resp = match_client.post(
        f"/api/match/items/{mr.id}/transfer",
        json={"target_clean_job_id": 99999},
    )
    assert resp.status_code == 400
    assert "不存在" in resp.json()["detail"] or "归档" in resp.json()["detail"]


def test_transfer_rejects_archived_target(db, match_client):
    _, _, mr, _, _ = _seed_transfer_case(db)
    upload = UploadFileRecord(filename="arch.xlsx", status="done")
    db.add(upload)
    db.flush()
    archived = CleanJobRecord(
        file_ids=[upload.id], task_name="归档任务",
        category_code="camera", status="archived",
    )
    db.add(archived)
    db.commit()

    resp = match_client.post(
        f"/api/match/items/{mr.id}/transfer",
        json={"target_clean_job_id": archived.id},
    )
    assert resp.status_code == 400


def test_transfer_clears_old_candidates_and_attrs(db, match_client):
    src_job, dst_job, mr, _, _ = _seed_transfer_case(db)
    # 造一个 smartlock 品类下的候选，转移到 camera 后应被清除
    lock = ModelRecord(brand_code="KDLK", model_code="X1", category_code="smartlock")
    db.add(lock)
    db.flush()
    db.add(MatchResultCandidate(
        match_result_id=mr.id, model_id=lock.id,
        match_source="s1", score=5, rank=1,
    ))
    db.add(MatchResultAttr(
        match_result_id=mr.id, attr_name="锁类型", attr_value="全自动",
    ))
    db.commit()

    resp = match_client.post(
        f"/api/match/items/{mr.id}/transfer",
        json={"target_clean_job_id": dst_job.id},
    )
    assert resp.status_code == 200

    old_cand = db.query(MatchResultCandidate).filter_by(
        match_result_id=mr.id, model_id=lock.id
    ).first()
    assert old_cand is None
    old_attr = db.query(MatchResultAttr).filter_by(
        match_result_id=mr.id, attr_name="锁类型"
    ).first()
    assert old_attr is None
