"""Brand API category permission tests."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.brands_api import router
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


def seed_data(session):
    session.add_all([
        Category(code="TV", name="电视", sort_order=1),
        Category(code="AC", name="空调", sort_order=2),
        BrandRecord(brand_code="SONY", brand_name="索尼"),
        BrandRecord(brand_code="GREE", brand_name="格力"),
        ModelRecord(brand_code="SONY", model_code="TV-1", category_code="TV", brand_name="索尼", model_name="电视一"),
        ModelRecord(brand_code="GREE", model_code="AC-1", category_code="AC", brand_name="格力", model_name="空调一"),
    ])


def test_list_brands_only_returns_brands_with_visible_model_categories(client):
    with client.Session() as session:
        seed_data(session)
        session.commit()

    res = client.get("/api/brands")

    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 1
    assert [item["brand_code"] for item in data["items"]] == ["SONY"]
    assert data["items"][0]["category_codes"] == ["TV"]


def test_empty_category_permissions_can_see_all_brands(client):
    client.current_user.category_permissions = []
    with client.Session() as session:
        seed_data(session)
        session.commit()

    res = client.get("/api/brands")

    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 2
    assert {item["brand_code"] for item in data["items"]} == {"SONY", "GREE"}
