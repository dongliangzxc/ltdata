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
    brands = r.json()["items"]
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
    brands = r.json()["items"]
    sony = next(b for b in brands if b["brand_code"] == "SONY")
    assert sony["model_count"] == 1


def test_list_brands_returns_paginated_response(client_and_db):
    client, db = client_and_db
    db.add(BrandRecord(brand_code="A", brand_name="A name"))
    db.add(BrandRecord(brand_code="B", brand_name="B name"))
    db.add(BrandRecord(brand_code="C", brand_name="C name"))
    db.commit()

    r = client.get("/api/brands", params={"page": 2, "page_size": 1})

    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 3
    assert body["page"] == 2
    assert body["page_size"] == 1
    assert [item["brand_code"] for item in body["items"]] == ["B"]


def test_list_brands_filters_keyword_on_backend(client_and_db):
    client, db = client_and_db
    db.add(BrandRecord(brand_code="SONY", brand_name="索尼", original_brand_name="Sony Upload"))
    db.add(BrandRecord(brand_code="BOSE", brand_name="博士", original_brand_name="Bose Upload"))
    db.add(BrandRecord(brand_code="MODEL_ONLY", brand_name=None, original_brand_name=None))
    db.add(ModelRecord(brand_code="MODEL_ONLY", model_code="M1", brand_name="Model Brand Hit"))
    db.commit()

    r = client.get("/api/brands", params={"keyword": "sony"})

    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert [item["brand_code"] for item in body["items"]] == ["SONY"]

    r = client.get("/api/brands", params={"keyword": "model brand"})

    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert [item["brand_code"] for item in body["items"]] == ["MODEL_ONLY"]


def test_list_brands_filters_category_on_backend(client_and_db):
    client, db = client_and_db
    db.add(BrandRecord(brand_code="SONY", brand_name="索尼"))
    db.add(BrandRecord(brand_code="BOSE", brand_name="博士"))
    db.add(ModelRecord(brand_code="SONY", model_code="S1", category_code="HEADPHONE"))
    db.add(ModelRecord(brand_code="BOSE", model_code="B1", category_code="SPEAKER"))
    db.commit()

    r = client.get("/api/brands", params={"category_code": "HEADPHONE"})

    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert [item["brand_code"] for item in body["items"]] == ["SONY"]


def test_list_brands_falls_back_original_name_from_models(client_and_db):
    """GET /brands fills uploaded brand name from model metadata when brand metadata is blank."""
    client, db = client_and_db
    db.add(BrandRecord(brand_code="DJI", brand_name=None, original_brand_name=None))
    db.add(ModelRecord(brand_code=" DJI ", model_code="OSMO-POCKET-3", brand_name="大疆"))
    db.commit()

    r = client.get("/api/brands")

    assert r.status_code == 200
    brands = r.json()["items"]
    dji = next(b for b in brands if b["brand_code"] == "DJI")
    assert dji["original_brand_name"] == "大疆"
    assert dji["brand_name"] == "大疆"


def test_list_brands_returns_alias_count(client_and_db):
    """GET /brands includes alias_count for each brand."""
    client, db = client_and_db
    db.add(BrandRecord(brand_code="SONY", brand_name="索尼"))
    db.add(BrandAlias(alias_name="Sony", brand_code="SONY"))
    db.add(BrandAlias(alias_name="sony", brand_code="SONY"))
    db.commit()

    r = client.get("/api/brands")

    assert r.status_code == 200
    brands = r.json()["items"]
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
    sony = next(b for b in r.json()["items"] if b["brand_code"] == "SONY")
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


