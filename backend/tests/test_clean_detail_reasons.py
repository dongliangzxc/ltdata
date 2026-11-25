"""Read-only per-row explanations cover outcomes without inventing old evidence."""
import pytest

from app.models.schemas import (
    Category, CleanedDataRecord, CleanDuplicateRecord, CleanJobRecord, FilteredItem,
    InterventionRule, MatchResult, ModelRecord, RawDataRecord, UploadFileRecord,
)
from app.services.clean_detail_reasons import match_detail_reason, filter_detail_reason, duplicate_detail_reason
from tests.test_clean_task_queue import _client


@pytest.mark.parametrize("source, expected", [
    ("s0", "URL 映射库"), ("historical", "历史库"), ("s0.2", "历史库"),
    ("s0.5", "具体规则名称和命中词未记录"), ("s1", "品牌线索"),
    ("s2", "品牌码"), ("s3", "品牌名称"), ("s4", "长型号码"),
    (None, "具体匹配依据未记录"), ("unknown", "具体匹配依据未记录"),
])
def test_match_reason_uses_saved_source_and_model(source, expected):
    result = MatchResult(match_status="matched", match_source=source, model_id=42)
    model = ModelRecord(id=42, brand_code="SONY", series="HT", model_code="A7000")
    reason = match_detail_reason(result, model)
    assert expected in reason
    assert "SONY / HT / A7000" in reason
    assert "#42" in reason


def test_manual_terminal_status_takes_precedence_over_old_automatic_source():
    result = MatchResult(match_status="excluded", match_source="s0", matched_by="manual", review_note="赠品不纳入统计")
    assert "已人工排除" in match_detail_reason(result, None)
    assert "赠品不纳入统计" in match_detail_reason(result, None)
    assert "URL 映射库" not in match_detail_reason(result, None)
    result.match_status = "ignored"
    assert "仅在当前任务" in match_detail_reason(result, None)
    result.match_status = "disputed"
    result.dispute_reason = "链接对应两个配置，需核对"
    assert "链接对应两个配置，需核对" in match_detail_reason(result, None)
    result.match_status = "confirmed"
    assert "人工选择并确认" in match_detail_reason(result, None)


def test_pending_text_only_exclusion_and_missing_history_are_explicit():
    assert "尚无型号匹配结果" in match_detail_reason(None, None)
    pending = MatchResult(match_status="pending", brand_identified=0)
    assert "尚未识别品牌" in match_detail_reason(pending, None)
    pending.brand_identified = 1
    assert "等待人工确认" in match_detail_reason(pending, None)
    text_only = MatchResult(match_status="text_only", match_source="s1", model_id=7)
    assert "尚待人工确认" in match_detail_reason(text_only, None)
    assert "#7 当前已不存在" in match_detail_reason(text_only, None)
    reused = MatchResult(match_status="excluded", match_source="exclude_reuse")
    assert "人工排除沉淀记录" in match_detail_reason(reused, None)
    ignored = MatchResult(match_status="ignored")
    assert "具体忽略原因未记录" in match_detail_reason(ignored, None)
    disabled = MatchResult(match_status="matched", is_disabled=1, disable_reason="异常销量")
    assert "当前结果已禁用：异常销量" in match_detail_reason(disabled, None)
    invalid = MatchResult(match_status="invalid_model", review_note="原型号已删除")
    assert "需重新选择" in match_detail_reason(invalid, None)
    assert "原型号已删除" in match_detail_reason(invalid, None)


def test_filter_reasons_preserve_snapshots_and_do_not_reconstruct_rules():
    snapshot = "命中旧规则：价格 < 100\n原始价格为 80；商品名包含赠品"
    entry = FilteredItem(matched_reason=snapshot, intervention_rule_name="现在的规则名")
    assert filter_detail_reason(entry) == snapshot
    entry.matched_reason = None
    assert "现在的规则名" in filter_detail_reason(entry)
    assert "完整过滤原因未记录" in filter_detail_reason(entry)
    assert "具体过滤原因未记录" in filter_detail_reason(FilteredItem())


def test_duplicate_reason_does_not_guess_unknown_keys():
    entry = CleanDuplicateRecord(kept_raw_data_id=10, dedup_basis="item_id_month_shop", dedup_key={"item_id": "1", "month": 202610, "shop_name": "店铺"})
    assert "商品 ID、月份、店铺名称完全相同" in duplicate_detail_reason(entry)
    assert "保留原始记录 #10" in duplicate_detail_reason(entry)
    entry.dedup_basis = "legacy"
    assert "具体去重依据未记录" in duplicate_detail_reason(entry)
    entry.kept_raw_data_id = None
    assert "保留记录的来源未记录" in duplicate_detail_reason(entry)


