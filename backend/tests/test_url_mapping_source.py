"""Tests for source/data_year/data_month on item_url_mappings."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.models.database import Base
from app.models.schemas import ItemUrlMapping, ItemUrlMappingOut
from fastapi.testclient import TestClient
from fastapi import FastAPI
from app.models.database import get_db
from app.api.url_mapping_api import router as url_router


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    try:
        yield s
    finally:
        s.rollback()
        s.close()


def test_url_mapping_source_defaults_none(db):
    """source/data_year/data_month default to NULL."""
    m = ItemUrlMapping(platform="jd", item_id="12345", brand_code="SONY")
    db.add(m)
    db.commit()
    db.refresh(m)
    assert m.source is None
    assert m.data_year is None
    assert m.data_month is None


def test_url_mapping_stores_source_and_dims(db):
    """source, data_year, data_month are stored and retrieved; Pydantic round-trip works."""
    m = ItemUrlMapping(
        platform="jd", item_id="99999", brand_code="JBL",
        source="url_import", data_year=2026, data_month=5,
    )
    db.add(m)
    db.commit()
    db.refresh(m)
    assert m.source == "url_import"
    assert m.data_year == 2026
    assert m.data_month == 5
    # Pydantic round-trip
    out = ItemUrlMappingOut.model_validate(m)
    assert out.source == "url_import"
    assert out.data_year == 2026
    assert out.data_month == 5


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
    app.include_router(url_router)
    def override_db():
        yield db
    app.dependency_overrides[get_db] = override_db
    yield TestClient(app), db
    db.close()


def test_list_url_mappings_filter_by_year(client_and_db):
    """GET /url-mappings?year=2026 returns only matching rows."""
    client, db = client_and_db
    db.add(ItemUrlMapping(platform="jd", item_id="aaa", brand_code="SONY", data_year=2026, data_month=3))
    db.add(ItemUrlMapping(platform="jd", item_id="bbb", brand_code="JBL",  data_year=2025, data_month=12))
    db.commit()
    r = client.get("/api/url-mappings?year=2026")
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["item_id"] == "aaa"


def test_list_url_mappings_filter_by_month(client_and_db):
    """GET /url-mappings?month=3 returns only matching rows."""
    client, db = client_and_db
    db.add(ItemUrlMapping(platform="jd", item_id="ccc", brand_code="SONY", data_year=2026, data_month=3))
    db.add(ItemUrlMapping(platform="jd", item_id="ddd", brand_code="JBL",  data_year=2026, data_month=4))
    db.commit()
    r = client.get("/api/url-mappings?month=3")
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["item_id"] == "ccc"


def test_list_url_mappings_source_in_response(client_and_db):
    """source field is returned in the list response."""
    client, db = client_and_db
    db.add(ItemUrlMapping(platform="jd", item_id="eee", brand_code="BOSE", source="manual"))
    db.commit()
    r = client.get("/api/url-mappings")
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["source"] == "manual"


def test_list_url_mappings_uses_headphone_category_for_legacy_domestic_rows(client_and_db):
    client, db = client_and_db
    db.add(ItemUrlMapping(platform="jd", item_id="legacy-jd", brand_code="SONY", source=None))
    db.add(ItemUrlMapping(platform="amazon", item_id="legacy-amazon", brand_code="SONY", source=None))
    db.add(ItemUrlMapping(platform="jd", item_id="manual-jd", brand_code="SONY", source="manual"))
    db.commit()

    r = client.get("/api/url-mappings")

    assert r.status_code == 200
    items = {item["item_id"]: item for item in r.json()["items"]}
    assert items["legacy-jd"]["category_code"] == "headphone"
    assert items["legacy-jd"]["category_name"] == "耳机"
    assert items["legacy-amazon"]["category_code"] is None
    assert items["legacy-amazon"]["category_name"] is None
    assert items["manual-jd"]["category_code"] is None
    assert items["manual-jd"]["category_name"] is None
