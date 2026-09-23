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


def test_create_model_auto_hangs_brand_to_category(client):
    """新建型号时，品牌自动挂到该品类下（brand_categories），即使此前该品牌无此品类型号"""
    from app.models.schemas import BrandCategory

    client.current_user.is_admin = 1
    client.current_user.category_permissions = []
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
        "specs": [],
    })

    assert res.status_code == 200
    with client.Session() as session:
        rows = session.query(BrandCategory).filter_by(brand_code="B1").all()
        assert {r.category_code for r in rows} == {"AC"}


def test_batch_update_model_category_moves_selected_models(client):
    client.current_user.is_admin = 1
    client.current_user.category_permissions = []
    with client.Session() as session:
        session.add_all([
            Category(code="tv", name="电视", sort_order=1),
            Category(code="ac", name="空调", sort_order=2),
        ])
        session.add_all([
            ModelRecord(brand_code="B1", model_code="TV-1", category_code="tv", brand_name="品牌一", model_name="电视一"),
            ModelRecord(brand_code="B2", model_code="AC-1", category_code="ac", brand_name="品牌二", model_name="空调一"),
        ])
        session.commit()
        model_ids = [m.id for m in session.query(ModelRecord).order_by(ModelRecord.id).all()]

    resp = client.post("/api/models/batch-category", json={
        "model_ids": model_ids,
        "category_code": "ac",
    })

    assert resp.status_code == 200
    data = resp.json()
    assert data["updated"] == 2
    assert data["errors"] == []
    with client.Session() as session:
        categories = {m.category_code for m in session.query(ModelRecord).all()}
        assert categories == {"ac"}


def test_batch_update_model_category_reports_conflict_per_row(client):
    client.current_user.is_admin = 1
    client.current_user.category_permissions = []
    with client.Session() as session:
        session.add_all([
            Category(code="tv", name="电视", sort_order=1),
            Category(code="ac", name="空调", sort_order=2),
        ])
        session.add_all([
            ModelRecord(brand_code="B1", model_code="TV-1", category_code="tv", brand_name="品牌一", model_name="电视一"),
            ModelRecord(brand_code="B1", model_code="TV-1", category_code="ac", brand_name="品牌一", model_name="电视一(AC)"),
        ])
        session.commit()
        target_id = session.query(ModelRecord).filter_by(category_code="tv").first().id

    resp = client.post("/api/models/batch-category", json={
        "model_ids": [target_id],
        "category_code": "ac",
    })

    assert resp.status_code == 200
    data = resp.json()
    assert data["updated"] == 0
    assert len(data["errors"]) == 1
    assert "已存在" in data["errors"][0]["reason"]


def test_batch_update_model_category_rejects_invisible_target(client):
    client.current_user.is_admin = 0
    client.current_user.category_permissions = ["tv"]
    with client.Session() as session:
        session.add_all([
            Category(code="tv", name="电视", sort_order=1),
            Category(code="ac", name="空调", sort_order=2),
        ])
        session.add_all([
            ModelRecord(brand_code="B1", model_code="TV-1", category_code="tv", brand_name="品牌一", model_name="电视一"),
        ])
        session.commit()

    resp = client.post("/api/models/batch-category", json={
        "model_ids": [1],
        "category_code": "ac",
    })

    assert resp.status_code == 403
