import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.main as main_module
from app.core.security import hash_password
from app.models import database as database_module
from app.models.schemas import Base, User


@pytest.fixture
def client(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    session.add_all(
        [
            User(username="admin", hashed_password=hash_password("luotu123"), name="管理员", is_admin=1, permissions=[]),
            User(username="data_user", hashed_password=hash_password("secret123"), permissions=["data_management"]),
            User(username="disabled", hashed_password=hash_password("secret123"), is_active=0, permissions=["data_management"]),
        ]
    )
    session.commit()
    session.close()

    monkeypatch.setattr(main_module, "SessionLocal", Session)
    monkeypatch.setattr(database_module, "SessionLocal", Session)

    yield TestClient(main_module.app)
    Base.metadata.drop_all(engine)


def login(client, username="admin", password="luotu123"):
    res = client.post("/api/auth/login", json={"username": username, "password": password})
    assert res.status_code == 200
    return res.json()["data"]["access_token"]


def test_login_returns_user_profile(client):
    token = login(client)
    assert token
    me_res = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me_res.status_code == 200
    data = me_res.json()["data"]
    assert data["username"] == "admin"
    assert data["is_admin"] == 1
    assert data["permissions"] == []


def test_disabled_user_cannot_login(client):
    res = client.post("/api/auth/login", json={"username": "disabled", "password": "secret123"})
    assert res.status_code == 401


def test_normal_user_can_access_granted_directory_api(client):
    token = login(client, "data_user", "secret123")
    res = client.get("/api/categories", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code != 403


def test_normal_user_cannot_access_ungranted_directory_api(client):
    token = login(client, "data_user", "secret123")
    res = client.get("/api/match/summary", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 403


def test_normal_user_cannot_access_user_management(client):
    token = login(client, "data_user", "secret123")
    res = client.get("/api/users", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 403


def test_missing_token_returns_401(client):
    res = client.get("/api/categories")
    assert res.status_code == 401
