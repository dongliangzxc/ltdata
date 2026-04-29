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
