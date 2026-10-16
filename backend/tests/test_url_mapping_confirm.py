"""Tests for url-mappings /confirm: NaN 清洗 与 warnings/errors 区分。"""
from types import SimpleNamespace

import openpyxl
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.models.database import Base, get_db
from app.models.schemas import Category, ModelRecord
from app.api.url_mapping_api import router
from app.core.auth_deps import get_current_user


@pytest.fixture()
def client(tmp_path, monkeypatch):
    import app.api.url_mapping_api as url_mod
    monkeypatch.setattr(url_mod, "UPLOAD_DIR", str(tmp_path))
    (tmp_path / "tmp").mkdir()

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False)

    s = Session()
    s.add_all([
        Category(code="CAT001", name="测试品类"),
        Category(code="smart_lock", name="智能门锁"),
    ])
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
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(is_admin=1, category_permissions=None)
    client = TestClient(app)
    client.session_factory = Session
    return client


def _write_tmp(tmp_path, headers, rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(headers)
    for r in rows:
        ws.append(r)
    wb.save(tmp_path / "tmp" / "tid_test.xlsx")
    return "tid"


_MAPPING = {
    "platform": "platform",
    "item_url": "item_url",
    "brand_code": "brand_code",
    "model_code": "model_code",
}


def _payload(temp_file_id, category_code="CAT001"):
    return {
        "temp_file_id": temp_file_id,
        "mapping": _MAPPING,
        "ignore_columns": [],
        "category_code": category_code,
    }


def test_confirm_blank_url_reports_missing_not_nan(client, tmp_path):
    """空/NaN 链接应报 missing required field，而不是 'cannot extract item_id from URL nan'。"""
    tid = _write_tmp(
        tmp_path,
        ["platform", "item_url", "brand_code", "model_code"],
        [["jd", None, "BRAND_A", "MODEL_X"]],
    )
    resp = client.post("/api/url-mappings/confirm", json=_payload(tid))
    assert resp.status_code == 200
    d = resp.json()
    assert d["errors"] and any("missing required field" in e for e in d["errors"])
    assert not any("nan" in e.lower() for e in d["errors"])
    assert "warnings" in d


def test_confirm_category_mismatch_is_warning_not_error(client, tmp_path):
    """型号归属品类与所选品类不一致时应记为提示，不阻塞导入、不进入异常。"""
    s = client.session_factory()
    s.add(ModelRecord(brand_code="VOC", model_code="M108", category_code="smart_lock", status="active"))
    s.commit()
    s.close()

    tid = _write_tmp(
        tmp_path,
        ["platform", "item_url", "brand_code", "model_code"],
        [[
            "dy",
            "https://haohuo.jinritemai.com/ecommerce/trade/detail/index.html?id=3577744407312650971&origin_type=detail_share_v2",
            "VOC",
            "M108",
        ]],
    )
    resp = client.post("/api/url-mappings/confirm", json=_payload(tid, category_code="CAT001"))
    assert resp.status_code == 200
    d = resp.json()
    assert d["inserted"] == 1
    assert d["errors"] == []
    assert any("不一致" in w for w in d["warnings"])
