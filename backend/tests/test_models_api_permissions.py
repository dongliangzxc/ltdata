"""Model API category permission tests."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.models_api import router
from app.core.auth_deps import get_current_user
from app.models.database import Base, get_db
from app.models.schemas import BrandRecord, Category, ModelRecord


class DummyUser:
    def __init__(self, *, is_admin=0, category_permissions=None):
        self.is_admin = is_admin
        self.category_permissions = category_permissions


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    app = FastAPI()
    app.include_router(router)

    current_user = DummyUser(is_admin=0, category_permissions=["TV"])

    def override_db():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    def override_current_user():
        return current_user

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_current_user
    test_client = TestClient(app)
    test_client.Session = Session
    test_client.current_user = current_user
    return test_client


def seed_categories(session):
    session.add_all([
        Category(code="TV", name="电视", sort_order=1),
        Category(code="AC", name="空调", sort_order=2),
    ])


def seed_brands(session):
    session.add_all([
        BrandRecord(brand_code="B1", brand_name="品牌一", status="active"),
        BrandRecord(brand_code="B2", brand_name="品牌二", status="active"),
    ])


def seed_models(session):
    session.add_all([
        ModelRecord(brand_code="B1", model_code="TV-1", category_code="TV", brand_name="品牌一", model_name="电视一"),
        ModelRecord(brand_code="B2", model_code="AC-1", category_code="AC", brand_name="品牌二", model_name="空调一"),
    ])


def test_list_models_only_returns_visible_categories(client):
    with client.Session() as session:
        seed_categories(session)
        seed_brands(session)
        seed_models(session)
        session.commit()

    res = client.get("/api/models")

    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 1
    assert [item["category_code"] for item in data["items"]] == ["TV"]


def test_create_model_rejects_invisible_category(client):
    with client.Session() as session:
        seed_categories(session)
        seed_brands(session)
        session.commit()

    res = client.post("/api/models", json={
        "brand_code": "B1",
        "model_code": "M1",
        "category_code": "AC",
        "brand_name": "品牌一",
        "model_name": "型号一",
        "launch_year": 2024,
        "launch_month": 1,
        "launch_week": 1,
        "launch_price": 1999,
        "url": "https://example.com",
        "status": "active",
        "operator": "tester",
        "specs": [],
    })

    assert res.status_code == 403
    assert res.json()["detail"] == "无权限访问该品类"
