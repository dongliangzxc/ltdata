"""验证 models_api category_code 改造"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.models.database import Base, get_db
from app.models.schemas import Category
from fastapi import FastAPI
from app.api.models_api import router

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
    c = TestClient(app)
    # 预置品类
    s = Session()
    s.add(Category(code="soundbar", name="回音壁"))
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
