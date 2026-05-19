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
            s.rollback()
            s.close()

    app.dependency_overrides[get_db] = override_db
    return TestClient(app)


def _seed(client, records):
    """Seed records into the test client's in-memory db."""
    from app.models.database import get_db as real_get_db
    gen = client.app.dependency_overrides[real_get_db]()
    db = next(gen)
    for r in records:
        db.add(r)
    db.commit()
    try:
        next(gen)
    except StopIteration:
        pass


def test_filter_by_brand_raw(client):
    """GET /api/rawdata?brand_raw=SONY returns only matching rows."""
    _seed(client, [
        RawDataRecord(file_id=1, platform="jd", brand_raw="SONY WH-1000XM5", item_name="Sony headphone"),
        RawDataRecord(file_id=1, platform="jd", brand_raw="JBL FLIP6", item_name="JBL speaker"),
    ])
    r = client.get("/api/rawdata?brand_raw=SONY")
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 1
    assert "SONY" in items[0]["brand_raw"]


def test_filter_by_item_name(client):
    """GET /api/rawdata?item_name=speaker returns only matching rows."""
    _seed(client, [
        RawDataRecord(file_id=1, platform="jd", brand_raw="SONY", item_name="Sony headphone premium"),
        RawDataRecord(file_id=1, platform="jd", brand_raw="JBL", item_name="JBL portable speaker"),
    ])
    r = client.get("/api/rawdata?item_name=speaker")
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 1
    assert "speaker" in items[0]["item_name"]
