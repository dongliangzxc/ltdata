import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.users_api import router
from app.core.security import hash_password
from app.models.database import Base, get_db
from app.models.schemas import User


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    admin = User(username="admin", hashed_password=hash_password("luotu123"), name="管理员", is_admin=1, permissions=[])
    session.add(admin)
    session.commit()
    session.close()

    app = FastAPI()
    app.include_router(router)

    def override_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    def override_admin():
        db = Session()
        try:
            return db.query(User).filter(User.username == "admin").first()
        finally:
            db.close()

    from app.core.auth_deps import require_admin

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[require_admin] = override_admin
    try:
        yield TestClient(app)
    finally:
        Base.metadata.drop_all(engine)


def test_create_and_list_user(client):
    res = client.post(
        "/api/users",
        json={
            "username": "analyst",
            "password": "secret123",
            "name": "分析师",
            "phone": "13800000000",
            "email": "a@example.com",
            "permissions": ["data_management"],
        },
    )
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["username"] == "analyst"
    assert data["name"] == "分析师"
    assert data["permissions"] == ["data_management"]

    list_res = client.get("/api/users", params={"keyword": "分析"})
    assert list_res.status_code == 200
    users = list_res.json()["data"]
    assert [user["username"] for user in users] == ["analyst"]


def test_admin_user_permissions_are_cleared(client):
    res = client.post(
        "/api/users",
        json={
            "username": "manager",
            "password": "secret123",
            "is_admin": 1,
            "permissions": ["data_management"],
        },
    )
    assert res.status_code == 200
    assert res.json()["data"]["is_admin"] == 1
    assert res.json()["data"]["permissions"] == []


def test_duplicate_username_returns_409(client):
    payload = {"username": "analyst", "password": "secret123"}
    assert client.post("/api/users", json=payload).status_code == 200
    res = client.post("/api/users", json=payload)
    assert res.status_code == 409


def test_update_user_status_and_permissions(client):
    created = client.post("/api/users", json={"username": "analyst", "password": "secret123"}).json()["data"]
    res = client.patch(
        f"/api/users/{created['id']}",
        json={"is_active": 0, "permissions": ["processing_workbench"], "name": " 新姓名 "},
    )
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["is_active"] == 0
    assert data["name"] == "新姓名"
    assert data["permissions"] == ["processing_workbench"]


def test_reset_password(client):
    created = client.post("/api/users", json={"username": "analyst", "password": "secret123"}).json()["data"]
    res = client.post(f"/api/users/{created['id']}/reset-password", json={"password": "newsecret"})
    assert res.status_code == 200
    assert res.json()["data"]["id"] == created["id"]


def test_cannot_disable_or_downgrade_last_admin(client):
    admin = client.get("/api/users", params={"keyword": "admin"}).json()["data"][0]
    disable_res = client.patch(f"/api/users/{admin['id']}", json={"is_active": 0})
    assert disable_res.status_code == 400
    downgrade_res = client.patch(f"/api/users/{admin['id']}", json={"is_admin": 0})
    assert downgrade_res.status_code == 400


def test_invalid_permission_returns_422(client):
    res = client.post("/api/users", json={"username": "analyst", "password": "secret123", "permissions": ["bad"]})
    assert res.status_code == 422
