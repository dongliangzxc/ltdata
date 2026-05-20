"""Tests for phase 6 analytics dashboard API."""
import io
from datetime import datetime

import pandas as pd
import pytest
from fastapi import FastAPI
from sqlalchemy import inspect
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.analytics_api import router
from app.models.analytics_db import AnalyticsBase, PublishedItem, get_analytics_db
from app.models.database import get_db
from app.models.schemas import Base, WorkbenchExportJob


@pytest.fixture(scope="function")
def client_and_dbs(tmp_path, monkeypatch):
    luotu_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    analytics_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(luotu_engine)
    AnalyticsBase.metadata.create_all(analytics_engine)
    with luotu_engine.begin() as conn:
        columns = {col["name"] for col in inspect(conn).get_columns("workbench_export_jobs")}
        if "progress" not in columns:
            conn.exec_driver_sql("ALTER TABLE workbench_export_jobs ADD COLUMN progress SMALLINT DEFAULT 0")
        if "file_token" not in columns:
            conn.exec_driver_sql("ALTER TABLE workbench_export_jobs ADD COLUMN file_token VARCHAR(64)")
        if "finished_at" not in columns:
            conn.exec_driver_sql("ALTER TABLE workbench_export_jobs ADD COLUMN finished_at DATETIME")

    LuotuSession = sessionmaker(bind=luotu_engine)
    AnalyticsSession = sessionmaker(bind=analytics_engine)
    luotu_db = LuotuSession()
    analytics_db = AnalyticsSession()

    from app.core.config import settings
    monkeypatch.setattr(settings, "EXPORT_DIR", str(tmp_path))

    app = FastAPI()
    app.include_router(router)

    def override_luotu_db():
        yield luotu_db

    def override_analytics_db():
        yield analytics_db

    app.dependency_overrides[get_db] = override_luotu_db
    app.dependency_overrides[get_analytics_db] = override_analytics_db

    yield TestClient(app), luotu_db, analytics_db, tmp_path

    luotu_db.close()
    analytics_db.close()


def _seed_published(analytics_db):
    rows = [
        PublishedItem(
            publish_job_id=1,
            clean_job_id=1,
            match_result_id=1,
            platform="jd",
            month=202604,
            item_id="item-sony-1",
            item_name="Sony WH headphone",
            shop_name="Sony Store",
            category_name="耳机",
            category_lv1="影音",
            sales_qty=100,
            corrected_sales_qty=80,
            sales_amount=10000,
            price=100,
            brand_code="SONY",
            brand_name="索尼",
            model_code="WH1000XM5",
            model_name="索尼降噪耳机",
            published_at=datetime(2026, 4, 30, 10, 0, 0),
        ),
        PublishedItem(
            publish_job_id=1,
            clean_job_id=1,
            match_result_id=2,
            platform="tmall",
            month=202604,
            item_id="item-sony-2",
            item_name="Sony WF earbuds",
            shop_name="Sony Store",
            category_name="耳机",
            category_lv1="影音",
            sales_qty=50,
            corrected_sales_qty=None,
            sales_amount=2500,
            price=50,
            brand_code="SONY",
            brand_name="索尼",
            model_code="WF1000XM5",
            model_name="索尼真无线耳机",
            published_at=datetime(2026, 4, 30, 11, 0, 0),
        ),
        PublishedItem(
            publish_job_id=1,
            clean_job_id=1,
            match_result_id=3,
            platform="jd",
            month=202605,
            item_id="item-jbl-1",
            item_name="JBL speaker",
            shop_name="JBL Store",
            category_name="音箱",
            category_lv1="影音",
            sales_qty=30,
            corrected_sales_qty=60,
            sales_amount=9000,
            price=300,
            brand_code="JBL",
            brand_name="JBL",
            model_code="FLIP6",
            model_name="JBL 蓝牙音箱",
            published_at=datetime(2026, 5, 31, 10, 0, 0),
        ),
        PublishedItem(
            publish_job_id=1,
            clean_job_id=1,
            match_result_id=4,
            platform="jd",
            month=202605,
            item_id="item-bose-1",
            item_name="Bose soundbar",
            shop_name="Bose Store",
            category_name=None,
            category_lv1="影音",
            category_lv2="家庭影音",
            category_lv3="回音壁",
            sales_qty=20,
            corrected_sales_qty=None,
            sales_amount=4000,
            price=200,
            brand_code="BOSE",
            brand_name="博士",
            model_code="SOUNDBAR600",
            model_name="Bose 回音壁",
            published_at=datetime(2026, 5, 31, 12, 0, 0),
        ),
    ]
    analytics_db.add_all(rows)
    analytics_db.commit()


def test_filters_return_available_dimensions(client_and_dbs):
    client, _, analytics_db, _ = client_and_dbs
    _seed_published(analytics_db)

    response = client.get("/api/analytics/filters")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["years"] == [2026]
    assert body["months"] == [5, 4]
    assert body["platforms"] == ["jd", "tmall"]
    assert {b["brand_code"] for b in body["brands"]} == {"SONY", "JBL", "BOSE"}
    assert {c["category_name"] for c in body["categories"]} == {"耳机", "音箱", "回音壁"}


