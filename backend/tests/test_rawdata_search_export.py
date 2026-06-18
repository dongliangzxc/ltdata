"""Tests for raw data search filters and export endpoint."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.models.database import Base, get_db
from fastapi import FastAPI
from app.api.rawdata import router
from app.models.schemas import RawDataRecord


@pytest.fixture(scope="function")
def client_and_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    app = FastAPI()
    app.include_router(router)

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    yield TestClient(app), db
    db.close()


def test_filter_by_brand_raw(client_and_db):
    """GET /api/rawdata?brand_raw=SONY returns only matching rows."""
    client, db = client_and_db
    db.add(RawDataRecord(file_id=1, platform="jd", brand_raw="SONY WH-1000XM5", item_name="Sony headphone"))
    db.add(RawDataRecord(file_id=1, platform="jd", brand_raw="JBL FLIP6", item_name="JBL speaker"))
    db.commit()
    r = client.get("/api/rawdata?brand_raw=SONY")
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 1
    assert "SONY" in items[0]["brand_raw"]


def test_filter_by_item_name(client_and_db):
    """GET /api/rawdata?item_name=speaker returns only matching rows."""
    client, db = client_and_db
    db.add(RawDataRecord(file_id=1, platform="jd", brand_raw="SONY", item_name="Sony headphone premium"))
    db.add(RawDataRecord(file_id=1, platform="jd", brand_raw="JBL", item_name="JBL portable speaker"))
    db.commit()
    r = client.get("/api/rawdata?item_name=speaker")
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 1
    assert "speaker" in items[0]["item_name"]


def test_filter_by_price_range_uses_inclusive_bounds(client_and_db):
    client, db = client_and_db
    db.add(RawDataRecord(file_id=1, platform="jd", item_name="Low", price=499.99, sales_qty=1, sales_amount=499.99))
    db.add(RawDataRecord(file_id=1, platform="jd", item_name="Lower bound", price=500, sales_qty=2, sales_amount=1000))
    db.add(RawDataRecord(file_id=1, platform="jd", item_name="Upper bound", price=1000, sales_qty=3, sales_amount=3000))
    db.add(RawDataRecord(file_id=1, platform="jd", item_name="High", price=1000.01, sales_qty=4, sales_amount=4000.04))
    db.commit()

    response = client.get("/api/rawdata?price_min=500&price_max=1000")

    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert [item["item_name"] for item in items] == ["Lower bound", "Upper bound"]


def test_filter_by_multiple_months_returns_matching_rows(client_and_db):
    client, db = client_and_db
    db.add(RawDataRecord(file_id=1, platform="jd", month=202604, item_name="April", sales_qty=1, sales_amount=100, price=100))
    db.add(RawDataRecord(file_id=1, platform="jd", month=202605, item_name="May", sales_qty=2, sales_amount=200, price=100))
    db.add(RawDataRecord(file_id=1, platform="jd", month=202606, item_name="June", sales_qty=3, sales_amount=300, price=100))
    db.commit()

    response = client.get("/api/rawdata?months=202604&months=202606")

    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert [item["item_name"] for item in items] == ["April", "June"]


def test_stats_respects_price_range(client_and_db):
    client, db = client_and_db
    db.add(RawDataRecord(file_id=1, platform="jd", brand_std="SONY", model_std="A", price=400, sales_qty=1, sales_amount=400))
    db.add(RawDataRecord(file_id=1, platform="jd", brand_std="SONY", model_std="B", price=500, sales_qty=2, sales_amount=1000))
    db.add(RawDataRecord(file_id=1, platform="jd", brand_std="JBL", model_std="C", price=1000, sales_qty=3, sales_amount=3000))
    db.commit()

    response = client.get("/api/rawdata/stats?price_min=500&price_max=1000")

    assert response.status_code == 200, response.text
    assert response.json() == {
        "total_qty": 5,
        "total_amount": 4000.0,
        "brand_count": 2,
        "model_count": 2,
    }


def test_stats_respects_multiple_months(client_and_db):
    client, db = client_and_db
    db.add(RawDataRecord(file_id=1, platform="jd", month=202604, brand_std="SONY", model_std="A", sales_qty=1, sales_amount=100))
    db.add(RawDataRecord(file_id=1, platform="jd", month=202605, brand_std="JBL", model_std="B", sales_qty=2, sales_amount=200))
    db.add(RawDataRecord(file_id=1, platform="jd", month=202606, brand_std="BOSE", model_std="C", sales_qty=3, sales_amount=300))
    db.commit()

    response = client.get("/api/rawdata/stats?months=202604&months=202605")

    assert response.status_code == 200, response.text
    assert response.json() == {
        "total_qty": 3,
        "total_amount": 300.0,
        "brand_count": 2,
        "model_count": 2,
    }


def test_export_returns_excel_with_data(client_and_db):
    """GET /api/rawdata/export returns an xlsx file containing seeded rows."""
    client, db = client_and_db
    db.add(RawDataRecord(
        file_id=1, platform="jd",
        brand_raw="SONY WH-1000XM5", item_name="Sony headphone",
        brand_std="SONY", model_std="WH-1000XM5",
        sales_qty=100, sales_amount=89900.0, price=899.0,
    ))
    db.commit()
    r = client.get("/api/rawdata/export")
    assert r.status_code == 200
    assert "spreadsheetml" in r.headers["content-type"]
    import io as _io
    import pandas as _pd
    df = _pd.read_excel(_io.BytesIO(r.content))
    assert len(df) == 1
    assert "品牌原始值" in df.columns


def test_export_filter_by_brand_raw(client_and_db):
    """Export respects brand_raw filter."""
    client, db = client_and_db
    db.add(RawDataRecord(file_id=1, platform="jd", brand_raw="SONY", item_name="Sony"))
    db.add(RawDataRecord(file_id=1, platform="jd", brand_raw="JBL", item_name="JBL"))
    db.commit()
    r = client.get("/api/rawdata/export?brand_raw=SONY")
    assert r.status_code == 200
    import io as _io
    import pandas as _pd
    df = _pd.read_excel(_io.BytesIO(r.content))
    assert len(df) == 1
    assert str(df.iloc[0]["品牌原始值"]) == "SONY"


def test_export_respects_price_range(client_and_db):
    client, db = client_and_db
    db.add(RawDataRecord(file_id=1, platform="jd", item_name="Low", price=499.99))
    db.add(RawDataRecord(file_id=1, platform="jd", item_name="Inside", price=500))
    db.add(RawDataRecord(file_id=1, platform="jd", item_name="High", price=1000.01))
    db.commit()

    response = client.get("/api/rawdata/export?price_min=500&price_max=1000")

    assert response.status_code == 200, response.text
    import io as _io
    import pandas as _pd
    df = _pd.read_excel(_io.BytesIO(response.content))
    assert df["宝贝名称"].tolist() == ["Inside"]


def test_export_respects_multiple_months(client_and_db):
    client, db = client_and_db
    db.add(RawDataRecord(file_id=1, platform="jd", month=202604, item_name="April"))
    db.add(RawDataRecord(file_id=1, platform="jd", month=202605, item_name="May"))
    db.add(RawDataRecord(file_id=1, platform="jd", month=202606, item_name="June"))
    db.commit()

    response = client.get("/api/rawdata/export?months=202604&months=202606")

    assert response.status_code == 200, response.text
    import io as _io
    import pandas as _pd
    df = _pd.read_excel(_io.BytesIO(response.content))
    assert df["宝贝名称"].tolist() == ["April", "June"]


def test_export_rejects_when_row_limit_exceeded(client_and_db, monkeypatch):
    client, db = client_and_db
    monkeypatch.setattr("app.api.rawdata.MAX_SYNC_EXPORT_ROWS", 1)
    db.add(RawDataRecord(file_id=1, platform="jd", item_name="One"))
    db.add(RawDataRecord(file_id=1, platform="jd", item_name="Two"))
    db.commit()

    response = client.get("/api/rawdata/export")

    assert response.status_code == 400
    assert "原始数据导出数据量过大" in response.json()["detail"]
