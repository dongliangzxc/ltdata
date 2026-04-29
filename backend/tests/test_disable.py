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
