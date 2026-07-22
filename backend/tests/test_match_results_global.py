"""GET /api/match/reviewed 全局接口测试"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.models.database import get_db
from app.models.schemas import (
    ModelRecord, UploadFileRecord, RawDataRecord,
    CleanJobRecord, MatchResult,
)
from app.api.match_api import router as match_router


@pytest.fixture()
def match_client(db):
    app = FastAPI()
    app.include_router(match_router)

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    return TestClient(app)


def _seed(db, *, clean_job_id, upload_id, status, source, item_name,
          price_flag=None, brand_raw="Sony", platform="jd", brand_std=None,
          model_code=None, model_name=None, brand_name=None, sales_coefficient=None):
    rd = RawDataRecord(
        file_id=upload_id, platform=platform,
        item_id=f"{status}-{source}-{item_name}",
        item_url=f"https://example.com/{status}/{item_name}",
        item_name=item_name, brand_raw=brand_raw, brand_std=brand_std, sales_qty=1,
    )
    db.add(rd)
    db.flush()
    model = None
    if model_code or model_name or brand_name:
        model = ModelRecord(
            brand_code=f"BRAND-{item_name}",
            model_code=model_code or f"MODEL-{item_name}",
            model_name=model_name or f"型号-{item_name}",
            brand_name=brand_name or brand_raw,
        )
        db.add(model)
        db.flush()
    mr = MatchResult(
        clean_job_id=clean_job_id, raw_data_id=rd.id,
        model_id=model.id if model else None,
        match_status=status, matched_by="auto",
        match_source=source, price_flag=price_flag,
        sales_coefficient=sales_coefficient,
    )
    db.add(mr)
    db.flush()
    return mr


@pytest.fixture()
def seeded(db):
    upload = UploadFileRecord(filename="g.xlsx", status="done")
    db.add(upload)
    db.flush()
    job_a = CleanJobRecord(file_ids=[upload.id], status="done")
    job_b = CleanJobRecord(file_ids=[upload.id], status="done")
    db.add_all([job_a, job_b])
    db.flush()

    rows = {
        "a_matched_s1":   _seed(db, clean_job_id=job_a.id, upload_id=upload.id,
                                status="matched",     source="s1",     item_name="A1"),
        "a_matched_manual": _seed(db, clean_job_id=job_a.id, upload_id=upload.id,
                                  status="matched",     source="manual", item_name="A2"),
        "a_urlmatched_s0": _seed(db, clean_job_id=job_a.id, upload_id=upload.id,
                                 status="url_matched", source="s0",     item_name="A3",
                                 price_flag="high"),
        "a_confirmed":    _seed(db, clean_job_id=job_a.id, upload_id=upload.id,
                                status="confirmed",   source="manual", item_name="A4"),
        "a_pending":      _seed(db, clean_job_id=job_a.id, upload_id=upload.id,
                                status="pending",     source=None,     item_name="A5"),
        "b_matched_s2":   _seed(db, clean_job_id=job_b.id, upload_id=upload.id,
                                status="matched",     source="s2",     item_name="B1"),
        "b_confirmed":    _seed(db, clean_job_id=job_b.id, upload_id=upload.id,
                                status="confirmed",   source="manual", item_name="B2"),
    }
    db.commit()
    return {"upload": upload, "job_a": job_a, "job_b": job_b, "rows": rows}


def test_all_tab_returns_all_reviewable_rows_cross_jobs(match_client, seeded):
    r = match_client.get("/api/match/reviewed", params={"tab": "all"})
    assert r.status_code == 200
    body = r.json()
    # 5 条 (pending 排除): a1/a2/a3/a4/b1/b2 = 6 条
    assert body["total"] == 6
    assert body["counts"] == {"all": 6, "pending_review": 3, "confirmed": 2}


def test_pending_review_tab_excludes_manual_source(match_client, seeded):
    r = match_client.get("/api/match/reviewed", params={"tab": "pending_review"})
    assert r.status_code == 200
    body = r.json()
    ids = {item["id"] for item in body["items"]}
    expected = {
        seeded["rows"]["a_matched_s1"].id,
        seeded["rows"]["a_urlmatched_s0"].id,
        seeded["rows"]["b_matched_s2"].id,
    }
    assert ids == expected
    assert body["total"] == 3


def test_confirmed_tab_only_returns_status_confirmed(match_client, seeded):
    r = match_client.get("/api/match/reviewed", params={"tab": "confirmed"})
    body = r.json()
    ids = {item["id"] for item in body["items"]}
    assert ids == {
        seeded["rows"]["a_confirmed"].id,
        seeded["rows"]["b_confirmed"].id,
    }


def test_filter_by_clean_job_id(match_client, seeded):
    r = match_client.get("/api/match/reviewed", params={
        "tab": "all", "clean_job_id": seeded["job_a"].id,
    })
    body = r.json()
    assert body["total"] == 4
    assert body["counts"] == {"all": 4, "pending_review": 2, "confirmed": 1}


def test_filter_by_match_source_multi(match_client, seeded):
    r = match_client.get(
        "/api/match/reviewed",
        params=[("tab", "all"), ("match_source", "s0"), ("match_source", "manual")],
    )
    ids = {item["id"] for item in r.json()["items"]}
    assert ids == {
        seeded["rows"]["a_matched_manual"].id,
        seeded["rows"]["a_urlmatched_s0"].id,
        seeded["rows"]["a_confirmed"].id,
        seeded["rows"]["b_confirmed"].id,
    }


def test_filter_by_price_flag(match_client, seeded):
    r = match_client.get("/api/match/reviewed", params={"tab": "all", "price_flag": "above"})
    ids = {item["id"] for item in r.json()["items"]}
    assert ids == {seeded["rows"]["a_urlmatched_s0"].id}

    r_none = match_client.get("/api/match/reviewed", params={"tab": "all", "price_flag": "none"})
    # 除 a_urlmatched_s0 外全部 price_flag IS NULL
    assert r_none.json()["total"] == 5


def test_filter_by_keyword(match_client, seeded):
    r = match_client.get("/api/match/reviewed", params={"tab": "all", "keyword": "A1"})
    ids = {item["id"] for item in r.json()["items"]}
    assert ids == {seeded["rows"]["a_matched_s1"].id}


def test_counts_reflect_current_filters_not_tab(match_client, seeded):
    # 按 job_a 筛，切到 confirmed tab，counts 三档都是 job_a 内的分布
    r = match_client.get("/api/match/reviewed", params={
        "tab": "confirmed", "clean_job_id": seeded["job_a"].id,
    })
    body = r.json()
    assert body["counts"] == {"all": 4, "pending_review": 2, "confirmed": 1}
    # items 只是 confirmed tab 的
    assert body["total"] == 1


def test_pagination_defaults_and_bounds(match_client, seeded):
    r = match_client.get("/api/match/reviewed", params={"tab": "all", "page_size": 2})
    body = r.json()
    assert body["page"] == 1
    assert body["page_size"] == 2
    assert len(body["items"]) == 2
    # 越上限
    r_over = match_client.get("/api/match/reviewed", params={"page_size": 101})
    assert r_over.status_code == 422


def test_orders_by_id_desc(match_client, seeded):
    r = match_client.get("/api/match/reviewed", params={"tab": "all"})
    ids = [item["id"] for item in r.json()["items"]]
    assert ids == sorted(ids, reverse=True)


def test_filter_by_platform(match_client, db, seeded):
    _seed(db, clean_job_id=seeded["job_a"].id, upload_id=seeded["upload"].id,
          status="matched", source="s1", item_name="TMALL-ONLY", platform="tmall")
    db.commit()

    r = match_client.get("/api/match/reviewed", params={"platform": "tmall"})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["item_name"] == "TMALL-ONLY"
    assert body["counts"] == {"all": 1, "pending_review": 1, "confirmed": 0}


def test_filter_by_brand_keyword(match_client, db, seeded):
    _seed(db, clean_job_id=seeded["job_a"].id, upload_id=seeded["upload"].id,
          status="matched", source="s1", item_name="BRAND-RAW", brand_raw="RawUnique")
    _seed(db, clean_job_id=seeded["job_a"].id, upload_id=seeded["upload"].id,
          status="matched", source="s1", item_name="BRAND-STD", brand_std="StdUnique")
    _seed(db, clean_job_id=seeded["job_a"].id, upload_id=seeded["upload"].id,
          status="matched", source="s1", item_name="BRAND-MATCHED", brand_name="MatchedUnique")
    db.commit()

    raw = match_client.get("/api/match/reviewed", params={"brand_keyword": "RawUnique"})
    assert {item["item_name"] for item in raw.json()["items"]} == {"BRAND-RAW"}

    std = match_client.get("/api/match/reviewed", params={"brand_keyword": "StdUnique"})
    assert {item["item_name"] for item in std.json()["items"]} == {"BRAND-STD"}

    matched = match_client.get("/api/match/reviewed", params={"brand_keyword": "MatchedUnique"})
    assert {item["item_name"] for item in matched.json()["items"]} == {"BRAND-MATCHED"}


def test_filter_by_model_keyword(match_client, db, seeded):
    _seed(db, clean_job_id=seeded["job_a"].id, upload_id=seeded["upload"].id,
          status="matched", source="s1", item_name="MODEL-CODE", model_code="CODE-UNIQUE")
    _seed(db, clean_job_id=seeded["job_a"].id, upload_id=seeded["upload"].id,
          status="matched", source="s1", item_name="MODEL-NAME", model_name="NameUnique")
    db.commit()

    by_code = match_client.get("/api/match/reviewed", params={"model_keyword": "CODE-UNIQUE"})
    assert {item["item_name"] for item in by_code.json()["items"]} == {"MODEL-CODE"}

    by_name = match_client.get("/api/match/reviewed", params={"model_keyword": "NameUnique"})
    assert {item["item_name"] for item in by_name.json()["items"]} == {"MODEL-NAME"}


def test_filter_by_coefficient_presence(match_client, db, seeded):
    _seed(db, clean_job_id=seeded["job_a"].id, upload_id=seeded["upload"].id,
          status="matched", source="s1", item_name="COEFF-WITH", sales_coefficient=1.2)
    _seed(db, clean_job_id=seeded["job_a"].id, upload_id=seeded["upload"].id,
          status="matched", source="s1", item_name="COEFF-WITHOUT")
    db.commit()

    with_coeff = match_client.get("/api/match/reviewed", params={"coefficient_filter": "with"})
    assert {item["item_name"] for item in with_coeff.json()["items"]} == {"COEFF-WITH"}
    assert with_coeff.json()["counts"] == {"all": 1, "pending_review": 1, "confirmed": 0}

    without_coeff = match_client.get("/api/match/reviewed", params={"coefficient_filter": "without"})
    names = {item["item_name"] for item in without_coeff.json()["items"]}
    assert "COEFF-WITH" not in names
    assert "COEFF-WITHOUT" in names
