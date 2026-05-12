"""Tests for url-mappings import P10 headers/confirm endpoints."""
import io, os, tempfile, openpyxl
from pathlib import Path
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from app.main import app
from app.core.security import create_access_token

client = TestClient(app)

def _auth():
    token = create_access_token("testuser")
    return {"Authorization": f"Bearer {token}"}


def _xlsx(headers, rows=None) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(headers)
    for r in (rows or []):
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _write_tmp_file(headers, rows):
    """Write an xlsx into a tmp subdir, returning (upload_dir, temp_file_id, full_path)."""
    upload_dir = tempfile.mkdtemp()
    tmp_subdir = os.path.join(upload_dir, "tmp")
    os.makedirs(tmp_subdir)
    temp_file_id = "test-file-id"
    fname = f"{temp_file_id}_test.xlsx"
    full_path = os.path.join(tmp_subdir, fname)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(headers)
    for r in rows:
        ws.append(r)
    wb.save(full_path)
    return upload_dir, temp_file_id, full_path


# ─── headers ─────────────────────────────────────────────────────────────────

def test_url_headers_returns_columns():
    data = _xlsx(["platform", "item_url", "brand_code", "model_code"])
    with patch("app.api.url_mapping_api.save_tmp_file") as ms, \
         patch("app.api.url_mapping_api.read_columns") as mc, \
         patch("app.api.url_mapping_api.find_best_template") as mt, \
         patch("app.api.url_mapping_api.get_db") as md:
        ms.return_value = ("tid1", MagicMock(), "test.xlsx")
        mc.return_value = ["platform", "item_url", "brand_code", "model_code"]
        mt.return_value = (None, 0)
        md.return_value = iter([MagicMock()])
        resp = client.post(
            "/api/url-mappings/headers",
            files={"file": ("test.xlsx", data, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            headers=_auth(),
        )
    assert resp.status_code == 200
    d = resp.json()
    assert d["temp_file_id"] == "tid1"
    assert "platform" in d["columns"]


def test_url_headers_requires_file():
    resp = client.post("/api/url-mappings/headers", headers=_auth())
    assert resp.status_code == 422


# ─── confirm ─────────────────────────────────────────────────────────────────

def test_url_confirm_inserts_mapping():
    upload_dir, temp_file_id, full_path = _write_tmp_file(
        ["platform", "item_url", "brand_code", "model_code"],
        [["jd", "https://item.jd.com/12345.html", "BRAND_A", "MODEL_X"]],
    )
    payload = {
        "temp_file_id": temp_file_id,
        "mapping": {
            "platform": "platform",
            "item_url": "item_url",
            "brand_code": "brand_code",
            "model_code": "model_code",
        },
        "ignore_columns": [],
        "category_code": "CAT001",
    }
    with patch("app.api.url_mapping_api.UPLOAD_DIR", upload_dir), \
         patch("app.api.url_mapping_api.get_db") as mock_db:
        mock_session = MagicMock()
        mock_model = MagicMock()
        mock_model.id = 99
        mock_model.category_code = "CAT001"
        mock_session.query.return_value.filter.return_value.first.side_effect = [
            mock_model,  # model lookup
            None,        # existing mapping lookup
        ]
        mock_db.return_value = iter([mock_session])
        resp = client.post("/api/url-mappings/confirm", json=payload, headers=_auth())
    assert resp.status_code == 200
    d = resp.json()
    assert "inserted" in d and "updated" in d and "errors" in d


def test_url_confirm_missing_required():
    """Rows missing platform/item_url/brand_code/model_code go to errors."""
    upload_dir, temp_file_id, full_path = _write_tmp_file(
        ["platform", "brand_code"],
        [["jd", "BRAND_A"]],
    )
    payload = {
        "temp_file_id": temp_file_id,
        "mapping": {"platform": "platform", "brand_code": "brand_code"},
        "ignore_columns": [],
        "category_code": "CAT001",
    }
    with patch("app.api.url_mapping_api.UPLOAD_DIR", upload_dir), \
         patch("app.api.url_mapping_api.get_db") as mock_db:
        mock_db.return_value = iter([MagicMock()])
        resp = client.post("/api/url-mappings/confirm", json=payload, headers=_auth())
    assert resp.status_code == 200
    d = resp.json()
    assert d["errors"]


def test_url_confirm_model_not_found():
    """Row where (brand_code, model_code) not in models table goes to errors."""
    upload_dir, temp_file_id, full_path = _write_tmp_file(
        ["platform", "item_url", "brand_code", "model_code"],
        [["jd", "https://item.jd.com/99.html", "UNKNOWN", "NOPE"]],
    )
    payload = {
        "temp_file_id": temp_file_id,
        "mapping": {
            "platform": "platform",
            "item_url": "item_url",
            "brand_code": "brand_code",
            "model_code": "model_code",
        },
        "ignore_columns": [],
        "category_code": "CAT001",
    }
    with patch("app.api.url_mapping_api.UPLOAD_DIR", upload_dir), \
         patch("app.api.url_mapping_api.get_db") as mock_db:
        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = None  # model not found
        mock_db.return_value = iter([mock_session])
        resp = client.post("/api/url-mappings/confirm", json=payload, headers=_auth())
    assert resp.status_code == 200
    d = resp.json()
    assert d["errors"]