@pytest.fixture
def details_job(db):
    db.add_all([Category(code="camera", name="摄像头"), Category(code="other", name="其他")])
    upload = UploadFileRecord(filename="reason.xlsx", status="done")
    model = ModelRecord(brand_code="TEST", model_code="A1", category_code="camera")
    db.add_all([upload, model])
    db.flush()
    job = CleanJobRecord(file_ids=[upload.id], category_code="camera", status="reviewing", row_in=11, row_out=8, row_duplicated=1)
    rule = InterventionRule(name="赠品规则", category_code="camera", action="filter", conditions={"item_name_contains_any": ["赠品"]})
    db.add_all([job, rule])
    db.flush()
    outcomes = ["url_matched", "confirmed", "pending", "text_only", "excluded", "ignored", "disputed", None, "link", "rule", "duplicate"]
    raw_ids = {}
    for index, outcome in enumerate(outcomes):
        raw = RawDataRecord(file_id=upload.id, platform="jd", item_id=str(index), month=202610,
                            item_name=f"商品-{outcome}", price=100 + index, sales_qty=1)
        db.add(raw)
        db.flush()
        raw_ids[outcome] = raw.id
        if index < 8:
            db.add(CleanedDataRecord(clean_job_id=job.id, raw_data_id=raw.id, item_name=raw.item_name))
            if outcome is not None:
                db.add(MatchResult(clean_job_id=job.id, raw_data_id=raw.id, match_status=outcome,
                                   match_source="s0" if index == 0 else "s1", model_id=model.id if index in (0, 1, 3) else None,
                                   review_note="当时保存的人工备注" if index in (1, 4, 5) else None,
                                   dispute_reason="配置存在争议" if index == 6 else None))
        elif outcome in ("link", "rule"):
            db.add(FilteredItem(clean_job_id=job.id, raw_data_id=raw.id,
                                intervention_rule_id=rule.id if outcome == "rule" else None,
                                matched_reason=f"保存的{outcome}过滤原因"))
        else:
            db.add(CleanDuplicateRecord(clean_job_id=job.id, raw_data_id=raw.id, kept_raw_data_id=raw_ids["url_matched"],
                                       dedup_basis="item_id_month_shop", dedup_key={"item_id": "0", "month": 202610, "shop_name": None}))
    db.commit()
    return job.id, raw_ids


def test_every_record_has_a_reason_across_groups_and_reading_is_non_mutating(db, details_job):
    job_id, raw_ids = details_job
    client = _client(db)
    before = [(r.id, r.match_status, r.match_source, r.model_id, r.review_note) for r in db.query(MatchResult)]
    seen = set()
    for group, count in [("mapping", 2), ("other", 6), ("interference_link", 1), ("interference_archive", 1), ("duplicates", 1)]:
        response = client.get(f"/api/clean/jobs/{job_id}/matched", params={"group": group})
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["total"] == payload["counts"][group] == count
        assert payload["accounting"]["status"] == "balanced"
        assert all(item["clean_reason"] for item in payload["items"])
        ids = {item["raw_data_id"] for item in payload["items"]}
        assert not seen.intersection(ids)
        seen.update(ids)
    assert seen == set(raw_ids.values())
    after = [(r.id, r.match_status, r.match_source, r.model_id, r.review_note) for r in db.query(MatchResult)]
    assert after == before


def test_other_details_keep_pagination_filters_and_task_scope(db, details_job):
    job_id, raw_ids = details_job
    other_job = CleanJobRecord(file_ids=[], category_code="other", status="reviewing")
    db.add(other_job)
    db.flush()
    # The same raw row being matched in another task must not hide it here.
    db.add(MatchResult(clean_job_id=other_job.id, raw_data_id=raw_ids["pending"], match_status="confirmed"))
    db.commit()
    client = _client(db)
    response = client.get(f"/api/clean/jobs/{job_id}/matched", params={"group": "other", "keyword": "商品-pending", "price_min": 102, "price_max": 102})
    payload = response.json()
    assert payload["total"] == 1 and payload["counts"]["other"] == 6
    assert payload["items"][0]["raw_data_id"] == raw_ids["pending"]
    first = client.get(f"/api/clean/jobs/{job_id}/matched", params={"group": "other", "page_size": 2}).json()
    second = client.get(f"/api/clean/jobs/{job_id}/matched", params={"group": "other", "page_size": 2, "page": 2}).json()
    assert len(first["items"]) == len(second["items"]) == 2
    assert not {r["id"] for r in first["items"]}.intersection(r["id"] for r in second["items"])
    assert _client(db, category_permissions=["other"]).get(f"/api/clean/jobs/{job_id}/matched", params={"group": "other"}).status_code == 404
