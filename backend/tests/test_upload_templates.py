"""
Tests for column template CRUD API.
Uses SQLite in-memory + FastAPI TestClient.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.models.database import get_db
from app.models.schemas import Base
from fastapi import FastAPI
from app.api.upload_templates_api import router


@pytest.fixture()
def client():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    def override_get_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def test_create_and_list_template(client):
    """Creating a template shows up in the list"""
    payload = {
        "name": "测试模板",
        "platform": "jd",
        "mapping": {"宝贝ID": "item_id", "月": "month"},
        "ignore_columns": [],
    }
    resp = client.post("/api/upload/templates", json=payload)
    assert resp.status_code == 200
    created = resp.json()
    assert created["name"] == "测试模板"
    assert created["is_builtin"] == 0

    list_resp = client.get("/api/upload/templates")
    assert list_resp.status_code == 200
    assert any(t["id"] == created["id"] for t in list_resp.json())


def test_update_template(client):
    """Can rename a template"""
    created = client.post("/api/upload/templates", json={
        "name": "原名", "mapping": {"月": "month"}, "ignore_columns": []
    }).json()
    resp = client.put(f"/api/upload/templates/{created['id']}", json={
        "name": "新名", "mapping": {"月": "month"}, "ignore_columns": []
    })
    assert resp.status_code == 200
    assert resp.json()["name"] == "新名"


def test_delete_template(client):
    """Can delete a non-builtin template"""
    created = client.post("/api/upload/templates", json={
        "name": "待删除", "mapping": {"月": "month"}, "ignore_columns": []
    }).json()
    resp = client.delete(f"/api/upload/templates/{created['id']}")
    assert resp.status_code == 200

    list_resp = client.get("/api/upload/templates")
    assert not any(t["id"] == created["id"] for t in list_resp.json())


def test_delete_builtin_template_forbidden(client):
    """Built-in template cannot be deleted — returns 403"""
    from app.models.schemas import ColumnTemplate

    # Insert a built-in template directly
    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    builtin = ColumnTemplate(name="内置", mapping={"月": "month"}, is_builtin=1)
    db.add(builtin)
    db.commit()
    db.refresh(builtin)

    resp = client.delete(f"/api/upload/templates/{builtin.id}")
    assert resp.status_code == 403
