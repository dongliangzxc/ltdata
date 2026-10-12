"""人工排除沉淀库（item_exclusions）复用测试。

覆盖：
  - 匹配阶段 S0.1：同品类按链接 / 标题兜底自动沿用排除
  - 跨品类不复用
  - 人工排除（单条 / 同标题批量）写入沉淀库
  - 撤销 / 确认时从沉淀库移除
"""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.auth_deps import get_current_user
from app.models.database import get_db
from app.models.schemas import (
    UploadFileRecord, RawDataRecord, CleanJobRecord, CleanedDataRecord,
    ModelRecord, MatchResult, ItemExclusion,
)
from app.api.match_api import router as match_router
from app.services.exclusion_store import (
    upsert_exclusion_for_raw,
    remove_exclusion_for_raw,
    load_exclusion_index,
    backfill_existing_exclusions,
)
from app.services.matcher import run_match
from app.utils.text_utils import title_key


class DummyUser:
    def __init__(self, *, is_admin=1, category_permissions=None):
        self.is_admin = is_admin
        self.category_permissions = category_permissions


def _seed_job_with_row(db, *, category_code="TEST", brand_code=None, item_name,
                       model_code=None, platform="jd", item_id="001", item_url=None):
    upload = UploadFileRecord(filename="t.xlsx", platform=platform, status="done", row_count=1)
    db.add(upload)
    db.flush()

    if model_code:
        db.add(ModelRecord(
            brand_code=brand_code, model_code=model_code,
            brand_name=brand_code, model_name=model_code, category_code=category_code,
        ))
        db.flush()

    raw = RawDataRecord(
        file_id=upload.id, platform=platform, item_id=item_id,
        item_url=item_url, item_name=item_name, brand_raw=brand_code,
    )
    db.add(raw)
    db.flush()

    job = CleanJobRecord(
        file_ids=[upload.id], rules={}, status="reviewing",
        row_in=1, row_out=1, category_code=category_code,
    )
    db.add(job)
    db.flush()

    cleaned = CleanedDataRecord(
        raw_data_id=raw.id, clean_job_id=job.id, platform=platform,
        item_id=item_id, item_url=item_url, item_name=item_name, brand_raw=brand_code,
    )
    db.add(cleaned)
    db.flush()
    return job, raw


def _match_result(db, job_id):
    return db.query(MatchResult).filter(MatchResult.clean_job_id == job_id).first()


# ── 匹配阶段复用 ────────────────────────────────────────────────

def test_reuse_exclusion_by_url_in_same_category(db):
    db.add(ItemExclusion(category_code="TEST", platform="jd", item_id="001",
                         item_name="旧标题"))
    db.commit()

    job, _raw = _seed_job_with_row(
        db, category_code="TEST", brand_code="SONY", model_code="HT-A7000",
        item_name="索尼 HT-A7000 回音壁", platform="jd", item_id="001",
        item_url="https://item.jd.com/001.html",
    )
    db.commit()

    run_match(db, job.id)

    result = _match_result(db, job.id)
    assert result.match_status == "excluded"
    assert result.match_source == "exclude_reuse"
    assert result.matched_by == "auto"
    assert result.model_id is None


def test_url_exclusion_wins_before_text_match(db):
    """即使文本能匹配到型号，命中排除库也直接 excluded。"""
    db.add(ItemExclusion(category_code="TEST", platform="jd", item_id="001"))
    db.commit()

    job, _raw = _seed_job_with_row(
        db, category_code="TEST", brand_code="SONY", model_code="HT-A7000",
        item_name="索尼 HT-A7000 回音壁", item_id="001",
        item_url="https://item.jd.com/001.html",
    )
    db.commit()
    run_match(db, job.id)
    assert _match_result(db, job.id).match_status == "excluded"


def test_reuse_exclusion_by_title_when_no_link(db):
    name = "索尼 HT-A7000 回音壁"
    db.add(ItemExclusion(category_code="TEST", item_id=None,
                         item_name_norm=title_key(name)))
    db.commit()

    job, _raw = _seed_job_with_row(
        db, category_code="TEST", brand_code="SONY", model_code="HT-A7000",
        item_name=name, item_id=None, item_url=None,
    )
    db.commit()
    run_match(db, job.id)

    result = _match_result(db, job.id)
    assert result.match_status == "excluded"
    assert result.match_source == "exclude_reuse"


