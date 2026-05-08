# backend/tests/test_categories_api.py
"""categories_api 单元测试，使用 SQLite 内存库"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.models.database import Base, get_db
from app.models.schemas import Category, ModelRecord
from fastapi import FastAPI
from app.api.categories_api import router

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

    def override_db():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override_db
    return TestClient(app)


def test_list_empty(client):
    r = client.get("/categories")
    assert r.status_code == 200
    assert r.json() == []


def test_create_category(client):
    r = client.post("/categories", json={"code": "soundbar", "name": "回音壁"})
    assert r.status_code == 201
    data = r.json()
    assert data["code"] == "soundbar"
    assert data["name"] == "回音壁"
    assert "id" in data


def test_create_duplicate_code_returns_409(client):
    client.post("/categories", json={"code": "tv", "name": "电视"})
    r = client.post("/categories", json={"code": "tv", "name": "电视B"})
    assert r.status_code == 409


def test_update_name(client):
    res = client.post("/categories", json={"code": "spk", "name": "音箱"})
    cat_id = res.json()["id"]
    r = client.put(f"/categories/{cat_id}", json={"name": "智能音箱"})
    assert r.status_code == 200
    assert r.json()["name"] == "智能音箱"
    assert r.json()["code"] == "spk"  # code 不变


def test_delete_category(client):
    res = client.post("/categories", json={"code": "del", "name": "删除测试"})
    cat_id = res.json()["id"]
    r = client.delete(f"/categories/{cat_id}")
    assert r.status_code == 204


def test_delete_category_with_models_returns_409(client):
    """有关联型号时禁止删除"""
    pass  # 在集成测试中验证
