"""白牌/公模归类（S5）与配置 API 测试。"""
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.white_label_api import router as white_label_router
from app.core.auth_deps import get_current_user
from app.models.database import Base, get_db
from app.models.schemas import (
    Category,
    CleanJobRecord,
    CleanedDataRecord,
    MatchResult,
    MatchResultCandidate,
    ModelRecord,
    RawDataRecord,
    UploadFileRecord,
    WhiteLabelPolicy,
    WhiteLabelRule,
)
from app.services.matcher import run_match


class DummyUser:
    def __init__(self, *, is_admin=0, category_permissions=None):
        self.is_admin = is_admin
        self.category_permissions = category_permissions


def _seed_job(db, *, category_code, item_name, brand_raw=None):
    upload = UploadFileRecord(filename="wl.xlsx", status="done", row_count=1)
    db.add(upload)
    db.flush()
    raw = RawDataRecord(file_id=upload.id, item_name=item_name, brand_raw=brand_raw)
    db.add(raw)
    db.flush()
    job = CleanJobRecord(
        file_ids=[upload.id], rules={}, status="done", row_in=1, row_out=1,
        category_code=category_code,
    )
    db.add(job)
    db.flush()
    db.add(CleanedDataRecord(
        raw_data_id=raw.id,
        clean_job_id=job.id,
        item_name=item_name,
        brand_raw=brand_raw,
    ))
    db.flush()
    return job.id


def _seed_placeholder(db, *, category_code, brand_code="无品牌", model_code="INEAR", model_name="入耳式"):
    model = ModelRecord(
        brand_code=brand_code,
        model_code=model_code,
        model_name=model_name,
        brand_name=brand_code,
        category_code=category_code,
    )
    db.add(model)
    db.flush()
    return model


def _seed_policy(db, *, category_code, mode="auto", enabled=1, brand_code="无品牌", unmatched_model_id=None):
    policy = WhiteLabelPolicy(
        category_code=category_code,
        enabled=enabled,
        mode=mode,
        brand_code=brand_code,
        unmatched_model_id=unmatched_model_id,
    )
    db.add(policy)
    db.flush()
    return policy


def _seed_category(db, category_code):
    db.add(Category(code=category_code, name=category_code, sort_order=1))
    db.flush()


def test_auto_mode_matches_placeholder_model(db):
    _seed_category(db, "headphone")
    placeholder = _seed_placeholder(db, category_code="headphone", model_code="INEAR", model_name="入耳式")
    _seed_policy(db, category_code="headphone", mode="auto", enabled=1)
    db.add(WhiteLabelRule(
        category_code="headphone", keyword="入耳", match_type="contains",
        model_id=placeholder.id, priority=20, is_active=1,
    ))
    job_id = _seed_job(
        db, category_code="headphone", brand_raw=None,
        item_name="通用入耳式蓝牙耳机 超长续航",
    )
    db.commit()

    run_match(db, job_id)

    result = db.query(MatchResult).filter(MatchResult.clean_job_id == job_id).one()
    assert result.match_status == "matched"
    assert result.model_id == placeholder.id
    assert result.match_source == "white_label"
    assert result.brand_identified == 1


def test_suggest_mode_adds_candidate_and_keeps_pending(db):
    _seed_category(db, "headphone")
    placeholder = _seed_placeholder(db, category_code="headphone", model_code="HEAD", model_name="头戴式")
    _seed_policy(db, category_code="headphone", mode="suggest", enabled=1)
    db.add(WhiteLabelRule(
        category_code="headphone", keyword="头戴", match_type="contains",
        model_id=placeholder.id, priority=20, is_active=1,
    ))
    job_id = _seed_job(
        db, category_code="headphone", brand_raw=None,
        item_name="头戴式无线蓝牙耳机",
    )
    db.commit()

    run_match(db, job_id)

    result = db.query(MatchResult).filter(MatchResult.clean_job_id == job_id).one()
    assert result.match_status == "pending"
    assert result.model_id is None
    assert result.brand_identified == 1
    candidate = db.query(MatchResultCandidate).filter(
        MatchResultCandidate.match_result_id == result.id,
    ).one()
    assert candidate.model_id == placeholder.id
    assert candidate.match_source == "white_label"


def test_off_mode_does_not_classify(db):
    _seed_category(db, "headphone")
    placeholder = _seed_placeholder(db, category_code="headphone")
    _seed_policy(db, category_code="headphone", mode="off", enabled=0)
    db.add(WhiteLabelRule(
        category_code="headphone", keyword="入耳", match_type="contains",
        model_id=placeholder.id, priority=20, is_active=1,
    ))
    job_id = _seed_job(
        db, category_code="headphone", brand_raw=None,
        item_name="通用入耳式蓝牙耳机",
    )
    db.commit()

    run_match(db, job_id)

    result = db.query(MatchResult).filter(MatchResult.clean_job_id == job_id).one()
    assert result.match_status == "pending"
    assert result.model_id is None
    assert result.brand_identified == 0
    assert db.query(MatchResultCandidate).filter(
        MatchResultCandidate.match_result_id == result.id,
    ).count() == 0