def test_summary_defaults_to_model_group_and_corrected_qty_desc(client_and_dbs):
    client, _, analytics_db, _ = client_and_dbs
    _seed_published(analytics_db)

    response = client.get("/api/analytics/summary?year=2026&month=4")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["totals"] == {
        "sales_qty": 150,
        "corrected_sales_qty": 130,
        "sales_amount": 12500.0,
        "avg_price": 83.33,
        "record_count": 2,
    }
    assert body["total"] == 2
    assert [row["dimension_key"] for row in body["rows"]] == ["WH1000XM5", "WF1000XM5"]
    assert body["rows"][0]["corrected_sales_qty"] == 80
    assert body["rows"][1]["corrected_sales_qty"] == 50


def test_summary_supports_page_and_page_size(client_and_dbs):
    client, _, analytics_db, _ = client_and_dbs
    _seed_published(analytics_db)

    response = client.get("/api/analytics/summary?year=2026&month=4&page=1&page_size=1")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["page"] == 1
    assert body["page_size"] == 1
    assert body["total"] > len(body["rows"])
    assert len(body["rows"]) == 1


def test_summary_supports_brand_category_platform_and_keyword_filters(client_and_dbs):
    client, _, analytics_db, _ = client_and_dbs
    _seed_published(analytics_db)

    brand_response = client.get("/api/analytics/summary?group_by=brand&brand=SONY")
    assert brand_response.status_code == 200, brand_response.text
    assert brand_response.json()["rows"][0]["dimension_key"] == "SONY"
    assert brand_response.json()["rows"][0]["record_count"] == 2

    category_response = client.get("/api/analytics/summary?group_by=category&category=音箱")
    assert category_response.status_code == 200, category_response.text
    assert category_response.json()["rows"][0]["dimension_key"] == "音箱"
    assert category_response.json()["rows"][0]["sales_qty"] == 30

    fallback_category_response = client.get("/api/analytics/summary?group_by=category&category=回音壁")
    assert fallback_category_response.status_code == 200, fallback_category_response.text
    assert fallback_category_response.json()["rows"][0]["dimension_key"] == "回音壁"
    assert fallback_category_response.json()["rows"][0]["dimension_name"] == "回音壁"
    assert fallback_category_response.json()["rows"][0]["sales_qty"] == 20

    platform_response = client.get("/api/analytics/summary?group_by=platform&platform=tmall&item_keyword=earbuds")
    assert platform_response.status_code == 200, platform_response.text
    assert platform_response.json()["rows"][0]["dimension_key"] == "tmall"
    assert platform_response.json()["rows"][0]["corrected_sales_qty"] == 50

    model_response = client.get("/api/analytics/summary?model_keyword=FLIP")
    assert model_response.status_code == 200, model_response.text
    assert model_response.json()["rows"][0]["dimension_key"] == "FLIP6"


def test_summary_returns_null_avg_price_when_raw_sales_qty_is_zero(client_and_dbs):
    client, _, analytics_db, _ = client_and_dbs
    analytics_db.add(PublishedItem(
        publish_job_id=1,
        clean_job_id=1,
        match_result_id=1,
        platform="jd",
        month=202604,
        item_id="zero-sales",
        item_name="Zero sales item",
        sales_qty=0,
        corrected_sales_qty=10,
        sales_amount=1000,
        brand_code="ZERO",
        brand_name="Zero",
        model_code="ZERO1",
        model_name="Zero Model",
        category_name="测试",
    ))
    analytics_db.commit()

    response = client.get("/api/analytics/summary?brand=ZERO")

    assert response.status_code == 200, response.text
    assert response.json()["totals"]["avg_price"] is None
    assert response.json()["rows"][0]["avg_price"] is None


def test_get_export_summary_respects_query_filters_and_creates_done_job(client_and_dbs, monkeypatch):
    client, luotu_db, analytics_db, _ = client_and_dbs
    _seed_published(analytics_db)
    captured = {}

    def fake_write_summary_export_file(rows):
        captured["rows"] = rows
        return "summary-token", "summary.xlsx", None

    monkeypatch.setattr("app.api.analytics_api.write_summary_export_file", fake_write_summary_export_file)

    response = client.get("/api/analytics/export/summary?year=2026&month=4&platform=tmall&group_by=platform")

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "done"
    assert response.json()["download_url"] == "/api/analytics/download/summary-token"
    assert [row["dimension_key"] for row in captured["rows"]] == ["tmall"]
    assert captured["rows"][0]["record_count"] == 1
    job = luotu_db.query(WorkbenchExportJob).get(response.json()["job_id"])
    assert job.status == "done"
    assert job.progress == 100
    assert job.file_token == "summary-token"
    assert job.finished_at is not None


