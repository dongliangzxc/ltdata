"""验证 models_api category_code 改造"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.models.database import Base, get_db
from app.models.schemas import BrandRecord, Category
from app.core.auth_deps import get_current_user
from fastapi import FastAPI
from app.api.models_api import router


class DummyUser:
    is_admin = 1
    category_permissions = []


@pytest.fixture
def client():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    app = FastAPI()
    app.include_router(router)

    def override_db():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: DummyUser()
    c = TestClient(app)
    # 预置品类和品牌
    s = Session()
    s.add(Category(code="soundbar", name="回音壁"))
    s.add_all([
        BrandRecord(brand_code="SONY", brand_name="索尼"),
        BrandRecord(brand_code="JBL", brand_name="JBL"),
    ])
    s.commit()
    s.close()
    return c


def test_create_model_with_category_code(client):
    r = client.post("/api/models", json={
        "brand_code": "SONY", "model_code": "HT-A7000",
        "category_code": "soundbar",
    })
    assert r.status_code == 200
    data = r.json()
    assert data["category_code"] == "soundbar"
    assert data["category_name"] == "回音壁"  # JOIN 填充


def test_list_models_returns_category_name(client):
    client.post("/api/models", json={"brand_code": "JBL", "model_code": "BAR800", "category_code": "soundbar"})
    r = client.get("/api/models")
    assert r.status_code == 200
    items = r.json()["items"]
    assert items[0]["category_name"] == "回音壁"


def test_create_model_without_model_code_auto_generates_placeholder(client):
    r = client.post("/api/models", json={
        "brand_code": "SONY",
        "model_code": "",
        "category_code": "soundbar",
        "model_name": "待补型号",
    })
    assert r.status_code == 200
    assert r.json()["model_code"] == "待补型号-soundbar"


def test_create_model_placeholder_code_unique_within_brand(client):
    r1 = client.post("/api/models", json={"brand_code": "SONY", "model_code": None, "category_code": "soundbar"})
    r2 = client.post("/api/models", json={"brand_code": "SONY", "model_code": None, "category_code": "soundbar"})
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json()["model_code"] == "待补型号-soundbar"
    assert r2.json()["model_code"] == "待补型号-soundbar-2"


def test_create_model_without_model_code_no_category_uses_unknown(client):
    r = client.post("/api/models", json={"brand_code": "SONY", "model_code": None})
    assert r.status_code == 200
    assert r.json()["model_code"] == "待补型号-unknown"


def test_create_model_duplicate_explicit_code_still_rejected(client):
    client.post("/api/models", json={"brand_code": "SONY", "model_code": "XM5"})
    r = client.post("/api/models", json={"brand_code": "SONY", "model_code": "XM5"})
    assert r.status_code == 409