def test_real_brand_and_model_wins_over_white_label(db):
    _seed_category(db, "headphone")
    real = ModelRecord(
        brand_code="EDIFIER", model_code="LOLLIPODS", brand_name="漫步者",
        model_name="LolliPods", category_code="headphone",
    )
    placeholder = _seed_placeholder(db, category_code="headphone")
    db.add_all([real, placeholder])
    db.flush()
    _seed_policy(db, category_code="headphone", mode="auto", enabled=1)
    db.add(WhiteLabelRule(
        category_code="headphone", keyword="入耳", match_type="contains",
        model_id=placeholder.id, priority=20, is_active=1,
    ))
    job_id = _seed_job(
        db, category_code="headphone", brand_raw="漫步者",
        item_name="漫步者 LolliPods 入耳式蓝牙耳机",
    )
    db.commit()

    run_match(db, job_id)

    result = db.query(MatchResult).filter(MatchResult.clean_job_id == job_id).one()
    assert result.match_status == "matched"
    assert result.model_id == real.id
    assert result.match_source != "white_label"


def test_placeholder_long_code_is_not_used_by_s4(db):
    _seed_category(db, "bt_speaker")
    placeholder = _seed_placeholder(
        db, category_code="bt_speaker", model_code="SOUNDBAR", model_name="回音壁",
    )
    _seed_policy(db, category_code="bt_speaker", mode="off", enabled=0)
    db.add(WhiteLabelRule(
        category_code="bt_speaker", keyword="回音壁", match_type="contains",
        model_id=placeholder.id, priority=20, is_active=1,
    ))
    job_id = _seed_job(
        db, category_code="bt_speaker", brand_raw=None,
        item_name="某款 soundbar 蓝牙音箱",
    )
    db.commit()

    run_match(db, job_id)

    result = db.query(MatchResult).filter(MatchResult.clean_job_id == job_id).one()
    assert result.match_status == "pending"
    assert result.model_id is None


def test_brand_text_not_in_library_is_not_white_labeled(db):
    """原品牌有明确文字但品牌库没认出来时，不能归成「无品牌」。"""
    _seed_category(db, "headphone")
    placeholder = _seed_placeholder(db, category_code="headphone")
    _seed_policy(db, category_code="headphone", mode="auto", enabled=1)
    db.add(WhiteLabelRule(
        category_code="headphone", keyword="入耳", match_type="contains",
        model_id=placeholder.id, priority=20, is_active=1,
    ))
    job_id = _seed_job(
        db, category_code="headphone", brand_raw="硕科思",
        item_name="硕科思 入耳式蓝牙耳机",
    )
    db.commit()

    run_match(db, job_id)

    result = db.query(MatchResult).filter(MatchResult.clean_job_id == job_id).one()
    assert result.match_status == "pending"
    assert result.model_id is None
    assert result.brand_identified == 0


def test_unmatched_falls_back_to_unmatched_model(db):
    _seed_category(db, "bt_speaker")
    unmatched = _seed_placeholder(
        db, category_code="bt_speaker", model_code="OTHER", model_name="未分类",
    )
    _seed_policy(
        db, category_code="bt_speaker", mode="auto", enabled=1,
        unmatched_model_id=unmatched.id,
    )
    job_id = _seed_job(
        db, category_code="bt_speaker", brand_raw=None,
        item_name="无线蓝牙音箱 重低音",
    )
    db.commit()

    run_match(db, job_id)

    result = db.query(MatchResult).filter(MatchResult.clean_job_id == job_id).one()
    assert result.match_status == "matched"
    assert result.model_id == unmatched.id


def test_rule_priority_prefers_more_specific_keyword(db):
    _seed_category(db, "headphone")
    half = _seed_placeholder(db, category_code="headphone", model_code="HALF", model_name="半入耳式")
    inear = _seed_placeholder(db, category_code="headphone", model_code="INEAR", model_name="入耳式")
    _seed_policy(db, category_code="headphone", mode="auto", enabled=1)
    db.add_all([
        WhiteLabelRule(category_code="headphone", keyword="半入耳", match_type="contains",
                       model_id=half.id, priority=10, is_active=1),
        WhiteLabelRule(category_code="headphone", keyword="入耳", match_type="contains",
                       model_id=inear.id, priority=20, is_active=1),
    ])
    job_id = _seed_job(
        db, category_code="headphone", brand_raw=None,
        item_name="半入耳式无线蓝牙耳机",
    )
    db.commit()

    run_match(db, job_id)

    result = db.query(MatchResult).filter(MatchResult.clean_job_id == job_id).one()
    assert result.model_id == half.id


