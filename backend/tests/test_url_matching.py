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
    model = ModelRecord(brand_code="BOSE", model_code="SB850", category_code="SOUNDBAR")
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


@pytest.fixture(autouse=True)
def _set_db_override():
    """确保每个测试前 get_db override 指向 SQLite，防止其他测试文件 clear() 污染"""
    app.dependency_overrides[get_db] = override_get_db
    yield
    app.dependency_overrides[get_db] = override_get_db


client = TestClient(app)


def _get_token():
    return create_access_token("urltest")


def _seed_model(db, brand_code="BOSE", model_code="SB900") -> int:
    from app.models.schemas import ModelRecord
    m = db.query(ModelRecord).filter_by(brand_code=brand_code, model_code=model_code).first()
    if not m:
        m = ModelRecord(brand_code=brand_code, model_code=model_code, category_code="SOUNDBAR")
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


def test_create_url_mapping_conflict():
    """POST /api/url-mappings returns 409 on duplicate platform+item_id"""
    token = _get_token()
    headers = {"Authorization": f"Bearer {token}"}
    db = TestSession()
    model_id = _seed_model(db)
    # Seed a mapping directly
    mapping = ItemUrlMapping(platform="jd", item_id="conflict_test_999", model_id=model_id)
    db.add(mapping)
    db.commit()
    db.close()

    r = client.post("/api/url-mappings", json={
        "platform": "jd", "item_id": "conflict_test_999", "model_id": model_id
    }, headers=headers)
    assert r.status_code == 409, f"Expected 409, got {r.status_code}: {r.text}"


def test_update_url_mapping_not_found():
    """PUT /api/url-mappings/{id} returns 404 for missing id"""
    token = _get_token()
    headers = {"Authorization": f"Bearer {token}"}
    db = TestSession()
    model_id = _seed_model(db)
    db.close()

    r = client.put("/api/url-mappings/999999",
                   json={"platform": "jd", "item_id": "ghost_item", "model_id": model_id},
                   headers=headers)
    assert r.status_code == 404, f"Expected 404, got {r.status_code}: {r.text}"


from app.services.matcher import run_match
from app.models.schemas import (
    CleanedDataRecord, CleanJobRecord, UploadFileRecord, RawDataRecord,
)


def _seed_match_data(db, item_url: str, item_name: str, brand_raw: str, brand_code: str, model_code: str):
    """Seed minimal data for a single cleaned row with given URL."""
    model = db.query(ModelRecord).filter_by(brand_code=brand_code, model_code=model_code).first()
    if not model:
        model = ModelRecord(brand_code=brand_code, model_code=model_code, category_code="SOUNDBAR")
        db.add(model)
        db.flush()

    uf = UploadFileRecord(filename="t.xlsx", platform="jd", month_range="202601")
    db.add(uf)
    db.flush()

    rd = RawDataRecord(
        file_id=uf.id, platform="jd", month=202601, category_lv1="音频",
        item_id="testitem", item_name=item_name, brand_raw=brand_raw,
        item_url=item_url, price=999.0, sales_qty=1, sales_amount=999.0,
    )
    db.add(rd)
    db.flush()

    cj = CleanJobRecord(status="done", file_ids=[uf.id])
    db.add(cj)
    db.flush()

    cd = CleanedDataRecord(
        raw_data_id=rd.id, clean_job_id=cj.id,
        platform="jd", month=202601, category_lv1="音频",
        item_id="testitem", item_name=item_name, item_url=item_url,
        brand_raw=brand_raw, price=999.0, sales_qty=1, sales_amount=999.0,
    )
    db.add(cd)
    db.commit()
    return cj.id, model.id


def test_s0_url_match():
    """S0: item with URL in mapping table → url_matched"""
    db = TestSession()

    cj_id, model_id = _seed_match_data(
        db,
        item_url="https://item.jd.com/800055334411.html",
        item_name="完全不含型号的商品名称",
        brand_raw="BOSE",
        brand_code="BOSE",
        model_code="SB_S0_TEST",
    )
    # Add URL mapping (use item_id distinct from other tests)
    existing = db.query(ItemUrlMapping).filter_by(platform="jd", item_id="800055334411").first()
    if not existing:
        db.add(ItemUrlMapping(platform="jd", item_id="800055334411", model_id=model_id))
    db.commit()

    run_match(db, cj_id)
    from app.models.schemas import MatchResult
    results = db.query(MatchResult).filter_by(clean_job_id=cj_id).all()
    assert len(results) == 1
    assert results[0].match_status == "url_matched"
    assert results[0].match_source == "s0"
    assert results[0].model_id == model_id
    db.close()


