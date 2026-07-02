"""Tests for status and operator fields on models table."""
import io

import openpyxl
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.models.database import Base, get_db
from fastapi import FastAPI
from app.api.models_api import router
from app.models.schemas import BrandRecord


@pytest.fixture
def client_and_session():
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
    return TestClient(app), Session


@pytest.fixture
def client(client_and_session):
    client, Session = client_and_session
    with Session() as db:
        db.add_all([
            BrandRecord(brand_code="SONY", brand_name="索尼"),
            BrandRecord(brand_code="JBL", brand_name="JBL"),
            BrandRecord(brand_code="BOSE", brand_name="博士"),
            BrandRecord(brand_code="A", brand_name="A Brand"),
            BrandRecord(brand_code="B", brand_name="B Brand"),
        ])
        db.commit()
    return client


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


def test_create_model_rejects_missing_brand(client_and_session):
    client, _Session = client_and_session

    r = client.post("/api/models", json={"brand_code": "UNKNOWN", "model_code": "M1"})

    assert r.status_code == 400
    assert r.json()["detail"] == "请先创建品牌或选择已有品牌"


def test_create_model_rejects_all_hyphen_placeholder_brand_even_if_seeded(client_and_session):
    client, Session = client_and_session
    with Session() as db:
        db.add(BrandRecord(brand_code="---", brand_name="占位"))
        db.commit()

    r = client.post("/api/models", json={"brand_code": "---", "model_code": "M1"})

    assert r.status_code == 400
    assert r.json()["detail"] == "请先创建品牌或选择已有品牌"


def _model_workbook_bytes(brand_code: str, model_code: str) -> bytes:
    workbook = openpyxl.Workbook()
    model_sheet = workbook.active
    model_sheet.title = "型号"
    model_sheet.append(["品牌码", "型号码", "品类", "品牌名称", "型号名称"])
    model_sheet.append([brand_code, model_code, None, "占位", "占位型号"])
    spec_sheet = workbook.create_sheet("型号规格")
    spec_sheet.append(["品牌码", "型号码", "规格名称", "规格值"])
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def test_import_models_skips_all_hyphen_placeholder_brand(client_and_session):
    client, Session = client_and_session

    r = client.post(
        "/api/models/import",
        files={
            "file": (
                "models.xlsx",
                _model_workbook_bytes("---", "M1"),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )

    assert r.status_code == 200
    assert r.json()["imported_models"] == 0
    with Session() as db:
        assert db.query(BrandRecord).filter_by(brand_code="---").first() is None


def test_models_confirm_skips_all_hyphen_placeholder_brand(client_and_session, monkeypatch, tmp_path):
    client, Session = client_and_session
    upload_dir = tmp_path / "uploads"
    tmp_dir = upload_dir / "tmp"
    tmp_dir.mkdir(parents=True)
    temp_file = tmp_dir / "placeholder.xlsx"
    temp_file.write_bytes(_model_workbook_bytes("---", "M1"))

    import app.api.models_api as models_mod
    monkeypatch.setattr(models_mod, "UPLOAD_DIR", str(upload_dir))

    r = client.post(
        "/api/models/confirm",
        json={
            "temp_file_id": "placeholder.xlsx",
            "mapping": {
                "品牌码": "brand_code",
                "型号码": "model_code",
                "品牌名称": "brand_name",
                "型号名称": "model_name",
            },
            "ignore_columns": [],
            "category_code": "soundbar",
        },
    )

    assert r.status_code == 200
    assert r.json()["models_inserted"] == 0
    with Session() as db:
        assert db.query(BrandRecord).filter_by(brand_code="---").first() is None


def test_create_model_snapshots_brand_name_from_brand(client_and_session):
    client, Session = client_and_session
    with Session() as db:
        db.add(BrandRecord(brand_code="DJI", brand_name="大疆"))
        db.commit()

    r = client.post("/api/models", json={"brand_code": "DJI", "model_code": "OSMO-ACTION-4"})

    assert r.status_code == 200
    data = r.json()
    assert data["brand_code"] == "DJI"
    assert data["brand_name"] == "大疆"
