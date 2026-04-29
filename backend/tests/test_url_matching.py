"""Tests for URL-based matching system"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.models.schemas import Base, ItemUrlMapping, ModelRecord

SQLITE_URL = "sqlite:///:memory:"
engine = create_engine(SQLITE_URL, connect_args={"check_same_thread": False}, poolclass=StaticPool)
Base.metadata.drop_all(bind=engine)
Base.metadata.create_all(bind=engine)
TestSession = sessionmaker(bind=engine)


def test_item_url_mapping_orm():
    """ItemUrlMapping ORM can be created and queried"""
    db = TestSession()
    model = ModelRecord(brand_code="BOSE", model_code="SB850", category_name="SOUNDBAR")
    db.add(model)
    db.flush()

    m = ItemUrlMapping(platform="jd", item_id="100045223280", model_id=model.id, price=1999.0)
    db.add(m)
    db.commit()

    found = db.query(ItemUrlMapping).filter_by(item_id="100045223280").first()
    assert found is not None
    assert found.platform == "jd"
    assert found.model_id == model.id
    assert float(found.price) == 1999.0
    db.close()


from app.utils.url_utils import extract_item_id


def test_extract_jd_url():
    assert extract_item_id("https://item.jd.com/100045223280.html") == ("jd", "100045223280")


def test_extract_jd_url_no_extension():
    """URL without .html should still parse"""
    assert extract_item_id("https://item.jd.com/100045223280") == ("jd", "100045223280")


def test_extract_tmall_url():
    assert extract_item_id("https://detail.tmall.com/item.htm?id=738271928") == ("tmall", "738271928")


def test_extract_taobao_url():
    assert extract_item_id("https://item.taobao.com/item.htm?id=655781234") == ("taobao", "655781234")


def test_extract_suning_url():
    assert extract_item_id("https://product.suning.com/0070171620/11498580.html") == ("suning", "11498580")


def test_extract_unknown_url_returns_none():
    assert extract_item_id("https://www.amazon.com/dp/B08N5WRWNW") is None


def test_extract_none_returns_none():
    assert extract_item_id(None) is None


def test_extract_empty_returns_none():
    assert extract_item_id("") is None


from fastapi.testclient import TestClient
from app.main import app
from app.models.database import get_db
from app.core.security import create_access_token


def override_get_db():
    db = TestSession()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)


def _get_token():
    return create_access_token("urltest")


def _seed_model(db, brand_code="BOSE", model_code="SB900") -> int:
    from app.models.schemas import ModelRecord
    m = db.query(ModelRecord).filter_by(brand_code=brand_code, model_code=model_code).first()
    if not m:
        m = ModelRecord(brand_code=brand_code, model_code=model_code, category_name="SOUNDBAR")
        db.add(m)
        db.commit()
    return m.id


def test_create_url_mapping():
    token = _get_token()
    headers = {"Authorization": f"Bearer {token}"}
    db = TestSession()
    model_id = _seed_model(db)
    db.close()

    r = client.post("/api/url-mappings", json={
        "platform": "jd", "item_id": "999000111", "model_id": model_id, "price": 1499.0
    }, headers=headers)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["platform"] == "jd"
    assert data["item_id"] == "999000111"
    assert data["model_id"] == model_id


def test_list_url_mappings():
    token = _get_token()
    headers = {"Authorization": f"Bearer {token}"}
    r = client.get("/api/url-mappings", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "total" in body
    assert "items" in body


def test_update_url_mapping():
    token = _get_token()
    headers = {"Authorization": f"Bearer {token}"}
    db = TestSession()
    model_id = _seed_model(db)
    mapping = ItemUrlMapping(platform="jd", item_id="update_test_777", model_id=model_id)
    db.add(mapping)
    db.commit()
    mid = mapping.id
    db.close()

    r = client.put(f"/api/url-mappings/{mid}",
                   json={"platform": "jd", "item_id": "update_test_777",
                         "model_id": model_id, "price": 888.0},
                   headers=headers)
    assert r.status_code == 200, r.text
    assert float(r.json()["price"]) == 888.0


def test_delete_url_mapping():
    token = _get_token()
    headers = {"Authorization": f"Bearer {token}"}
    db = TestSession()
    model_id = _seed_model(db)
    mapping = ItemUrlMapping(platform="jd", item_id="delete_test_555", model_id=model_id)
    db.add(mapping)
    db.commit()
    mid = mapping.id
    db.close()

    r = client.delete(f"/api/url-mappings/{mid}", headers=headers)
    assert r.status_code == 200, r.text

    db = TestSession()
    assert db.query(ItemUrlMapping).filter_by(id=mid).first() is None
    db.close()
