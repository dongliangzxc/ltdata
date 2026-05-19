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