def test_exclusion_not_reused_across_categories(db):
    db.add(ItemExclusion(category_code="OTHER", platform="jd", item_id="001"))
    db.commit()

    job, _raw = _seed_job_with_row(
        db, category_code="TEST", brand_code="SONY", model_code="HT-A7000",
        item_name="索尼 HT-A7000 回音壁", item_id="001",
        item_url="https://item.jd.com/001.html",
    )
    db.commit()
    run_match(db, job.id)

    result = _match_result(db, job.id)
    assert result.match_status == "text_only"
    assert result.match_source != "exclude_reuse"


# ── 沉淀库读写 ──────────────────────────────────────────────────

def test_upsert_and_remove_exclusion_for_raw(db):
    _job, raw = _seed_job_with_row(
        db, category_code="TEST", item_name="索尼 HT-A7000 回音壁",
        item_id="001", item_url="https://item.jd.com/001.html",
    )
    db.commit()

    upsert_exclusion_for_raw(db, raw, "TEST", reason="非目标品类", source="manual")
    db.commit()
    url_keys, name_keys = load_exclusion_index(db, "TEST")
    assert ("jd", "001") in url_keys

    remove_exclusion_for_raw(db, raw, "TEST")
    db.commit()
    url_keys, _ = load_exclusion_index(db, "TEST")
    assert ("jd", "001") not in url_keys


def test_load_exclusion_index_disabled_without_category(db):
    db.add(ItemExclusion(category_code="TEST", platform="jd", item_id="001"))
    db.commit()
    url_keys, name_keys = load_exclusion_index(db, None)
    assert url_keys == set()
    assert name_keys == set()


def test_backfill_existing_exclusions(db):
    # 两个任务下的已排除记录
    job_a, raw_a = _seed_job_with_row(
        db, category_code="TEST", item_name="商品A", item_id="111",
        item_url="https://item.jd.com/111.html",
    )
    job_b, raw_b = _seed_job_with_row(
        db, category_code="TEST", item_name="商品B", item_id="222",
        item_url="https://item.jd.com/222.html",
    )
    # 无归属品类的任务，回填时应跳过
    job_c, raw_c = _seed_job_with_row(
        db, category_code=None, item_name="商品C", item_id="333",
        item_url="https://item.jd.com/333.html",
    )
    db.add(MatchResult(clean_job_id=job_a.id, raw_data_id=raw_a.id,
                       match_status="excluded", matched_by="manual", review_note="非目标"))
    db.add(MatchResult(clean_job_id=job_b.id, raw_data_id=raw_b.id,
                       match_status="excluded", matched_by="manual"))
    db.add(MatchResult(clean_job_id=job_c.id, raw_data_id=raw_c.id,
                       match_status="excluded", matched_by="manual"))
    db.add(MatchResult(clean_job_id=job_a.id, raw_data_id=raw_a.id,
                       match_status="confirmed", matched_by="manual"))
    db.commit()

    backfilled = backfill_existing_exclusions(db)
    db.commit()

    assert backfilled == 2
    rows = db.query(ItemExclusion).filter(ItemExclusion.category_code == "TEST").all()
    assert {r.item_id for r in rows} == {"111", "222"}

    # 再次执行幂等：同一键原地更新，不新增
    backfilled_again = backfill_existing_exclusions(db)
    db.commit()
    assert backfilled_again == 2
    assert db.query(ItemExclusion).count() == 2


def test_backfill_exclusion_used_by_new_task(db):
    # 先制造一条历史已排除记录
    job_a, raw_a = _seed_job_with_row(
        db, category_code="TEST", item_name="商品A", item_id="111",
        item_url="https://item.jd.com/111.html",
    )
    db.add(MatchResult(clean_job_id=job_a.id, raw_data_id=raw_a.id,
                       match_status="excluded", matched_by="manual"))
    db.commit()

    backfill_existing_exclusions(db)
    db.commit()

    # 新任务同款商品应自动沿用排除
    job_b, _raw_b = _seed_job_with_row(
        db, category_code="TEST", brand_code="SONY", model_code="HT-A7000",
        item_name="同款新任务 索尼 HT-A7000", item_id="111",
        item_url="https://item.jd.com/111.html",
    )
    db.commit()
    run_match(db, job_b.id)

    result = _match_result(db, job_b.id)
    assert result.match_status == "excluded"
    assert result.match_source == "exclude_reuse"