def _client(db):
    app = FastAPI()
    app.include_router(white_label_router)
    current_user = {"value": DummyUser(is_admin=1)}
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: current_user["value"]
    client = TestClient(app)
    client.db = db
    client.current_user = current_user
    return client


def test_policy_and_rule_api(db):
    _seed_category(db, "headphone")
    placeholder = _seed_placeholder(db, category_code="headphone", model_code="INEAR", model_name="入耳式")
    db.commit()
    client = _client(db)

    policies = client.get("/api/white-label/policies").json()
    assert any(p["category_code"] == "headphone" and p["enabled"] is False for p in policies)

    saved = client.put("/api/white-label/policies/headphone", json={
        "enabled": True,
        "mode": "suggest",
        "brand_code": "无品牌",
        "unmatched_model_id": placeholder.id,
    })
    assert saved.status_code == 200
    assert saved.json()["enabled"] is True
    assert saved.json()["mode"] == "suggest"

    created = client.post("/api/white-label/rules", json={
        "category_code": "headphone",
        "keyword": "入耳",
        "match_type": "contains",
        "model_id": placeholder.id,
        "priority": 20,
        "is_active": True,
    })
    assert created.status_code == 201
    rule_id = created.json()["id"]

    listed = client.get("/api/white-label/rules", params={"category_code": "headphone"}).json()
    assert [row["id"] for row in listed] == [rule_id]
    assert listed[0]["model_name"] == "入耳式"

    models = client.get("/api/white-label/models", params={"category_code": "headphone"}).json()
    assert [row["id"] for row in models] == [placeholder.id]

    deleted = client.delete(f"/api/white-label/rules/{rule_id}")
    assert deleted.status_code == 204


def _match_client(db):
    from app.api.match_api import router as match_router

    app = FastAPI()
    app.include_router(match_router)
    current_user = {"value": DummyUser(is_admin=1)}
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: current_user["value"]
    client = TestClient(app)
    client.db = db
    client.current_user = current_user
    return client


def test_batch_white_label_classify_ids(db):
    _seed_category(db, "headphone")
    placeholder = _seed_placeholder(db, category_code="headphone", model_code="INEAR", model_name="入耳式")
    upload = UploadFileRecord(filename="wl.xlsx", status="done", row_count=1)
    db.add(upload)
    db.flush()
    job = CleanJobRecord(file_ids=[upload.id], rules={}, status="reviewing", category_code="headphone")
    db.add(job)
    db.flush()
    match_ids = []
    for index in range(2):
        raw = RawDataRecord(file_id=upload.id, item_name=f"无名入耳式耳机{index}", brand_raw="力勤")
        db.add(raw)
        db.flush()
        mr = MatchResult(
            clean_job_id=job.id,
            raw_data_id=raw.id,
            match_status="pending",
            matched_by="auto",
            brand_identified=0,
        )
        db.add(mr)
        db.flush()
        match_ids.append(mr.id)
    db.commit()
    client = _match_client(db)

    response = client.post(f"/api/match/{job.id}/white-label-classify", json={
        "mode": "ids",
        "ids": match_ids,
        "model_id": placeholder.id,
    })

    assert response.status_code == 200
    assert response.json()["success"] == 2
    db.expire_all()
    rows = db.query(MatchResult).filter(MatchResult.id.in_(match_ids)).all()
    assert all(row.match_status == "confirmed" for row in rows)
    assert all(row.model_id == placeholder.id for row in rows)
    assert all(row.brand_identified == 1 for row in rows)
    assert all(row.match_source == "white_label" for row in rows)


def test_batch_white_label_classify_rejects_real_model(db):
    _seed_category(db, "headphone")
    real = ModelRecord(
        brand_code="EDIFIER", model_code="LOLLIPODS", brand_name="漫步者",
        model_name="LolliPods", category_code="headphone",
    )
    db.add(real)
    db.flush()
    upload = UploadFileRecord(filename="wl.xlsx", status="done", row_count=1)
    db.add(upload)
    db.flush()
    job = CleanJobRecord(file_ids=[upload.id], rules={}, status="reviewing", category_code="headphone")
    db.add(job)
    db.commit()
    client = _match_client(db)

    response = client.post(f"/api/match/{job.id}/white-label-classify", json={
        "mode": "ids",
        "ids": [1],
        "model_id": real.id,
    })

    assert response.status_code == 400
    assert "占位型号" in response.json()["detail"]


def test_rule_api_rejects_non_placeholder_model(db):
    _seed_category(db, "headphone")
    real = ModelRecord(
        brand_code="EDIFIER", model_code="LOLLIPODS", brand_name="漫步者",
        model_name="LolliPods", category_code="headphone",
    )
    db.add(real)
    db.commit()
    client = _client(db)

    response = client.post("/api/white-label/rules", json={
        "category_code": "headphone",
        "keyword": "入耳",
        "match_type": "contains",
        "model_id": real.id,
        "priority": 20,
        "is_active": True,
    })
    assert response.status_code == 400
    assert "占位型号" in response.json()["detail"]
