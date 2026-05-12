"""Tests for models import P10 headers/confirm endpoints."""
import io
import os
import tempfile
import openpyxl
import pytest
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.models.database import Base, get_db
from app.models.schemas import Category
from app.api.models_api import router


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture()
def tmp_upload(tmp_path):
    """Create a temp upload directory and patch UPLOAD_DIR in models_api."""
    import app.api.models_api as models_mod
    original = models_mod.UPLOAD_DIR
    models_mod.UPLOAD_DIR = str(tmp_path)
    yield tmp_path
    models_mod.UPLOAD_DIR = original


@pytest.fixture()
def client(tmp_upload):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    # Pre-seed a category
    s = Session()
    s.add(Category(code="CAT001", name="测试品类"))
    s.commit()
    s.close()

    def override_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = override_db
    return TestClient(app)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _make_xlsx(headers, rows=None, sheet_name="Sheet") -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet_name
    ws.append(headers)
    for r in (rows or []):
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _upload_headers(client, headers, rows=None):
    """POST to /api/models/headers and return response."""
    xlsx_bytes = _make_xlsx(headers, rows)
    return client.post(
        "/api/models/headers",
        files={"file": ("test.xlsx", xlsx_bytes,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )


def _headers_then_confirm(client, headers, data_rows, mapping, category_code="CAT001", extra_payload=None):
    """Two-step: upload headers, then confirm."""
    resp = _upload_headers(client, headers, data_rows)
    assert resp.status_code == 200
    temp_file_id = resp.json()["temp_file_id"]

    payload = {
        "temp_file_id": temp_file_id,
        "mapping": mapping,
        "ignore_columns": [],
        "category_code": category_code,
    }
    if extra_payload:
        payload.update(extra_payload)

    return client.post("/api/models/confirm", json=payload)


# ─── headers ──────────────────────────────────────────────────────────────────

def test_models_headers_returns_columns(client):
    resp = _upload_headers(client, ["brand_code", "model_code", "brand_name"])
    assert resp.status_code == 200
    data = resp.json()
    assert "temp_file_id" in data
    assert "brand_code" in data["columns"]
    assert "model_code" in data["columns"]


def test_models_headers_requires_file(client):
    resp = client.post("/api/models/headers")
    assert resp.status_code == 422


def test_models_headers_returns_filename(client):
    resp = _upload_headers(client, ["brand_code", "model_code"])
    assert resp.status_code == 200
    data = resp.json()
    assert "filename" in data
    assert data["filename"] == "test.xlsx"


def test_models_headers_suggests_template_when_match(client):
    """Headers endpoint suggests existing template when columns match."""
    from app.services.import_helper import col_fingerprint
    from app.models.schemas import ColumnTemplate

    # Insert matching template into DB
    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    cols = ["brand_code", "model_code"]
    fp = col_fingerprint(cols)
    tmpl = ColumnTemplate(
        name="型号模板",
        module="model",
        mapping={"brand_code": "brand_code", "model_code": "model_code"},
        ignore_columns=[],
        col_fingerprint=fp,
    )
    db.add(tmpl)
    db.commit()
    db.close()

    resp = _upload_headers(client, cols)
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("suggested_template") is not None
    assert data["match_score"] == 100


# ─── confirm ──────────────────────────────────────────────────────────────────

def test_models_confirm_inserts_model(client):
    resp = _headers_then_confirm(
        client,
        headers=["brand_code", "model_code"],
        data_rows=[["BRAND_A", "MODEL_X"]],
        mapping={"brand_code": "brand_code", "model_code": "model_code"},
        category_code="CAT001",
    )
    assert resp.status_code == 200
    d = resp.json()
    assert "models_inserted" in d
    assert "errors" in d
    assert d["models_inserted"] == 1


def test_models_confirm_category_fallback(client):
    """category_code from payload is used when Excel row has no category_code col."""
    resp = _headers_then_confirm(
        client,
        headers=["brand_code", "model_code"],
        data_rows=[["BR1", "M1"]],
        mapping={"brand_code": "brand_code", "model_code": "model_code"},
        category_code="FALLBACK_CAT",
    )
    assert resp.status_code == 200
    d = resp.json()
    assert d["models_inserted"] == 1


def test_models_confirm_missing_required_field(client):
    """Rows missing brand_code or model_code are counted as errors."""
    resp = _headers_then_confirm(
        client,
        headers=["brand_code"],
        data_rows=[["BRAND_A"]],
        mapping={"brand_code": "brand_code"},
        category_code="CAT001",
    )
    assert resp.status_code == 200
    d = resp.json()
    assert d["errors"] or d["models_inserted"] == 0


def test_models_confirm_upserts_on_duplicate(client):
    """Importing the same brand_code+model_code updates (models_updated) instead of inserting."""
    mapping = {"brand_code": "brand_code", "model_code": "model_code"}
    headers = ["brand_code", "model_code"]
    rows = [["BRAND_A", "MODEL_Y"]]

    resp1 = _headers_then_confirm(client, headers, rows, mapping)
    assert resp1.status_code == 200
    assert resp1.json()["models_inserted"] == 1

    resp2 = _headers_then_confirm(client, headers, rows, mapping)
    assert resp2.status_code == 200
    d2 = resp2.json()
    assert d2["models_updated"] == 1
    assert d2["models_inserted"] == 0


def test_models_confirm_temp_file_not_found(client):
    """Confirm returns 404 when temp_file_id does not exist."""
    payload = {
        "temp_file_id": "nonexistent-uuid",
        "mapping": {"brand_code": "brand_code", "model_code": "model_code"},
        "ignore_columns": [],
        "category_code": "CAT001",
    }
    resp = client.post("/api/models/confirm", json=payload)
    assert resp.status_code == 404


def test_models_confirm_multiple_rows(client):
    """Confirm inserts multiple valid rows."""
    resp = _headers_then_confirm(
        client,
        headers=["brand_code", "model_code"],
        data_rows=[
            ["BRAND_A", "MODEL_1"],
            ["BRAND_A", "MODEL_2"],
            ["BRAND_B", "MODEL_3"],
        ],
        mapping={"brand_code": "brand_code", "model_code": "model_code"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["models_inserted"] == 3
    assert data["errors"] == []


def test_models_confirm_column_remapping(client):
    """Confirm supports remapping non-standard column names."""
    resp = _headers_then_confirm(
        client,
        headers=["品牌码", "型号码"],
        data_rows=[["SONY", "WH1000XM5"]],
        mapping={"品牌码": "brand_code", "型号码": "model_code"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["models_inserted"] == 1