# ── API 层沉淀 / 移除 ───────────────────────────────────────────

def _client(db):
    app = FastAPI()
    app.include_router(match_router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: DummyUser()
    return TestClient(app)


def _seed_match(db, *, status="pending", item_name="测试商品", item_id="001"):
    upload = UploadFileRecord(filename="t.xlsx", platform="jd", status="done")
    db.add(upload)
    db.flush()
    job = CleanJobRecord(file_ids=[upload.id], status="reviewing", category_code="TEST")
    db.add(job)
    db.flush()
    raw = RawDataRecord(
        file_id=upload.id, platform="jd", item_id=item_id,
        item_url=f"https://item.jd.com/{item_id}.html", item_name=item_name,
        brand_raw="Sony",
    )
    db.add(raw)
    db.flush()
    mr = MatchResult(clean_job_id=job.id, raw_data_id=raw.id, match_status=status,
                     matched_by="auto", match_source="s1")
    db.add(mr)
    db.flush()
    return job, raw, mr


def test_single_exclude_writes_library(db):
    client = _client(db)
    _job, _raw, mr = _seed_match(db)
    db.commit()

    resp = client.put(f"/api/match/confirm/{mr.id}", json={"excluded": True, "reason": "非目标"})
    assert resp.status_code == 200

    row = db.query(ItemExclusion).filter(
        ItemExclusion.category_code == "TEST", ItemExclusion.platform == "jd",
        ItemExclusion.item_id == "001",
    ).first()
    assert row is not None
    assert row.reason == "非目标"


def test_confirm_removes_exclusion_from_library(db):
    client = _client(db)
    _job, raw, mr = _seed_match(db)
    db.add(ItemExclusion(category_code="TEST", platform="jd", item_id="001"))
    model = ModelRecord(brand_code="SONY", model_code="HT-A7000",
                        brand_name="Sony", model_name="HT-A7000", category_code="TEST")
    db.add(model)
    db.commit()

    resp = client.put(f"/api/match/confirm/{mr.id}", json={"model_id": model.id})
    assert resp.status_code == 200

    assert db.query(ItemExclusion).filter(
        ItemExclusion.category_code == "TEST", ItemExclusion.item_id == "001",
    ).count() == 0


def test_revert_excluded_removes_from_library(db):
    client = _client(db)
    _job, _raw, mr = _seed_match(db, status="excluded")
    db.add(ItemExclusion(category_code="TEST", platform="jd", item_id="001"))
    db.commit()

    resp = client.post(f"/api/match/items/{mr.id}/revert")
    assert resp.status_code == 200

    assert db.query(ItemExclusion).filter(
        ItemExclusion.category_code == "TEST", ItemExclusion.item_id == "001",
    ).count() == 0


def test_same_title_exclude_writes_library(db):
    client = _client(db)
    upload = UploadFileRecord(filename="t.xlsx", platform="jd", status="done")
    db.add(upload)
    db.flush()
    job = CleanJobRecord(file_ids=[upload.id], status="reviewing", category_code="TEST")
    db.add(job)
    db.flush()

    matches = []
    for item_id in ("101", "102"):
        raw = RawDataRecord(
            file_id=upload.id, platform="jd", item_id=item_id,
            item_url=f"https://item.jd.com/{item_id}.html", item_name="同标题商品",
            brand_raw="Sony",
        )
        db.add(raw)
        db.flush()
        mr = MatchResult(clean_job_id=job.id, raw_data_id=raw.id, match_status="pending",
                         matched_by="auto", match_source="s1")
        db.add(mr)
        db.flush()
        matches.append(mr)
    db.commit()

    resp = client.post(f"/api/match/items/{matches[0].id}/same-title-exclude", json={})
    assert resp.status_code == 200

    rows = db.query(ItemExclusion).filter(ItemExclusion.category_code == "TEST").all()
    assert {r.item_id for r in rows} == {"101", "102"}
