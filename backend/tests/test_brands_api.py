"""Tests for brands aggregation and alias management API."""
import pytest
from fastapi.testclient import TestClient
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.models.database import Base, get_db
from app.models.schemas import ModelRecord, BrandAlias


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
    from app.api.brands_api import router
    app = FastAPI()
    app.include_router(router)
    def override_db():
        yield db
    app.dependency_overrides[get_db] = override_db
    yield TestClient(app), db
    db.close()


def test_list_brands_returns_model_count(client_and_db):
    """GET /brands returns each brand with correct model_count."""
    client, db = client_and_db
    db.add(ModelRecord(brand_code="SONY", model_code="WH1000XM5", brand_name="索尼"))
    db.add(ModelRecord(brand_code="SONY", model_code="WF1000XM5", brand_name="索尼"))
    db.add(ModelRecord(brand_code="JBL",  model_code="FLIP6",     brand_name="JBL"))
    db.commit()
    r = client.get("/api/brands")
    assert r.status_code == 200
    brands = r.json()
    sony = next(b for b in brands if b["brand_code"] == "SONY")
    jbl  = next(b for b in brands if b["brand_code"] == "JBL")
    assert sony["model_count"] == 2
    assert jbl["model_count"] == 1


def test_list_brands_returns_alias_count(client_and_db):
    """GET /brands includes alias_count for each brand."""
    client, db = client_and_db
    db.add(ModelRecord(brand_code="SONY", model_code="WH1000XM5", brand_name="索尼"))
    db.add(BrandAlias(alias_name="Sony", brand_code="SONY"))
    db.add(BrandAlias(alias_name="sony", brand_code="SONY"))
    db.commit()
    r = client.get("/api/brands")
    brands = r.json()
    sony = next(b for b in brands if b["brand_code"] == "SONY")
    assert sony["alias_count"] == 2


def test_list_brand_aliases(client_and_db):
    """GET /brands/{brand_code}/aliases returns aliases for that brand only."""
    client, db = client_and_db
    db.add(BrandAlias(alias_name="Sony",    brand_code="SONY"))
    db.add(BrandAlias(alias_name="sony",    brand_code="SONY"))
    db.add(BrandAlias(alias_name="JBL Inc", brand_code="JBL"))
    db.commit()
    r = client.get("/api/brands/SONY/aliases")
    assert r.status_code == 200
    aliases = r.json()
    assert len(aliases) == 2
    assert all(a["brand_code"] == "SONY" for a in aliases)


def test_create_brand_alias(client_and_db):
    """POST /brands/{brand_code}/aliases creates a new alias."""
    client, db = client_and_db
    r = client.post("/api/brands/SONY/aliases", json={"alias_name": "Sony Inc"})
    assert r.status_code == 201
    body = r.json()
    assert body["alias_name"] == "Sony Inc"
    assert body["brand_code"] == "SONY"


def test_delete_brand_alias(client_and_db):
    """DELETE /brands/{brand_code}/aliases/{alias_id} removes the alias."""
    client, db = client_and_db
    alias = BrandAlias(alias_name="Sony", brand_code="SONY")
    db.add(alias)
    db.commit()
    r = client.delete(f"/api/brands/SONY/aliases/{alias.id}")
    assert r.status_code == 204
    assert db.query(BrandAlias).filter(BrandAlias.id == alias.id).first() is None