def test_text_only_when_url_not_in_map():
    """S1-S4 text match + URL exists in raw data but NOT in mapping → text_only"""
    db = TestSession()

    model = ModelRecord(brand_code="EDIFIER_TX", model_code="EDIFIER_R1280", category_code="SOUNDBAR")
    db.add(model)
    db.flush()

    uf = UploadFileRecord(filename="t2.xlsx", platform="jd", month_range="202601")
    db.add(uf)
    db.flush()
    rd = RawDataRecord(
        file_id=uf.id, platform="jd", month=202601, category_lv1="音频",
        item_id="textonly_item", item_name="EDIFIER_R1280 蓝牙音箱",
        brand_raw="EDIFIER_TX",
        item_url="https://item.jd.com/777999888.html",  # NOT in url_map
        price=500.0, sales_qty=2, sales_amount=1000.0,
    )
    db.add(rd)
    db.flush()
    cj = CleanJobRecord(status="done", file_ids=[uf.id])
    db.add(cj)
    db.flush()
    cd = CleanedDataRecord(
        raw_data_id=rd.id, clean_job_id=cj.id,
        platform="jd", month=202601, category_lv1="音频",
        item_id="textonly_item", item_name="EDIFIER_R1280 蓝牙音箱",
        item_url="https://item.jd.com/777999888.html",
        brand_raw="EDIFIER_TX", price=500.0, sales_qty=2, sales_amount=1000.0,
    )
    db.add(cd)
    db.commit()

    run_match(db, cj.id)
    from app.models.schemas import MatchResult
    results = db.query(MatchResult).filter_by(clean_job_id=cj.id).all()
    assert len(results) == 1
    assert results[0].match_status == "text_only", f"Expected text_only, got {results[0].match_status}"
    db.close()


def test_matched_when_no_url():
    """Text match with no URL in raw data → matched (not text_only)"""
    db = TestSession()

    model = ModelRecord(brand_code="SENNHSR", model_code="MOMENTUM_S3", category_code="SOUNDBAR")
    db.add(model)
    db.flush()

    uf = UploadFileRecord(filename="t3.xlsx", platform="jd", month_range="202601")
    db.add(uf)
    db.flush()
    rd = RawDataRecord(
        file_id=uf.id, platform="jd", month=202601, category_lv1="音频",
        item_id="nourl_item", item_name="MOMENTUM_S3 蓝牙音箱",
        brand_raw="SENNHSR",
        item_url=None,   # No URL
        price=500.0, sales_qty=2, sales_amount=1000.0,
    )
    db.add(rd)
    db.flush()
    cj = CleanJobRecord(status="done", file_ids=[uf.id])
    db.add(cj)
    db.flush()
    cd = CleanedDataRecord(
        raw_data_id=rd.id, clean_job_id=cj.id,
        platform="jd", month=202601, category_lv1="音频",
        item_id="nourl_item", item_name="MOMENTUM_S3 蓝牙音箱",
        item_url=None,
        brand_raw="SENNHSR", price=500.0, sales_qty=2, sales_amount=1000.0,
    )
    db.add(cd)
    db.commit()

    run_match(db, cj.id)
    from app.models.schemas import MatchResult
    results = db.query(MatchResult).filter_by(clean_job_id=cj.id).all()
    assert len(results) == 1
    assert results[0].match_status == "matched"
    db.close()