def test_get_export_detail_respects_query_filters_and_creates_done_job(client_and_dbs, monkeypatch):
    client, luotu_db, analytics_db, _ = client_and_dbs
    _seed_published(analytics_db)
    captured = {}

    def fake_write_detail_export_file(rows, fields=None):
        captured["rows"] = rows
        captured["fields"] = fields
        return "detail-token", "detail.xlsx", None

    monkeypatch.setattr("app.api.analytics_api.write_detail_export_file", fake_write_detail_export_file)

    response = client.get("/api/analytics/export/detail?year=2026&month=5&brand=JBL&fields=platform,item_name")

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "done"
    assert response.json()["download_url"] == "/api/analytics/download/detail-token"
    assert captured["fields"] == "platform,item_name"
    assert [row["item_id"] for row in captured["rows"]] == ["item-jbl-1"]
    job = luotu_db.query(WorkbenchExportJob).get(response.json()["job_id"])
    assert job.status == "done"
    assert job.progress == 100
    assert job.file_token == "detail-token"
    assert job.finished_at is not None


def test_export_summary_creates_downloadable_excel(client_and_dbs):
    client, _, analytics_db, _ = client_and_dbs
    _seed_published(analytics_db)

    response = client.get("/api/analytics/export/summary?year=2026&month=4&group_by=brand")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "done"
    assert body["download_url"].startswith("/api/analytics/download/")
    download = client.get(body["download_url"])
    assert download.status_code == 200, download.text
    df = pd.read_excel(io.BytesIO(download.content))
    assert len(df) == 1
    assert list(df.columns) == ["维度编码", "维度名称", "原始销量", "修正后销量", "原始销额", "原始均价", "记录数"]
    assert df.iloc[0]["维度编码"] == "SONY"
    assert int(df.iloc[0]["修正后销量"]) == 130


def test_export_summary_exports_all_model_rows_despite_summary_pagination_defaults(client_and_dbs):
    client, _, analytics_db, _ = client_and_dbs
    _seed_published(analytics_db)

    response = client.get("/api/analytics/export/summary?year=2026&month=4&group_by=model")

    assert response.status_code == 200, response.text
    download = client.get(response.json()["download_url"])
    assert download.status_code == 200, download.text
    df = pd.read_excel(io.BytesIO(download.content))
    assert len(df) == 2


def test_export_summary_respects_sort_by_sales_qty_asc(client_and_dbs):
    client, _, analytics_db, _ = client_and_dbs
    _seed_published(analytics_db)

    response = client.get("/api/analytics/export/summary?year=2026&month=4&group_by=model&sort_by=sales_qty_asc")

    assert response.status_code == 200, response.text
    download = client.get(response.json()["download_url"])
    assert download.status_code == 200, download.text
    df = pd.read_excel(io.BytesIO(download.content))
    assert df["维度编码"].tolist() == ["WF1000XM5", "WH1000XM5"]


def test_export_detail_respects_selected_fields(client_and_dbs):
    client, _, analytics_db, _ = client_and_dbs
    _seed_published(analytics_db)

    response = client.get("/api/analytics/export/detail?brand=SONY&fields=platform,item_name,corrected_sales_qty")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "done"
    assert body["download_url"].startswith("/api/analytics/download/")
    download = client.get(body["download_url"])
    assert download.status_code == 200, download.text
    df = pd.read_excel(io.BytesIO(download.content))
    assert len(df) == 2
    assert list(df.columns) == ["平台", "商品名", "修正后销量"]
    assert set(df["商品名"].tolist()) == {"Sony WH headphone", "Sony WF earbuds"}
    assert sorted(int(value) for value in df["修正后销量"].tolist()) == [50, 80]


def test_export_detail_falls_back_to_default_fields_when_fields_are_invalid(client_and_dbs):
    client, _, analytics_db, _ = client_and_dbs
    _seed_published(analytics_db)

    response = client.get("/api/analytics/export/detail?brand=JBL&fields=bad_field")

    assert response.status_code == 200, response.text
    download = client.get(response.json()["download_url"])
    assert download.status_code == 200, download.text
    df = pd.read_excel(io.BytesIO(download.content))
    assert len(df) == 1
    assert "平台" in df.columns
    assert "型号编码" in df.columns
    assert "发布时间" in df.columns


def test_export_failure_marks_job_error(client_and_dbs, monkeypatch):
    client, luotu_db, analytics_db, _ = client_and_dbs
    _seed_published(analytics_db)

    def fail_write_summary_export_file(rows):
        raise RuntimeError("disk full")

    monkeypatch.setattr("app.api.analytics_api.write_summary_export_file", fail_write_summary_export_file)

    with pytest.raises(RuntimeError, match="disk full"):
        client.get("/api/analytics/export/summary?year=2026&month=4")

    job = luotu_db.query(WorkbenchExportJob).one()
    assert job.status == "error"
    assert job.progress == 100
    assert job.error_msg == "disk full"
    assert job.finished_at is not None
