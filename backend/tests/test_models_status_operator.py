"""Tests for status and operator fields on models table."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.models.database import Base, get_db
from fastapi import FastAPI
from app.api.models_api import router


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


def test_create_model_status_defaults_to_active(client):
    r = client.post("/api/models", json={"brand_code": "SONY", "model_code": "XM5"})
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "active"
    assert data["operator"] is None


def test_create_model_with_status_and_operator(client):
    r = client.post("/api/models", json={
        "brand_code": "JBL", "model_code": "FLIP6",
        "status": "inactive", "operator": "alice",
    })
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "inactive"
    assert data["operator"] == "alice"


def test_update_model_changes_status_and_operator(client):
    create_r = client.post("/api/models", json={"brand_code": "BOSE", "model_code": "QC45"})
    model_id = create_r.json()["id"]

    r = client.put(f"/api/models/{model_id}", json={
        "brand_code": "BOSE", "model_code": "QC45",
        "status": "inactive", "operator": "bob",
    })
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "inactive"
    assert data["operator"] == "bob"


def test_list_models_filter_by_status(client):
    client.post("/api/models", json={"brand_code": "A", "model_code": "M1", "status": "active"})
    client.post("/api/models", json={"brand_code": "B", "model_code": "M2", "status": "inactive"})

    r = client.get("/api/models?status=active")
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["brand_code"] == "A"

    r2 = client.get("/api/models?status=inactive")
    assert r2.status_code == 200
    items2 = r2.json()["items"]
    assert len(items2) == 1
    assert items2[0]["brand_code"] == "B"
