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
          price_flag=None, brand_raw="Sony"):
    rd = RawDataRecord(
        file_id=upload_id, platform="jd",
        item_id=f"{status}-{source}-{item_name}",
        item_url=f"https://example.com/{status}/{item_name}",
        item_name=item_name, brand_raw=brand_raw, sales_qty=1,
    )
    db.add(rd)
    db.flush()
    mr = MatchResult(
        clean_job_id=clean_job_id, raw_data_id=rd.id,
        match_status=status, matched_by="auto",
        match_source=source, price_flag=price_flag,
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
    return {"job_a": job_a, "job_b": job_b, "rows": rows}


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
