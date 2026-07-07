"""Tests for brands aggregation and alias management API."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.models.database import Base, get_db
from app.models.schemas import ModelRecord, BrandAlias, BrandRecord


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


def test_brand_record_can_be_created(client_and_db):
    from app.models.schemas import BrandRecord

    _client, db = client_and_db
    brand = BrandRecord(brand_code="SONY", brand_name="索尼")
    db.add(brand)
    db.commit()

    saved = db.query(BrandRecord).filter_by(brand_code="SONY").one()
    assert saved.brand_code == "SONY"
    assert saved.brand_name == "索尼"
    assert saved.status == "active"


def test_brand_backfills_use_trimmed_brand_code():
    """Migration and init SQL backfills collapse whitespace-only brand_code variants."""
    migration_sql = Path(
        __file__,
        "..",
        "..",
        "alembic",
        "versions",
        "p29a1b2c3d4e5_create_brands_table.py",
    ).resolve().read_text()
    init_sql = Path(__file__, "..", "..", "..", "sql", "init.sql").resolve().read_text()

    assert "TRIM(m.brand_code) AS brand_code" in migration_sql
    assert "GROUP BY TRIM(m.brand_code)" in migration_sql
    assert "TRIM(m.brand_code) AS brand_code" in init_sql
    assert "GROUP BY TRIM(m.brand_code)" in init_sql


def test_brand_backfills_exclude_all_hyphen_placeholder_codes():
    """Migration and init SQL backfills must skip any all-hyphen brand_code, e.g. '---'."""
    migration_sql = Path(
        __file__,
        "..",
        "..",
        "alembic",
        "versions",
        "p29a1b2c3d4e5_create_brands_table.py",
    ).resolve().read_text()
    init_sql = Path(__file__, "..", "..", "..", "sql", "init.sql").resolve().read_text()
    placeholder_guard = "REPLACE(TRIM(m.brand_code), '-', '') <> ''"

    assert migration_sql.count(placeholder_guard) == 2
    assert placeholder_guard in init_sql


def test_mysql_migration_updated_at_matches_init_sql():
    """Alembic-created MySQL brands table must include ON UPDATE CURRENT_TIMESTAMP."""
    migration_sql = Path(
        __file__,
        "..",
        "..",
        "alembic",
        "versions",
        "p29a1b2c3d4e5_create_brands_table.py",
    ).resolve().read_text()

    assert "ON UPDATE CURRENT_TIMESTAMP" in migration_sql


def test_list_brands_returns_model_count(client_and_db):
    """GET /brands returns brands from brands table with correct model_count."""
    client, db = client_and_db
    db.add(BrandRecord(brand_code="SONY", brand_name="索尼"))
    db.add(BrandRecord(brand_code="JBL", brand_name="JBL"))
    db.add(BrandRecord(brand_code="EMPTY", brand_name="空品牌"))
    db.add(ModelRecord(brand_code="SONY", model_code="WH1000XM5", brand_name="索尼"))
    db.add(ModelRecord(brand_code="SONY", model_code="WF1000XM5", brand_name="索尼"))
    db.add(ModelRecord(brand_code="JBL",  model_code="FLIP6",     brand_name="JBL"))
    db.commit()

    r = client.get("/api/brands")

    assert r.status_code == 200
    brands = r.json()
    sony = next(b for b in brands if b["brand_code"] == "SONY")
    jbl = next(b for b in brands if b["brand_code"] == "JBL")
    empty = next(b for b in brands if b["brand_code"] == "EMPTY")
    assert sony["model_count"] == 2
    assert jbl["model_count"] == 1
    assert empty["model_count"] == 0


def test_list_brands_counts_models_with_trimmed_brand_code(client_and_db):
    """GET /brands counts legacy model brand_code values under trimmed brand master codes."""
    client, db = client_and_db
    db.add(BrandRecord(brand_code="SONY", brand_name="索尼"))
    db.add(ModelRecord(brand_code=" SONY ", model_code="WH1000XM5", brand_name="索尼"))
    db.commit()

    r = client.get("/api/brands")

    assert r.status_code == 200
    brands = r.json()
    sony = next(b for b in brands if b["brand_code"] == "SONY")
    assert sony["model_count"] == 1


def test_list_brands_returns_alias_count(client_and_db):
    """GET /brands includes alias_count for each brand."""
    client, db = client_and_db
    db.add(BrandRecord(brand_code="SONY", brand_name="索尼"))
    db.add(BrandAlias(alias_name="Sony", brand_code="SONY"))
    db.add(BrandAlias(alias_name="sony", brand_code="SONY"))
    db.commit()

    r = client.get("/api/brands")

    assert r.status_code == 200
    brands = r.json()
    sony = next(b for b in brands if b["brand_code"] == "SONY")
    assert sony["alias_count"] == 2


def test_create_brand(client_and_db):
    client, db = client_and_db

    r = client.post("/api/brands", json={"brand_code": " DJI ", "brand_name": " 大疆 "})

    assert r.status_code == 201
    body = r.json()
    assert body["brand_code"] == "DJI"
    assert body["brand_name"] == "大疆"
    # 首次创建时把 brand_name 锁定为 original_brand_name
    assert body["original_brand_name"] == "大疆"
    assert body["category_codes"] == []
    assert body["model_count"] == 0
    assert body["alias_count"] == 0
    saved = db.query(BrandRecord).filter_by(brand_code="DJI").one()
    assert saved.brand_name == "大疆"
    assert saved.original_brand_name == "大疆"


def test_list_brands_returns_original_name_and_categories(client_and_db):
    """GET /brands 返回原始品牌名与型号覆盖的品类码列表。"""
    client, db = client_and_db
    db.add(BrandRecord(brand_code="SONY", brand_name="索尼(修改后)", original_brand_name="索尼"))
    db.add(ModelRecord(brand_code="SONY", model_code="WH1000XM5", category_code="EARPHONE"))
    db.add(ModelRecord(brand_code="SONY", model_code="A7M4",      category_code="CAMERA"))
    # 同品类下的两个型号应去重
    db.add(ModelRecord(brand_code="SONY", model_code="WF1000XM5", category_code="EARPHONE"))
    db.commit()

    r = client.get("/api/brands")

    assert r.status_code == 200
    sony = next(b for b in r.json() if b["brand_code"] == "SONY")
    assert sony["brand_name"] == "索尼(修改后)"
    assert sony["original_brand_name"] == "索尼"
    # 品类码按升序返回
    assert sony["category_codes"] == ["CAMERA", "EARPHONE"]


def test_create_brand_rejects_duplicate_code(client_and_db):
    client, db = client_and_db
    db.add(BrandRecord(brand_code="SONY", brand_name="索尼"))
    db.commit()

    r = client.post("/api/brands", json={"brand_code": "SONY", "brand_name": "Sony"})

    assert r.status_code == 409
    assert r.json()["detail"] == "品牌已存在，可直接选择"


def test_create_brand_rejects_duplicate_code_from_integrity_error(client_and_db, monkeypatch):
    """POST /brands handles duplicate races that surface only at commit time."""
    client, db = client_and_db

    def raise_integrity_error():
        raise IntegrityError("INSERT INTO brands", {}, Exception("duplicate"))

    monkeypatch.setattr(db, "commit", raise_integrity_error)

    r = client.post("/api/brands", json={"brand_code": "SONY", "brand_name": "Sony"})

    assert r.status_code == 409
    assert r.json()["detail"] == "品牌已存在，可直接选择"


@pytest.mark.parametrize("brand_code", ["", " ", "-", "--", "---"])
def test_create_brand_rejects_placeholder_codes(client_and_db, brand_code):
    client, _db = client_and_db

    r = client.post("/api/brands", json={"brand_code": brand_code, "brand_name": "占位"})

    assert r.status_code == 400
    assert r.json()["detail"] == "品牌码不能为空或占位符"


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
