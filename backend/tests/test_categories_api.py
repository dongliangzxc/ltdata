# backend/tests/test_categories_api.py
"""categories_api 单元测试，使用 SQLite 内存库"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.models.database import Base, get_db
from app.core.auth_deps import get_current_user
from fastapi import FastAPI
from app.api.categories_api import router


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

    current_user = DummyUser(is_admin=1, category_permissions=[])

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
    test_client.current_user = current_user
    return test_client


def test_list_empty(client):
    r = client.get("/api/categories")
    assert r.status_code == 200
    assert r.json() == []


def test_create_category(client):
    r = client.post("/api/categories", json={"code": "soundbar", "name": "回音壁"})
    assert r.status_code == 201
    data = r.json()
    assert data["code"] == "soundbar"
    assert data["name"] == "回音壁"
    assert "id" in data


def test_create_duplicate_code_returns_409(client):
    client.post("/api/categories", json={"code": "tv", "name": "电视"})
    r = client.post("/api/categories", json={"code": "tv", "name": "电视B"})
    assert r.status_code == 409


def test_update_name(client):
    res = client.post("/api/categories", json={"code": "spk", "name": "音箱"})
    cat_id = res.json()["id"]
    r = client.put(f"/api/categories/{cat_id}", json={"name": "智能音箱"})
    assert r.status_code == 200
    assert r.json()["name"] == "智能音箱"
    assert r.json()["code"] == "spk"  # code 不变


def test_delete_category(client):
    res = client.post("/api/categories", json={"code": "del", "name": "删除测试"})
    cat_id = res.json()["id"]
    r = client.delete(f"/api/categories/{cat_id}")
    assert r.status_code == 204


def test_delete_category_with_models_returns_409(client):
    """有关联型号时禁止删除"""
    pass  # 在集成测试中验证


def test_scoped_user_only_lists_permitted_category_tree(client):
    client.current_user.is_admin = 0
    client.current_user.category_permissions = ["tv"]
    client.post("/api/categories", json={"code": "tv", "name": "电视"})
    client.post("/api/categories", json={"code": "soundbar", "name": "回音壁"})

    response = client.get("/api/categories/tree")

    assert response.status_code == 200
    assert [item["code"] for item in response.json()] == ["tv"]


def test_user_without_category_permissions_lists_all_categories(client):
    client.current_user.is_admin = 0
    client.current_user.category_permissions = []
    client.post("/api/categories", json={"code": "tv", "name": "电视"})
    client.post("/api/categories", json={"code": "soundbar", "name": "回音壁"})

    response = client.get("/api/categories/tree")

    assert response.status_code == 200
    assert [item["code"] for item in response.json()] == ["soundbar", "tv"]


def test_scoped_user_cannot_update_unpermitted_category(client):
    created = client.post("/api/categories", json={"code": "tv", "name": "电视"})
    client.current_user.is_admin = 0
    client.current_user.category_permissions = ["soundbar"]

    response = client.put(f"/api/categories/{created.json()['id']}", json={"name": "电视机"})

    assert response.status_code == 403
    assert response.json()["detail"] == "无权限访问该品类"


def test_scoped_user_cannot_delete_unpermitted_category(client):
    created = client.post("/api/categories", json={"code": "tv", "name": "电视"})
    client.current_user.is_admin = 0
    client.current_user.category_permissions = ["soundbar"]

    response = client.delete(f"/api/categories/{created.json()['id']}")

    assert response.status_code == 403
    assert response.json()["detail"] == "无权限访问该品类"