@pytest.mark.skip(reason="requires analytics DB (MySQL); run inside Docker only")
def test_publisher_includes_url_matched():
    """url_matched rows are published; text_only rows are skipped"""
    from app.models.schemas import (
        MatchResult, UploadFileRecord, RawDataRecord, CleanJobRecord,
    )
    from app.models.analytics_db import AnalyticsBase, analytics_engine, AnalyticsSession
    from app.services.publisher import run_publish

    AnalyticsBase.metadata.create_all(bind=analytics_engine)

    db = TestSession()
    model = db.query(ModelRecord).first()
    if not model:
        model = ModelRecord(brand_code="PUB_TEST", model_code="PUB_MODEL", category_code="SOUNDBAR")
        db.add(model)
        db.flush()

    uf = UploadFileRecord(filename="pub.xlsx", platform="jd", month_range="202601")
    db.add(uf)
    db.flush()

    rd1 = RawDataRecord(file_id=uf.id, platform="jd", month=202601, category_lv1="音频",
                        item_id="pub1", item_name="pub item 1", brand_raw="PUB_TEST",
                        price=500.0, sales_qty=1, sales_amount=500.0)
    rd2 = RawDataRecord(file_id=uf.id, platform="jd", month=202601, category_lv1="音频",
                        item_id="pub2", item_name="pub item 2", brand_raw="PUB_TEST",
                        price=300.0, sales_qty=1, sales_amount=300.0)
    db.add_all([rd1, rd2])
    db.flush()

    cj = CleanJobRecord(status="done", file_ids=[uf.id])
    db.add(cj)
    db.flush()

    mr1 = MatchResult(clean_job_id=cj.id, raw_data_id=rd1.id,
                      model_id=model.id, match_status="url_matched", is_disabled=0)
    mr2 = MatchResult(clean_job_id=cj.id, raw_data_id=rd2.id,
                      model_id=model.id, match_status="text_only", is_disabled=0)
    db.add_all([mr1, mr2])
    db.commit()

    analytics_db = AnalyticsSession()
    try:
        result = run_publish(db, analytics_db, cj.id)
        assert result["published_count"] == 1, \
            f"Should publish url_matched only, got {result['published_count']}"
    finally:
        db.close()
        analytics_db.close()


def test_summary_includes_url_matched_and_text_only():
    """GET /api/match/{cj_id}/summary returns url_matched and text_only counts"""
    token = _get_token()
    headers = {"Authorization": f"Bearer {token}"}

    db = TestSession()
    model = db.query(ModelRecord).first()
    uf = UploadFileRecord(filename="sum.xlsx", platform="jd", month_range="202601")
    db.add(uf); db.flush()
    cj = CleanJobRecord(status="done", file_ids=[uf.id])
    db.add(cj); db.flush()

    rd1 = RawDataRecord(file_id=uf.id, platform="jd", month=202601, category_lv1="音频",
                        item_id="s1", item_name="s1", brand_raw="X", price=1.0,
                        sales_qty=1, sales_amount=1.0)
    rd2 = RawDataRecord(file_id=uf.id, platform="jd", month=202601, category_lv1="音频",
                        item_id="s2", item_name="s2", brand_raw="X", price=1.0,
                        sales_qty=1, sales_amount=1.0)
    db.add_all([rd1, rd2]); db.flush()

    from app.models.schemas import MatchResult
    db.add(MatchResult(clean_job_id=cj.id, raw_data_id=rd1.id,
                       model_id=model.id, match_status="url_matched"))
    db.add(MatchResult(clean_job_id=cj.id, raw_data_id=rd2.id,
                       model_id=model.id, match_status="text_only"))
    db.commit()
    cj_id = cj.id
    db.close()

    r = client.get(f"/api/match/{cj_id}/summary", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["url_matched"] == 1, f"url_matched should be 1: {body}"
    assert body["text_only"] == 1, f"text_only should be 1: {body}"


def test_list_text_only():
    """GET /api/match/{cj_id}/pending?status=text_only returns text_only rows"""
    token = _get_token()
    headers = {"Authorization": f"Bearer {token}"}

    db = TestSession()
    model = db.query(ModelRecord).first()
    uf = UploadFileRecord(filename="to.xlsx", platform="jd", month_range="202601")
    db.add(uf); db.flush()
    cj = CleanJobRecord(status="done", file_ids=[uf.id])
    db.add(cj); db.flush()
    rd = RawDataRecord(file_id=uf.id, platform="jd", month=202601, category_lv1="音频",
                       item_id="to1", item_name="test text only item", brand_raw="X",
                       price=1.0, sales_qty=1, sales_amount=1.0)
    db.add(rd); db.flush()
    from app.models.schemas import MatchResult
    db.add(MatchResult(clean_job_id=cj.id, raw_data_id=rd.id,
                       model_id=model.id, match_status="text_only"))
    db.commit()
    cj_id = cj.id
    db.close()

    r = client.get(f"/api/match/{cj_id}/pending", params={"status": "text_only"}, headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["total"] >= 1
    assert all(item["match_status"] == "text_only" for item in body["items"])
