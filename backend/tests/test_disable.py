"""测试禁用/启用功能"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.models.schemas import Base, MatchResult
from app.main import app
from app.models.database import get_db

SQLITE_URL = "sqlite:///:memory:"

engine = create_engine(
    SQLITE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
Base.metadata.drop_all(bind=engine)
Base.metadata.create_all(bind=engine)
TestSession = sessionmaker(bind=engine)

def override_get_db():
    db = TestSession()
    try:
        yield db
    finally:
        db.close()

app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)


def test_match_result_has_is_disabled():
    """MatchResult ORM 应包含 is_disabled 和 disable_reason 字段"""
    mr = MatchResult(
        clean_job_id=1,
        raw_data_id=1,
        match_status="matched",
        is_disabled=0,
        disable_reason=None,
    )
    assert mr.is_disabled == 0
    assert mr.disable_reason is None


from app.models.schemas import (
    ModelRecord, RawDataRecord, CleanJobRecord, UploadFileRecord,
)
from app.models.analytics_db import AnalyticsBase, analytics_engine, AnalyticsSession

AnalyticsBase.metadata.create_all(bind=analytics_engine)


def _seed_publish_data(db):
    """创建上传文件、原始数据、清洗任务、型号、匹配结果（1条正常+1条禁用）"""
    # RawDataRecord requires file_id FK; create a parent UploadFileRecord first
    upload_file = UploadFileRecord(
        filename="test.xlsx",
        platform="jd",
        month_range="202601",
    )
    db.add(upload_file)
    db.flush()

    model = ModelRecord(
        brand_code="TST",
        model_code="X100",
        model_name="Test Model",
        category_name="平板",
        brand_name="Test Brand",
    )
    db.add(model)
    db.flush()

    clean_job = CleanJobRecord(status="done", file_ids=[upload_file.id])
    db.add(clean_job)
    db.flush()

    rd1 = RawDataRecord(
        file_id=upload_file.id,
        platform="jd", month=202601, category_lv1="平板",
        item_id="item1", item_name="Test Item Normal",
        brand_raw="TST", price=500.0, sales_qty=10, sales_amount=5000.0,
    )
    rd2 = RawDataRecord(
        file_id=upload_file.id,
        platform="jd", month=202601, category_lv1="平板",
        item_id="item2", item_name="Test Item Disabled",
        brand_raw="TST", price=100.0, sales_qty=1, sales_amount=100.0,
    )
    db.add_all([rd1, rd2])
    db.flush()

    mr1 = MatchResult(
        clean_job_id=clean_job.id, raw_data_id=rd1.id,
        model_id=model.id, match_status="matched",
        is_disabled=0,
    )
    mr2 = MatchResult(
        clean_job_id=clean_job.id, raw_data_id=rd2.id,
        model_id=model.id, match_status="matched",
        is_disabled=1, disable_reason="avg_price",
    )
    db.add_all([mr1, mr2])
    db.commit()
    return clean_job.id


def test_publisher_excludes_disabled():
    """发布时 is_disabled=1 的行不应被发布"""
    from app.services.publisher import run_publish

    db = TestSession()
    clean_job_id = _seed_publish_data(db)
    db.close()

    db = TestSession()
    analytics_db = AnalyticsSession()
    try:
        result = run_publish(db, analytics_db, clean_job_id)
        assert result["published_count"] == 1, \
            f"应发布 1 条（排除禁用），实际: {result['published_count']}"
    finally:
        db.close()
        analytics_db.close()


from passlib.context import CryptContext
from app.models.schemas import User as UserRecord

_pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")


def _get_or_create_user_token():
    """创建测试用户并获取 JWT token"""
    db = TestSession()
    user = db.query(UserRecord).filter(UserRecord.username == "tester").first()
    if not user:
        user = UserRecord(
            username="tester",
            hashed_password=_pwd_ctx.hash("tester123"),
        )
        db.add(user)
        db.commit()
    db.close()

    resp = client.post("/api/auth/login", json={"username": "tester", "password": "tester123"})
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    return resp.json()["data"]["access_token"]


def _seed_single_mr():
    """创建单条 matched match_result，返回 (match_id, clean_job_id)"""
    db = TestSession()
    # reuse or create model
    from app.models.schemas import ModelRecord, RawDataRecord, CleanJobRecord
    model = db.query(ModelRecord).first()
    if not model:
        model = ModelRecord(
            brand_code="API", model_code="API100",
            model_name="API Model", category_name="平板",
        )
        db.add(model)
        db.flush()

    # need an upload file for raw data
    from app.models.schemas import UploadFileRecord
    uf = UploadFileRecord(filename="test.xlsx", status="done")
    db.add(uf)
    db.flush()

    cj = CleanJobRecord(status="done", file_ids=[uf.id])
    db.add(cj)
    db.flush()

    rd = RawDataRecord(
        file_id=uf.id,
        platform="jd", month=202604, category_lv1="平板",
        item_id=f"apitem_{cj.id}", item_name="API Test Item",
        brand_raw="API", price=300.0, sales_qty=5, sales_amount=1500.0,
    )
    db.add(rd)
    db.flush()

    mr = MatchResult(
        clean_job_id=cj.id, raw_data_id=rd.id,
        model_id=model.id, match_status="matched", is_disabled=0,
    )
    db.add(mr)
    db.commit()
    mr_id = mr.id
    cj_id = cj.id
    db.close()
    return mr_id, cj_id


def test_disable_and_enable_single():
    """单条禁用后 is_disabled=1，启用后 is_disabled=0"""
    token = _get_or_create_user_token()
    match_id, _ = _seed_single_mr()
    headers = {"Authorization": f"Bearer {token}"}

    # 禁用
    r = client.patch(f"/api/match/{match_id}/disable",
                     json={"reason": "商用"}, headers=headers)
    assert r.status_code == 200, f"disable failed: {r.text}"
    assert r.json()["is_disabled"] == 1
    assert r.json()["disable_reason"] == "商用"

    # 启用
    r = client.patch(f"/api/match/{match_id}/enable", headers=headers)
    assert r.status_code == 200, f"enable failed: {r.text}"
    assert r.json()["is_disabled"] == 0
    assert r.json()["disable_reason"] is None


def test_avg_price_disable():
    """均价禁用：price < threshold 的 matched 行应被禁用"""
    token = _get_or_create_user_token()
    headers = {"Authorization": f"Bearer {token}"}

    db = TestSession()
    from app.models.schemas import ModelRecord, RawDataRecord, CleanJobRecord, UploadFileRecord
    model = db.query(ModelRecord).first()

    uf = UploadFileRecord(filename="avg.xlsx", status="done")
    db.add(uf)
    db.flush()

    cj = CleanJobRecord(status="done", file_ids=[uf.id])
    db.add(cj)
    db.flush()

    rd_low = RawDataRecord(
        file_id=uf.id, platform="jd", month=202604, category_lv1="平板",
        item_id="avg_low", item_name="低价商品",
        brand_raw="API", price=100.0, sales_qty=1, sales_amount=100.0,
    )
    rd_high = RawDataRecord(
        file_id=uf.id, platform="jd", month=202604, category_lv1="平板",
        item_id="avg_high", item_name="正常商品",
        brand_raw="API", price=500.0, sales_qty=10, sales_amount=5000.0,
    )
    db.add_all([rd_low, rd_high])
    db.flush()

    mr_low = MatchResult(clean_job_id=cj.id, raw_data_id=rd_low.id,
                         model_id=model.id, match_status="matched", is_disabled=0)
    mr_high = MatchResult(clean_job_id=cj.id, raw_data_id=rd_high.id,
                          model_id=model.id, match_status="matched", is_disabled=0)
    db.add_all([mr_low, mr_high])
    db.commit()
    cj_id = cj.id
    db.close()

    r = client.post(f"/api/match/{cj_id}/avg-price-disable",
                    json={"threshold": 200}, headers=headers)
    assert r.status_code == 200, f"avg-price-disable failed: {r.text}"
    assert r.json()["disabled_count"] == 1


def test_list_disabled():
    """查询禁用列表，应只返回 is_disabled=1 的行"""
    token = _get_or_create_user_token()
    match_id, cj_id = _seed_single_mr()
    headers = {"Authorization": f"Bearer {token}"}

    # 先禁用
    client.patch(f"/api/match/{match_id}/disable",
                 json={"reason": "配件"}, headers=headers)

    r = client.get(f"/api/match/{cj_id}/disabled", headers=headers)
    assert r.status_code == 200, f"list disabled failed: {r.text}"
    data = r.json()
    assert data["total"] >= 1
    assert all(item["is_disabled"] == 1 for item in data["items"])
