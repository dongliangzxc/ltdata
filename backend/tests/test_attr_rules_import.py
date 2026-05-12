"""Tests for attr-rules import endpoints (P10)."""
import io
import os
import tempfile
import pytest
import openpyxl
from pathlib import Path
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.database import Base, get_db
from app.models.schemas import Category, ColumnTemplate
from app.api.rules_api import router


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture()
def tmp_upload(tmp_path):
    """Create a temp upload directory and patch UPLOAD_DIR in rules_api."""
    import app.api.rules_api as rules_mod
    original = rules_mod.UPLOAD_DIR
    rules_mod.UPLOAD_DIR = str(tmp_path)
    yield tmp_path
    rules_mod.UPLOAD_DIR = original


@pytest.fixture()
def client(tmp_upload):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    # Pre-seed a category so category_code validation works
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


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _make_minimal_xlsx(headers: list, rows: list = None) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(headers)
    if rows:
        for r in rows:
            ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _upload_headers(client, headers, rows=None):
    """POST to /attr-rules/headers and return response."""
    xlsx_bytes = _make_minimal_xlsx(headers, rows)
    return client.post(
        "/api/rules/attr-rules/headers",
        files={"file": ("test.xlsx", xlsx_bytes,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )


# ─── /attr-rules/headers ─────────────────────────────────────────────────────

def test_attr_rules_headers_returns_columns(client):
    """Headers endpoint returns temp_file_id and columns."""
    resp = _upload_headers(client, ["keyword", "attr_name", "attr_value"])
    assert resp.status_code == 200
    data = resp.json()
    assert "temp_file_id" in data
    assert data["columns"] == ["keyword", "attr_name", "attr_value"]


def test_attr_rules_headers_requires_file(client):
    """Headers endpoint returns 422 if no file uploaded."""
    resp = client.post("/api/rules/attr-rules/headers")
    assert resp.status_code == 422


def test_attr_rules_headers_returns_filename(client):
    """Headers endpoint returns filename in response."""
    resp = _upload_headers(client, ["keyword", "attr_name", "attr_value"])
    assert resp.status_code == 200
    data = resp.json()
    assert "filename" in data
    assert data["filename"] == "test.xlsx"


def test_attr_rules_headers_suggests_template_when_match(client):
    """Headers endpoint suggests existing template when columns match."""
    import app.api.rules_api as rules_mod
    from app.services.import_helper import col_fingerprint

    # Manually add a ColumnTemplate to the DB via the dependency override
    # We'll do this by calling the DB through the override
    app_inner = client.app
    db_gen = app_inner.dependency_overrides[get_db]()
    db = next(db_gen)
    cols = ["keyword", "attr_name", "attr_value"]
    fp = col_fingerprint(cols)
    tmpl = ColumnTemplate(
        name="attr规则模板",
        module="attr",
        mapping={"keyword": "keyword", "attr_name": "attr_name", "attr_value": "attr_value"},
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


# ─── /attr-rules/confirm ─────────────────────────────────────────────────────

def _headers_then_confirm(client, headers, data_rows, mapping, category_code="CAT001", extra_payload=None):
    """Two-step: upload headers, then confirm."""
    # Step 1: upload
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

    return client.post("/api/rules/attr-rules/confirm", json=payload)


def test_attr_rules_confirm_inserts_rows(client):
    """Confirm endpoint inserts rows and returns inserted count."""
    resp = _headers_then_confirm(
        client,
        headers=["keyword", "attr_name", "attr_value"],
        data_rows=[["8GB内存", "内存", "8GB"]],
        mapping={"keyword": "keyword", "attr_name": "attr_name", "attr_value": "attr_value"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "inserted" in data
    assert "skipped" in data
    assert "errors" in data
    assert data["inserted"] == 1
    assert data["skipped"] == 0


def test_attr_rules_confirm_skips_duplicate(client):
    """Confirm skips rows where keyword+attr_name+category_code already exists."""
    mapping = {"keyword": "keyword", "attr_name": "attr_name", "attr_value": "attr_value"}
    headers = ["keyword", "attr_name", "attr_value"]
    rows = [["8GB内存", "内存", "8GB"]]

    # First insert
    resp1 = _headers_then_confirm(client, headers, rows, mapping)
    assert resp1.status_code == 200
    assert resp1.json()["inserted"] == 1

    # Second insert of same data — should be skipped
    resp2 = _headers_then_confirm(client, headers, rows, mapping)
    assert resp2.status_code == 200
    data = resp2.json()
    assert data["skipped"] >= 1
    assert data["inserted"] == 0


def test_attr_rules_confirm_missing_required_field(client):
    """Confirm reports error for rows missing required fields (attr_name not mapped)."""
    resp = _headers_then_confirm(
        client,
        headers=["keyword", "attr_value"],
        data_rows=[["8GB内存", "8GB"]],
        mapping={"keyword": "keyword", "attr_value": "attr_value"},
        # attr_name not in mapping → not in df → field will be empty
    )
    assert resp.status_code == 200
    data = resp.json()
    # Row missing attr_name must be reported as error or skipped
    assert data["errors"] or data["skipped"] >= 1
    assert data["inserted"] == 0


def test_attr_rules_confirm_temp_file_not_found(client):
    """Confirm returns 404 when temp_file_id does not exist."""
    payload = {
        "temp_file_id": "nonexistent-id",
        "mapping": {"keyword": "keyword"},
        "ignore_columns": [],
        "category_code": "CAT001",
    }
    resp = client.post("/api/rules/attr-rules/confirm", json=payload)
    assert resp.status_code == 404


def test_attr_rules_confirm_multiple_rows(client):
    """Confirm inserts multiple valid rows."""
    resp = _headers_then_confirm(
        client,
        headers=["keyword", "attr_name", "attr_value"],
        data_rows=[
            ["8GB内存", "内存", "8GB"],
            ["16GB内存", "内存", "16GB"],
            ["骁龙888", "处理器", "骁龙888"],
        ],
        mapping={"keyword": "keyword", "attr_name": "attr_name", "attr_value": "attr_value"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["inserted"] == 3
    assert data["skipped"] == 0


def test_attr_rules_confirm_column_remapping(client):
    """Confirm supports remapping non-standard column names."""
    resp = _headers_then_confirm(
        client,
        headers=["关键词", "属性名", "属性值"],
        data_rows=[["8GB内存", "内存", "8GB"]],
        mapping={"关键词": "keyword", "属性名": "attr_name", "属性值": "attr_value"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["inserted"] == 1


def test_attr_rules_confirm_optional_fields(client):
    """Confirm handles optional match_type and priority columns."""
    resp = _headers_then_confirm(
        client,
        headers=["keyword", "attr_name", "attr_value", "match_type", "priority"],
        data_rows=[["骁龙", "处理器", "骁龙888", "exact", "10"]],
        mapping={
            "keyword": "keyword",
            "attr_name": "attr_name",
            "attr_value": "attr_value",
            "match_type": "match_type",
            "priority": "priority",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["inserted"] == 1