def test_update_brand_alias(client_and_db):
    client, db = client_and_db
    db.add(BrandRecord(brand_code="SONY", brand_name="索尼"))
    db.add(BrandAlias(alias_name="Sony", brand_code="SONY"))
    db.commit()

    resp = client.patch("/api/brands/SONY/aliases/1", json={"alias_name": "SONY INC"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["alias_name"] == "SONY INC"
    assert body["brand_code"] == "SONY"
    assert db.query(BrandAlias).filter(BrandAlias.id == 1).one().alias_name == "SONY INC"
    assert client.get("/api/brands").json()["items"][0]["alias_count"] == 1


def test_update_brand_alias_rejects_duplicate(client_and_db):
    client, db = client_and_db
    db.add(BrandRecord(brand_code="SONY", brand_name="索尼"))
    db.add(BrandRecord(brand_code="BOSE", brand_name="博士"))
    db.add(BrandAlias(alias_name="Sony", brand_code="SONY"))
    db.add(BrandAlias(alias_name="BOSE", brand_code="BOSE"))
    db.commit()

    resp = client.patch("/api/brands/SONY/aliases/1", json={"alias_name": "BOSE"})

    assert resp.status_code == 409
    assert resp.json()["detail"] == "别名 'BOSE' 已存在"


def test_update_brand_alias_rejects_missing_or_foreign_alias(client_and_db):
    client, db = client_and_db
    db.add(BrandRecord(brand_code="SONY", brand_name="索尼"))
    db.add(BrandRecord(brand_code="BOSE", brand_name="博士"))
    db.add(BrandAlias(alias_name="Sony", brand_code="SONY"))
    db.add(BrandAlias(alias_name="Bose", brand_code="BOSE"))
    db.commit()

    missing = client.patch("/api/brands/SONY/aliases/999", json={"alias_name": "SONY INC"})
    foreign = client.patch("/api/brands/SONY/aliases/2", json={"alias_name": "SONY INC"})

    assert missing.status_code == 404
    assert foreign.status_code == 404


def test_update_brand_alias_rejects_blank_alias(client_and_db):
    client, db = client_and_db
    db.add(BrandRecord(brand_code="SONY", brand_name="索尼"))
    db.add(BrandAlias(alias_name="Sony", brand_code="SONY"))
    db.commit()

    resp = client.patch("/api/brands/SONY/aliases/1", json={"alias_name": "   "})

    assert resp.status_code == 400
    assert resp.json()["detail"] == "别名不能为空"


def test_update_brand_name_changes_only_edited_name(client_and_db):
    client, db = client_and_db
    brand = BrandRecord(
        brand_code="SONY",
        brand_name="索尼旧名",
        original_brand_name="Sony Upload",
    )
    db.add(brand)
    db.add(ModelRecord(brand_code="SONY", model_code="A1", brand_name="索尼型号", category_code="camera"))
    db.add(BrandAlias(alias_name="Sony", brand_code="SONY"))
    db.commit()

    resp = client.patch("/api/brands/SONY", json={"brand_name": " 索尼新名 "})

    assert resp.status_code == 200
    body = resp.json()
    assert body["brand_code"] == "SONY"
    assert body["brand_name"] == "索尼新名"
    assert body["original_brand_name"] == "Sony Upload"
    assert body["model_count"] == 1
    assert body["alias_count"] == 1
    assert db.query(BrandRecord).filter_by(brand_code="SONY").one().brand_name == "索尼新名"
    assert db.query(BrandRecord).filter_by(brand_code="SONY").one().original_brand_name == "Sony Upload"


def test_list_brands_returns_only_brand_form_alias(client_and_db):
    client, db = client_and_db
    db.add(BrandRecord(brand_code="SONY", brand_name="索尼"))
    panel_alias = BrandAlias(alias_name="Sony Panel", brand_code="SONY")
    form_alias = BrandAlias(alias_name="Sony Form", brand_code="SONY", created_by="brand_form")
    db.add(panel_alias)
    db.add(form_alias)
    db.commit()

    resp = client.get("/api/brands")

    assert resp.status_code == 200
    sony = next(item for item in resp.json()["items"] if item["brand_code"] == "SONY")
    assert sony["brand_alias_id"] == form_alias.id
    assert sony["brand_alias_name"] == "Sony Form"
    assert sony["alias_count"] == 2


def test_list_brands_does_not_treat_multiple_panel_aliases_as_brand_alias(client_and_db):
    client, db = client_and_db
    db.add(BrandRecord(brand_code="SONY", brand_name="索尼"))
    db.add(BrandAlias(alias_name="Sony First", brand_code="SONY"))
    db.add(BrandAlias(alias_name="Sony Second", brand_code="SONY"))
    db.commit()

    resp = client.get("/api/brands")

    assert resp.status_code == 200
    sony = next(item for item in resp.json()["items"] if item["brand_code"] == "SONY")
    assert sony["brand_alias_id"] is None
    assert sony["brand_alias_name"] is None
    assert sony["alias_count"] == 2


def test_update_brand_saves_name_and_brand_alias(client_and_db):
    client, db = client_and_db
    db.add(BrandRecord(brand_code="SONY", brand_name="索尼旧名", original_brand_name="Sony Upload"))
    db.add(BrandAlias(alias_name="Sony", brand_code="SONY", created_by="brand_form"))
    db.commit()

    resp = client.patch("/api/brands/SONY", json={"brand_name": "索尼新名", "alias_name": "SONY INC"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["brand_name"] == "索尼新名"
    assert body["brand_alias_name"] == "SONY INC"
    assert db.query(BrandRecord).filter_by(brand_code="SONY").one().brand_name == "索尼新名"
    assert db.query(BrandAlias).filter_by(brand_code="SONY").one().alias_name == "SONY INC"


def test_update_brand_alias_conflict_rolls_back_brand_name(client_and_db):
    client, db = client_and_db
    db.add(BrandRecord(brand_code="SONY", brand_name="索尼旧名"))
    db.add(BrandRecord(brand_code="BOSE", brand_name="博士"))
    db.add(BrandAlias(alias_name="Sony", brand_code="SONY", created_by="brand_form"))
    db.add(BrandAlias(alias_name="BOSE", brand_code="BOSE", created_by="brand_form"))
    db.commit()

    resp = client.patch("/api/brands/SONY", json={"brand_name": "索尼新名", "alias_name": "BOSE"})

    assert resp.status_code == 409
    assert db.query(BrandRecord).filter_by(brand_code="SONY").one().brand_name == "索尼旧名"
    assert db.query(BrandAlias).filter_by(brand_code="SONY").one().alias_name == "Sony"


def test_update_brand_creates_brand_alias_when_missing(client_and_db):
    client, db = client_and_db
    db.add(BrandRecord(brand_code="SONY", brand_name="索尼旧名"))
    db.commit()

    resp = client.patch("/api/brands/SONY", json={"brand_name": "索尼新名", "alias_name": "SONY INC"})

    assert resp.status_code == 200
    assert resp.json()["brand_alias_name"] == "SONY INC"
    alias = db.query(BrandAlias).filter_by(brand_code="SONY").one()
    assert alias.alias_name == "SONY INC"
    assert alias.created_by == "brand_form"


def test_update_brand_creates_form_alias_without_changing_panel_aliases(client_and_db):
    client, db = client_and_db
    db.add(BrandRecord(brand_code="SONY", brand_name="索尼旧名"))
    db.add(BrandAlias(alias_name="Sony Panel 1", brand_code="SONY"))
    db.add(BrandAlias(alias_name="Sony Panel 2", brand_code="SONY"))
    db.commit()

    resp = client.patch("/api/brands/SONY", json={"brand_name": "索尼新名", "alias_name": "SONY INC"})

    assert resp.status_code == 200
    assert resp.json()["brand_alias_name"] == "SONY INC"
    aliases = db.query(BrandAlias).filter_by(brand_code="SONY").order_by(BrandAlias.alias_name).all()
    assert [alias.alias_name for alias in aliases] == ["SONY INC", "Sony Panel 1", "Sony Panel 2"]
    assert next(alias for alias in aliases if alias.alias_name == "SONY INC").created_by == "brand_form"
    assert all(alias.created_by is None for alias in aliases if alias.alias_name.startswith("Sony Panel"))


def test_update_brand_alias(client_and_db):
    client, db = client_and_db
    db.add(BrandRecord(brand_code="SONY", brand_name="索尼"))
    db.add(BrandAlias(alias_name="Sony", brand_code="SONY"))
    db.commit()

    resp = client.patch("/api/brands/SONY/aliases/1", json={"alias_name": "SONY INC"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["alias_name"] == "SONY INC"
    assert body["brand_code"] == "SONY"
    assert db.query(BrandAlias).filter(BrandAlias.id == 1).one().alias_name == "SONY INC"
    assert client.get("/api/brands").json()["items"][0]["alias_count"] == 1


def test_update_brand_alias_rejects_duplicate(client_and_db):
    client, db = client_and_db
    db.add(BrandRecord(brand_code="SONY", brand_name="索尼"))
    db.add(BrandRecord(brand_code="BOSE", brand_name="博士"))
    db.add(BrandAlias(alias_name="Sony", brand_code="SONY"))
    db.add(BrandAlias(alias_name="BOSE", brand_code="BOSE"))
    db.commit()

    resp = client.patch("/api/brands/SONY/aliases/1", json={"alias_name": "BOSE"})

    assert resp.status_code == 409
    assert resp.json()["detail"] == "别名 'BOSE' 已存在"


def test_update_brand_alias_rejects_missing_or_foreign_alias(client_and_db):
    client, db = client_and_db
    db.add(BrandRecord(brand_code="SONY", brand_name="索尼"))
    db.add(BrandRecord(brand_code="BOSE", brand_name="博士"))
    db.add(BrandAlias(alias_name="Sony", brand_code="SONY"))
    db.add(BrandAlias(alias_name="Bose", brand_code="BOSE"))
    db.commit()

    missing = client.patch("/api/brands/SONY/aliases/999", json={"alias_name": "SONY INC"})
    foreign = client.patch("/api/brands/SONY/aliases/2", json={"alias_name": "SONY INC"})

    assert missing.status_code == 404
    assert foreign.status_code == 404


def test_update_brand_alias_rejects_blank_alias(client_and_db):
    client, db = client_and_db
    db.add(BrandRecord(brand_code="SONY", brand_name="索尼"))
    db.add(BrandAlias(alias_name="Sony", brand_code="SONY"))
    db.commit()

    resp = client.patch("/api/brands/SONY/aliases/1", json={"alias_name": "   "})

    assert resp.status_code == 400
    assert resp.json()["detail"] == "别名不能为空"


def test_update_brand_name_stores_blank_as_none(client_and_db):
    client, db = client_and_db
    db.add(BrandRecord(brand_code="BOSE", brand_name="Bose", original_brand_name="Bose Upload"))
    db.commit()

    resp = client.patch("/api/brands/BOSE", json={"brand_name": "   "})

    assert resp.status_code == 200
    assert resp.json()["brand_name"] is None
    assert db.query(BrandRecord).filter_by(brand_code="BOSE").one().brand_name is None


def test_update_brand_name_returns_404_for_missing_brand(client_and_db):
    client, _db = client_and_db

    resp = client.patch("/api/brands/MISSING", json={"brand_name": "Missing"})

    assert resp.status_code == 404
    assert resp.json()["detail"] == "品牌不存在"


def test_update_brand_name_clear_returns_none_even_with_model_metadata(client_and_db):
    """清空品牌名后，PATCH 响应与数据库 brand_name 都应为 None，不回退到型号品牌名。"""
    client, db = client_and_db
    db.add(BrandRecord(brand_code="DJI", brand_name="旧名", original_brand_name="DJI Upload"))
    db.add(ModelRecord(brand_code="DJI", model_code="OSMO-POCKET-3", brand_name="大疆"))
    db.commit()

    resp = client.patch("/api/brands/DJI", json={"brand_name": "   "})

    assert resp.status_code == 200
    body = resp.json()
    assert body["brand_name"] is None
    # original_brand_name 仍然保留（首次上传值）
    assert body["original_brand_name"] == "DJI Upload"
    assert db.query(BrandRecord).filter_by(brand_code="DJI").one().brand_name is None


def test_update_brand_name_accepts_missing_field_and_clears(client_and_db):
    """BrandUpdate.brand_name 默认为 None，缺省字段时按清空处理。"""
    client, db = client_and_db
    db.add(BrandRecord(brand_code="JBL", brand_name="JBL 旧名", original_brand_name="JBL Upload"))
    db.commit()

    resp = client.patch("/api/brands/JBL", json={})

    assert resp.status_code == 200
    assert resp.json()["brand_name"] is None
    assert db.query(BrandRecord).filter_by(brand_code="JBL").one().brand_name is None
