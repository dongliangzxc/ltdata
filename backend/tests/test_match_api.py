from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.models.database import get_db
from app.models.schemas import (
    ModelRecord, UploadFileRecord, RawDataRecord,
    CleanJobRecord, MatchResult, ItemUrlMapping, CleanedDataRecord,
    HistoricalMapping, MatchResultAttr, MetadataSpec, ModelSpec, Category, AttrRule,
)
from app.api.match_api import confirm_match, router as match_router


@pytest.fixture()
def match_client(db):
    app = FastAPI()
    app.include_router(match_router)

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    return TestClient(app)


def _seed_review_row(
    db,
    *,
    clean_job_id,
    upload_id,
    model_id=None,
    status="matched",
    sales_qty=10,
    corrected_sales_qty=None,
    coefficient=None,
    price_flag=None,
    price_ref=None,
    item_name="测试商品",
):
    rd = RawDataRecord(
        file_id=upload_id,
        platform="jd",
        item_id=f"item-{status}-{sales_qty}-{item_name}",
        item_url=f"https://example.com/{status}/{sales_qty}",
        item_name=item_name,
        brand_raw="Sony",
        sales_qty=sales_qty,
    )
    db.add(rd)
    db.flush()

    if corrected_sales_qty is not None:
        db.add(CleanedDataRecord(
            clean_job_id=clean_job_id,
            raw_data_id=rd.id,
            platform="jd",
            corrected_sales_qty=corrected_sales_qty,
        ))

    mr = MatchResult(
        clean_job_id=clean_job_id,
        raw_data_id=rd.id,
        model_id=model_id,
        match_status=status,
        matched_by="auto",
        match_source="s1",
        sales_coefficient=coefficient,
        price_flag=price_flag,
        price_ref=price_ref,
    )
    db.add(mr)
    db.flush()
    return mr


def test_confirm_matched_backfills_null_url_mapping(db):
    """
    prev_status='matched' 且 item_url_mappings.model_id=NULL 时，
    确认后应回写 model_id。
    """
    model = ModelRecord(brand_code="Sony", model_code="WH-XM5", category_code="headphone")
    db.add(model)
    db.flush()

    upload = UploadFileRecord(filename="x.xlsx", status="done")
    db.add(upload)
    db.flush()

    clean_job = CleanJobRecord(file_ids=[upload.id], status="done")
    db.add(clean_job)
    db.flush()

    rd = RawDataRecord(
        file_id=upload.id,
        platform="jd",
        item_id="88888",
        item_url="https://item.jd.com/88888.html",
        item_name="索尼耳机",
        brand_raw="Sony",
    )
    db.add(rd)
    db.flush()

    db.add(ItemUrlMapping(
        platform="jd", item_id="88888",
        item_url="https://item.jd.com/88888.html", model_id=None,
    ))
    db.flush()

    mr = MatchResult(
        clean_job_id=clean_job.id,
        raw_data_id=rd.id,
        model_id=model.id,
        match_status="matched",
        matched_by="auto",
        match_source="s1",
    )
    db.add(mr)
    db.commit()

    confirm_match(mr.id, {"model_id": model.id}, db=db)

    mapping = db.query(ItemUrlMapping).filter_by(platform="jd", item_id="88888").first()
    assert mapping.model_id == model.id


def test_confirm_match_overwrites_existing_url_mapping_and_marks_manual(db):
    old_model = ModelRecord(brand_code="DJI", model_code="OSMO-OLD", category_code="camera")
    new_model = ModelRecord(brand_code="DJI", model_code="OSMO-NEW", category_code="camera")
    db.add_all([old_model, new_model])
    db.flush()

    upload = UploadFileRecord(filename="reselect.xlsx", status="done")
    db.add(upload)
    db.flush()

    clean_job = CleanJobRecord(file_ids=[upload.id], status="done")
    db.add(clean_job)
    db.flush()

    raw = RawDataRecord(
        file_id=upload.id,
        platform="jd",
        item_id="reselect-1001",
        item_url="https://item.jd.com/reselect-1001.html",
        item_name="大疆运动相机",
        brand_raw="大疆",
        price=1999,
    )
    db.add(raw)
    db.flush()

    db.add(ItemUrlMapping(
        platform="jd",
        item_id="reselect-1001",
        item_url="https://item.jd.com/reselect-1001.html",
        model_id=old_model.id,
        brand_code=old_model.brand_code,
        price=1888,
        source="s0",
    ))
    db.flush()

    match = MatchResult(
        clean_job_id=clean_job.id,
        raw_data_id=raw.id,
        model_id=old_model.id,
        match_status="matched",
        matched_by="auto",
        match_source="s1",
    )
    db.add(match)
    db.commit()

    response = confirm_match(match.id, {"model_id": new_model.id}, db=db)

    assert response.model_id == new_model.id
    assert response.match_status == "confirmed"
    assert response.matched_by == "manual"
    assert response.match_source == "manual"

    mapping = db.query(ItemUrlMapping).filter_by(platform="jd", item_id="reselect-1001").first()
    assert mapping is not None
    assert mapping.model_id == new_model.id
    assert mapping.brand_code == new_model.brand_code
    assert mapping.item_url == raw.item_url
    assert mapping.price == raw.price
    assert mapping.source == "match_confirm"


def test_confirm_match_model_correction_clears_obsolete_attrs_before_rerun(db, monkeypatch):
    old_model = ModelRecord(brand_code="Sony", model_code="OLD-TV", category_code="old-tv")
    new_model = ModelRecord(brand_code="Sony", model_code="NEW-TV", category_code="new-tv")
    db.add_all([old_model, new_model])
    db.flush()

    new_rule = AttrRule(
        keyword="OLED",
        match_type="contains",
        attr_name="屏幕类型",
        attr_value="OLED",
        category_code="new-tv",
    )
    db.add(new_rule)
    db.flush()

    upload = UploadFileRecord(filename="attr-correction.xlsx", status="done")
    db.add(upload)
    db.flush()

    clean_job = CleanJobRecord(file_ids=[upload.id], status="done")
    db.add(clean_job)
    db.flush()

    raw = RawDataRecord(
        file_id=upload.id,
        platform="jd",
        item_id="attr-correction-1001",
        item_url="https://item.jd.com/attr-correction-1001.html",
        item_name="Sony OLED 电视",
        brand_raw="Sony",
    )
    db.add(raw)
    db.flush()

    match = MatchResult(
        clean_job_id=clean_job.id,
        raw_data_id=raw.id,
        model_id=old_model.id,
        match_status="matched",
        matched_by="auto",
        match_source="s1",
    )
    db.add(match)
    db.flush()
    db.add(MatchResultAttr(match_result_id=match.id, attr_name="旧品类属性", attr_value="旧值"))
    db.commit()

    monkeypatch.setattr("app.api.match_api.audit_price", lambda *_args, **_kwargs: None)

    response = confirm_match(match.id, {"model_id": new_model.id}, db=db)

    assert response.model_id == new_model.id
    assert response.match_status == "confirmed"
    assert response.matched_by == "manual"
    assert response.match_source == "manual"

    attrs = db.query(MatchResultAttr).filter_by(match_result_id=match.id).order_by(MatchResultAttr.id).all()
    assert [(attr.attr_name, attr.attr_value, attr.rule_id) for attr in attrs] == [
        ("屏幕类型", "OLED", new_rule.id),
    ]


def test_confirm_historical_pending_does_not_query_historical_mappings(db, monkeypatch):
    model = ModelRecord(brand_code="Sony", model_code="WH-XM5-HIST", category_code="headphone")
    db.add(model)
    db.flush()

    upload = UploadFileRecord(filename="x.xlsx", status="done")
    db.add(upload)
    db.flush()

    clean_job = CleanJobRecord(file_ids=[upload.id], status="done")
    db.add(clean_job)
    db.flush()

    rd = RawDataRecord(
        file_id=upload.id,
        platform="jd",
        item_id="hist-pending-1",
        item_url="https://item.jd.com/hist-pending-1.html",
        item_name="历史待确认商品",
        brand_raw="Sony",
    )
    db.add(rd)
    db.flush()

    mr = MatchResult(
        clean_job_id=clean_job.id,
        raw_data_id=rd.id,
        model_id=None,
        match_status="pending",
        matched_by="auto",
        match_source="historical",
    )
    db.add(mr)
    db.commit()

    original_query = db.query

    def fail_on_historical_mapping(*entities, **kwargs):
        if any(entity is HistoricalMapping for entity in entities):
            raise AssertionError("confirm_match must not rewrite historical_mappings")
        return original_query(*entities, **kwargs)

    monkeypatch.setattr(db, "query", fail_on_historical_mapping)

    response = confirm_match(mr.id, {"model_id": model.id}, db=db)

    assert response.match_status == "confirmed"
    assert response.model_id == model.id


def test_match_summary_counts_disputed(db):
    from app.api.match_api import get_match_summary

    db.add_all([
        MatchResult(clean_job_id=9001, raw_data_id=1, match_status="pending"),
        MatchResult(clean_job_id=9001, raw_data_id=2, match_status="disputed"),
    ])
    db.commit()

    summary = get_match_summary(9001, db)

    assert summary.pending == 1
    assert summary.disputed == 1


def test_confirm_match_can_mark_disputed(db):
    upload = UploadFileRecord(filename="dispute.xlsx", status="done")
    db.add(upload)
    db.flush()
    raw = RawDataRecord(file_id=upload.id, item_name="争议商品", platform="jd", item_id="sku-9101")
    db.add(raw)
    db.flush()
    mr = MatchResult(clean_job_id=9100, raw_data_id=raw.id, match_status="pending")
    db.add(mr)
    db.commit()

    result = confirm_match(mr.id, {"disputed": True, "reason": "标题和链接信息冲突"}, db)

    assert result.match_status == "disputed"
    assert result.dispute_reason == "标题和链接信息冲突"
    assert result.review_note == "标题和链接信息冲突"
    assert result.reviewed_at is not None


def test_confirm_match_rejects_disputed_without_reason(db):
    upload = UploadFileRecord(filename="dispute-empty.xlsx", status="done")
    db.add(upload)
    db.flush()
    raw = RawDataRecord(file_id=upload.id, item_name="争议商品", platform="jd", item_id="sku-9102")
    db.add(raw)
    db.flush()
    mr = MatchResult(clean_job_id=9100, raw_data_id=raw.id, match_status="pending")
    db.add(mr)
    db.commit()

    with pytest.raises(Exception) as exc_info:
        confirm_match(mr.id, {"disputed": True, "reason": ""}, db)

    assert "暂存争议需填写原因" in str(exc_info.value)


def test_confirm_match_excluded_saves_reason(db):
    upload = UploadFileRecord(filename="exclude.xlsx", status="done")
    db.add(upload)
    db.flush()
    raw = RawDataRecord(file_id=upload.id, item_name="配件", platform="jd", item_id="sku-9111")
    db.add(raw)
    db.flush()
    mr = MatchResult(clean_job_id=9110, raw_data_id=raw.id, match_status="pending", model_id=1)
    db.add(mr)
    db.commit()

    result = confirm_match(mr.id, {"excluded": True, "reason": "配件不是整机"}, db)

    assert result.match_status == "excluded"
    assert result.model_id is None
    assert result.review_note == "配件不是整机"
    assert result.reviewed_at is not None


def test_revert_restores_state_before_exclude(db, match_client):
    """排除操作应可撤销回到操作前的 pending / matched 状态。"""
    model = ModelRecord(brand_code="DJI", model_code="Osmo-Action-6", category_code="camera")
    db.add(model)
    db.flush()
    upload = UploadFileRecord(filename="revert.xlsx", status="done")
    db.add(upload)
    db.flush()
    clean_job = CleanJobRecord(file_ids=[upload.id], status="done")
    db.add(clean_job)
    db.flush()
    raw = RawDataRecord(file_id=upload.id, item_name="配件", platform="jd", item_id="rev-1")
    db.add(raw)
    db.flush()
    mr = MatchResult(
        clean_job_id=clean_job.id,
        raw_data_id=raw.id,
        match_status="matched",
        matched_by="auto",
        match_source="s1",
        model_id=model.id,
    )
    db.add(mr)
    db.commit()

    excluded = confirm_match(mr.id, {"excluded": True, "reason": "点错了"}, db)
    assert excluded.match_status == "excluded"
    assert excluded.model_id is None

    revert_response = match_client.post(f"/api/match/items/{mr.id}/revert")
    assert revert_response.status_code == 200
    body = revert_response.json()
    assert body["match_status"] == "matched"
    assert body["model_id"] == model.id
    assert body["matched_by"] == "auto"
    assert body["match_source"] == "s1"
    assert body["revertible"] is False

    # 二次撤销应报 400，避免重复回滚
    again = match_client.post(f"/api/match/items/{mr.id}/revert")
    assert again.status_code == 400


def test_revert_without_snapshot_falls_back_to_pending(db, match_client):
    """迁移前遗留的已排除记录没有 prev_* 快照，撤销时兜底重置为 pending。"""
    upload = UploadFileRecord(filename="revert-legacy.xlsx", status="done")
    db.add(upload)
    db.flush()
    clean_job = CleanJobRecord(file_ids=[upload.id], status="done")
    db.add(clean_job)
    db.flush()
    raw = RawDataRecord(file_id=upload.id, item_name="遗留配件", platform="jd", item_id="rev-3")
    db.add(raw)
    db.flush()
    mr = MatchResult(
        clean_job_id=clean_job.id,
        raw_data_id=raw.id,
        match_status="excluded",
        matched_by="manual",
        review_note="旧数据",
    )
    db.add(mr)
    db.commit()

    response = match_client.post(f"/api/match/items/{mr.id}/revert")
    assert response.status_code == 200
    body = response.json()
    assert body["match_status"] == "pending"
    assert body["model_id"] is None
    assert body["review_note"] is None


def test_review_detail_exposes_revertible_after_exclude(db, match_client):
    upload = UploadFileRecord(filename="revert-detail.xlsx", status="done")
    db.add(upload)
    db.flush()
    clean_job = CleanJobRecord(file_ids=[upload.id], status="done")
    db.add(clean_job)
    db.flush()
    raw = RawDataRecord(file_id=upload.id, item_name="干扰配件", platform="jd", item_id="rev-2")
    db.add(raw)
    db.flush()
    mr = MatchResult(clean_job_id=clean_job.id, raw_data_id=raw.id, match_status="pending", matched_by="auto")
    db.add(mr)
    db.commit()

    confirm_match(mr.id, {"excluded": True, "reason": "点错了"}, db)

    detail = match_client.get(f"/api/match/items/{mr.id}/review-detail")
    assert detail.status_code == 200
    assert detail.json()["revertible"] is True


def test_pending_endpoint_allows_disputed_and_review_detail(db, match_client):
    model = ModelRecord(brand_code="Sony", model_code="WH-XM5", category_code="headphone")
    db.add(model)
    db.flush()
    upload = UploadFileRecord(filename="review-detail.xlsx", status="done")
    db.add(upload)
    db.flush()
    clean_job = CleanJobRecord(file_ids=[upload.id], status="done")
    db.add(clean_job)
    db.flush()
    raw = RawDataRecord(
        file_id=upload.id,
        platform="jd",
        item_id="sku-9201",
        item_url="https://item.jd.com/sku-9201.html",
        item_name="索尼耳机",
        brand_raw="SONY",
        shop_name="索尼旗舰店",
        sales_qty=12,
    )
    db.add(raw)
    db.flush()
    mr = MatchResult(
        clean_job_id=clean_job.id,
        raw_data_id=raw.id,
        model_id=model.id,
        match_status="disputed",
        matched_by="manual",
        match_source="s1",
        dispute_reason="需要复核",
    )
    db.add(mr)
    db.flush()
    db.add(ItemUrlMapping(platform="jd", item_id="sku-9201", item_url=raw.item_url, model_id=None, brand_code="Sony"))
    db.commit()

    list_response = match_client.get(f"/api/match/{clean_job.id}/pending", params={"status": "disputed"})
    assert list_response.status_code == 200
    assert list_response.json()["total"] == 1
    assert list_response.json()["items"][0]["dispute_reason"] == "需要复核"

    detail_response = match_client.get(f"/api/match/items/{mr.id}/review-detail")
    assert detail_response.status_code == 200
    body = detail_response.json()
    assert body["match_status"] == "disputed"
    assert body["item_url"] == raw.item_url
    assert body["shop_name"] == "索尼旗舰店"
    assert body["url_mapping"]["brand_code"] == "Sony"


def test_pending_endpoint_supports_reviewed_and_excluded_statuses(db, match_client):
    model = ModelRecord(brand_code="Sony", model_code="WH-XM5", category_code="headphone")
    db.add(model)
    db.flush()
    upload = UploadFileRecord(filename="review-queue.xlsx", status="done")
    db.add(upload)
    db.flush()
    clean_job = CleanJobRecord(file_ids=[upload.id], status="done")
    db.add(clean_job)
    db.flush()

    matched = _seed_review_row(db, clean_job_id=clean_job.id, upload_id=upload.id, model_id=model.id, status="matched", item_name="matched row")
    url_matched = _seed_review_row(db, clean_job_id=clean_job.id, upload_id=upload.id, model_id=model.id, status="url_matched", item_name="url row")
    confirmed = _seed_review_row(db, clean_job_id=clean_job.id, upload_id=upload.id, model_id=model.id, status="confirmed", item_name="confirmed row")
    excluded = _seed_review_row(db, clean_job_id=clean_job.id, upload_id=upload.id, status="excluded", item_name="excluded row")
    _seed_review_row(db, clean_job_id=clean_job.id, upload_id=upload.id, status="pending", item_name="pending row")
    db.commit()

    matched_response = match_client.get(f"/api/match/{clean_job.id}/pending", params={"status": "matched"})
    assert matched_response.status_code == 200
    assert matched_response.json()["total"] == 2
    assert {item["id"] for item in matched_response.json()["items"]} == {matched.id, url_matched.id}

    confirmed_response = match_client.get(f"/api/match/{clean_job.id}/pending", params={"status": "confirmed"})
    assert confirmed_response.status_code == 200
    assert confirmed_response.json()["total"] == 1
    assert confirmed_response.json()["items"][0]["id"] == confirmed.id

    excluded_response = match_client.get(f"/api/match/{clean_job.id}/pending", params={"status": "excluded"})
    assert excluded_response.status_code == 200
    assert excluded_response.json()["total"] == 1
    assert excluded_response.json()["items"][0]["id"] == excluded.id


def test_review_detail_returns_category_model_specs_and_match_attrs(db, match_client):
    category = Category(code="headphone", name="耳机")
    model = ModelRecord(brand_code="Sony", model_code="WH-1000XM5", category_code="headphone")
    db.add_all([category, model])
    db.flush()
    metadata_spec_noise = MetadataSpec(category_code="headphone", spec_name="降噪", spec_type="text", spec_values="主动降噪,被动降噪", required=1, single_select=1)
    metadata_spec_fit = MetadataSpec(category_code="headphone", spec_name="佩戴方式", spec_type="text", spec_values="头戴式,入耳式", required=0, single_select=1)
    model_spec = ModelSpec(model_id=model.id, spec_name="降噪", spec_value="主动降噪")
    db.add_all([
        metadata_spec_noise,
        metadata_spec_fit,
        model_spec,
    ])
    upload = UploadFileRecord(filename="detail-attrs.xlsx", status="done")
    db.add(upload)
    db.flush()
    clean_job = CleanJobRecord(file_ids=[upload.id], status="reviewing", category_code="headphone")
    db.add(clean_job)
    db.flush()
    raw = RawDataRecord(file_id=upload.id, platform="jd", item_id="sku-attr", item_name="Sony WH-1000XM5 主动降噪", brand_raw="Sony")
    db.add(raw)
    db.flush()
    mr = MatchResult(clean_job_id=clean_job.id, raw_data_id=raw.id, model_id=model.id, match_status="confirmed")
    db.add(mr)
    db.flush()
    match_attr = MatchResultAttr(match_result_id=mr.id, attr_name="佩戴方式", attr_value="头戴式")
    db.add(match_attr)
    db.commit()

    response = match_client.get(f"/api/match/items/{mr.id}/review-detail")

    assert response.status_code == 200
    body = response.json()
    assert body["category_code"] == "headphone"
    assert body["category_name"] == "耳机"
    assert body["metadata_specs"] == [
        {
            "id": metadata_spec_noise.id,
            "spec_name": "降噪",
            "spec_type": "text",
            "spec_values": "主动降噪,被动降噪",
            "required": True,
            "decimal_places": None,
            "single_select": True,
        },
        {
            "id": metadata_spec_fit.id,
            "spec_name": "佩戴方式",
            "spec_type": "text",
            "spec_values": "头戴式,入耳式",
            "required": False,
            "decimal_places": None,
            "single_select": True,
        },
    ]
    assert body["model_specs"] == [{"id": model_spec.id, "spec_name": "降噪", "spec_value": "主动降噪"}]
    assert body["match_attrs"] == [{"id": match_attr.id, "attr_name": "佩戴方式", "attr_value": "头戴式", "rule_id": None}]


def test_reviewed_endpoint_returns_only_reviewable_rows_with_price_and_quantity_fields(db, match_client):
    model = ModelRecord(brand_code="Sony", model_code="WH-XM5", category_code="headphone")
    db.add(model)
    db.flush()
    upload = UploadFileRecord(filename="review.xlsx", status="done")
    db.add(upload)
    db.flush()
    clean_job = CleanJobRecord(file_ids=[upload.id], status="done")
    other_job = CleanJobRecord(file_ids=[upload.id], status="done")
    db.add_all([clean_job, other_job])
    db.flush()

    matched = _seed_review_row(
        db,
        clean_job_id=clean_job.id,
        upload_id=upload.id,
        model_id=model.id,
        status="matched",
        sales_qty=10,
        corrected_sales_qty=12,
        coefficient=1.5,
        price_flag="high",
        price_ref=99.99,
        item_name="matched row",
    )
    url_matched = _seed_review_row(
        db,
        clean_job_id=clean_job.id,
        upload_id=upload.id,
        model_id=model.id,
        status="url_matched",
        sales_qty=7,
        corrected_sales_qty=None,
        item_name="url row",
    )
    confirmed = _seed_review_row(
        db,
        clean_job_id=clean_job.id,
        upload_id=upload.id,
        model_id=model.id,
        status="confirmed",
        sales_qty=9,
        corrected_sales_qty=8,
        coefficient=0,
        item_name="confirmed row",
    )
    _seed_review_row(db, clean_job_id=clean_job.id, upload_id=upload.id, status="pending", item_name="pending row")
    _seed_review_row(db, clean_job_id=clean_job.id, upload_id=upload.id, status="text_only", item_name="text row")
    _seed_review_row(db, clean_job_id=clean_job.id, upload_id=upload.id, status="excluded", item_name="excluded row")
    _seed_review_row(db, clean_job_id=other_job.id, upload_id=upload.id, status="matched", item_name="other job row")
    db.commit()

    response = match_client.get(f"/api/match/{clean_job.id}/reviewed")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    items_by_id = {item["id"]: item for item in body["items"]}
    assert set(items_by_id) == {matched.id, url_matched.id, confirmed.id}

    matched_item = items_by_id[matched.id]
    assert matched_item["price_flag"] == "high"
    assert matched_item["price_ref"] == 99.99
    assert matched_item["sales_coefficient"] == 1.5
    assert matched_item["corrected_sales_qty"] == 12
    assert matched_item["adjusted_sales_qty"] == 18
    assert matched_item["model_code"] == "WH-XM5"
    assert matched_item["brand_code"] == "Sony"
    assert "attr_count" in matched_item

    url_item = items_by_id[url_matched.id]
    assert url_item["corrected_sales_qty"] == 7
    assert url_item["adjusted_sales_qty"] == 7

    confirmed_item = items_by_id[confirmed.id]
    assert confirmed_item["sales_coefficient"] == 0.0
    assert confirmed_item["corrected_sales_qty"] == 8
    assert confirmed_item["adjusted_sales_qty"] == 0


def test_patch_coefficient_sets_updates_and_clears_quantity_preview(db, match_client):
    model = ModelRecord(brand_code="Sony", model_code="WH-XM5")
    db.add(model)
    db.flush()
    upload = UploadFileRecord(filename="coef.xlsx", status="done")
    db.add(upload)
    db.flush()
    clean_job = CleanJobRecord(file_ids=[upload.id], status="done")
    db.add(clean_job)
    db.flush()
    mr = _seed_review_row(
        db,
        clean_job_id=clean_job.id,
        upload_id=upload.id,
        model_id=model.id,
        status="matched",
        sales_qty=10,
        corrected_sales_qty=11,
    )
    db.commit()

    response = match_client.patch(f"/api/match/{mr.id}/coefficient", json={"coefficient": 1.25})
    assert response.status_code == 200
    assert response.json()["sales_coefficient"] == 1.25
    assert response.json()["corrected_sales_qty"] == 11
    assert response.json()["adjusted_sales_qty"] == 14

    response = match_client.patch(f"/api/match/{mr.id}/coefficient", json={"coefficient": 2})
    assert response.status_code == 200
    assert response.json()["sales_coefficient"] == 2.0
    assert response.json()["adjusted_sales_qty"] == 22

    response = match_client.patch(f"/api/match/{mr.id}/coefficient", json={"coefficient": None})
    assert response.status_code == 200
    assert response.json()["sales_coefficient"] is None
    assert response.json()["adjusted_sales_qty"] == 11


def test_sales_coefficient_persistence_precision_matches_api_limit():
    column_type = MatchResult.__table__.c.sales_coefficient.type
    assert column_type.precision == 7
    assert column_type.scale == 4


def test_patch_coefficient_validation_rejects_out_of_range_and_accepts_zero(db, match_client):
    upload = UploadFileRecord(filename="validation.xlsx", status="done")
    db.add(upload)
    db.flush()
    clean_job = CleanJobRecord(file_ids=[upload.id], status="done")
    db.add(clean_job)
    db.flush()
    mr = _seed_review_row(
        db,
        clean_job_id=clean_job.id,
        upload_id=upload.id,
        status="matched",
        sales_qty=10,
        corrected_sales_qty=10,
    )
    db.commit()

    assert match_client.patch(f"/api/match/{mr.id}/coefficient", json={"coefficient": -0.1}).status_code == 400
    assert match_client.patch(f"/api/match/{mr.id}/coefficient", json={"coefficient": 1000}).status_code == 400
    assert match_client.patch(f"/api/match/{mr.id}/coefficient", json={"coefficient": "1.2"}).status_code == 400

    response = match_client.patch(f"/api/match/{mr.id}/coefficient", json={"coefficient": 999.9999})
    assert response.status_code == 200
    assert response.json()["sales_coefficient"] == 999.9999
    assert response.json()["adjusted_sales_qty"] == 10000

    response = match_client.patch(f"/api/match/{mr.id}/coefficient", json={"coefficient": 0})
    assert response.status_code == 200
    assert response.json()["sales_coefficient"] == 0.0
    assert response.json()["adjusted_sales_qty"] == 0


def test_same_title_preview_uses_normalized_title_and_actionable_statuses(db, match_client):
    upload = UploadFileRecord(filename="same-title.xlsx", status="done")
    db.add(upload)
    db.flush()
    clean_job = CleanJobRecord(file_ids=[upload.id], status="reviewing")
    db.add(clean_job)
    db.flush()

    raw_rows = [
        RawDataRecord(file_id=upload.id, platform="jd", item_id="sku-1", item_name=" Sony  WH-1000XM5！", brand_raw="Sony", sales_qty=10),
        RawDataRecord(file_id=upload.id, platform="jd", item_id="sku-2", item_name="sony wh 1000xm5", brand_raw="Sony", sales_qty=20),
        RawDataRecord(file_id=upload.id, platform="jd", item_id="sku-3", item_name="SONY、WH·1000XM5", brand_raw="Sony", sales_qty=30),
        RawDataRecord(file_id=upload.id, platform="jd", item_id="sku-4", item_name="Bose QC Ultra", brand_raw="Bose", sales_qty=40),
    ]
    db.add_all(raw_rows)
    db.flush()
    match_rows = [
        MatchResult(clean_job_id=clean_job.id, raw_data_id=raw_rows[0].id, match_status="pending"),
        MatchResult(clean_job_id=clean_job.id, raw_data_id=raw_rows[1].id, match_status="text_only"),
        MatchResult(clean_job_id=clean_job.id, raw_data_id=raw_rows[2].id, match_status="confirmed"),
        MatchResult(clean_job_id=clean_job.id, raw_data_id=raw_rows[3].id, match_status="pending"),
    ]
    db.add_all(match_rows)
    db.commit()

    response = match_client.get(f"/api/match/items/{match_rows[0].id}/same-title-preview")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert body["actionable_count"] == 2
    assert body["status_counts"] == {"confirmed": 1, "pending": 1, "text_only": 1}
    assert [item["id"] for item in body["items"]] == [match_rows[0].id, match_rows[1].id, match_rows[2].id]
    assert body["items"][0]["item_name"] == " Sony  WH-1000XM5！"
    assert body["items"][0]["sales_qty"] == 10


def test_same_title_confirm_updates_actionable_rows_and_writes_url_mappings(db, match_client):
    model = ModelRecord(brand_code="Sony", model_code="WH-1000XM5", category_code="headphone")
    existing_model = ModelRecord(brand_code="Bose", model_code="QC-Ultra", category_code="headphone")
    db.add_all([model, existing_model])
    db.flush()
    upload = UploadFileRecord(filename="same-confirm.xlsx", status="done")
    db.add(upload)
    db.flush()
    clean_job = CleanJobRecord(file_ids=[upload.id], status="reviewing")
    db.add(clean_job)
    db.flush()

    raw_rows = [
        RawDataRecord(file_id=upload.id, platform="jd", item_id="sku-a", item_url="https://item.jd.com/sku-a.html", item_name="Sony WH-1000XM5", brand_raw="Sony"),
        RawDataRecord(file_id=upload.id, platform="jd", item_id="sku-b", item_url="https://item.jd.com/sku-b.html", item_name="sony wh 1000xm5", brand_raw="Sony"),
        RawDataRecord(file_id=upload.id, platform="jd", item_id="sku-c", item_url="https://item.jd.com/sku-c.html", item_name="Sony WH-1000XM5", brand_raw="Sony"),
    ]
    db.add_all(raw_rows)
    db.flush()
    existing_reviewed_at = datetime(2026, 1, 2, 3, 4, 5)
    match_rows = [
        MatchResult(clean_job_id=clean_job.id, raw_data_id=raw_rows[0].id, match_status="pending"),
        MatchResult(clean_job_id=clean_job.id, raw_data_id=raw_rows[1].id, match_status="disputed", dispute_reason="待复核"),
        MatchResult(
            clean_job_id=clean_job.id,
            raw_data_id=raw_rows[2].id,
            match_status="confirmed",
            model_id=existing_model.id,
            matched_by="legacy",
            match_source="s1",
            review_note="人工已确认，禁止覆盖",
            reviewed_at=existing_reviewed_at,
        ),
    ]
    db.add_all(match_rows)
    db.commit()

    response = match_client.post(
        f"/api/match/items/{match_rows[0].id}/same-title-confirm",
        json={"model_id": model.id, "include_statuses": ["pending", "text_only", "disputed"]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["affected_count"] == 2
    assert body["url_mapping_count"] == 2
    refreshed = {row.id: row for row in db.query(MatchResult).all()}
    assert refreshed[match_rows[0].id].match_status == "confirmed"
    assert refreshed[match_rows[0].id].model_id == model.id
    assert refreshed[match_rows[0].id].match_source == "manual"
    assert refreshed[match_rows[1].id].match_status == "confirmed"
    assert refreshed[match_rows[1].id].dispute_reason is None
    assert refreshed[match_rows[2].id].match_status == "confirmed"
    assert refreshed[match_rows[2].id].model_id == existing_model.id
    assert refreshed[match_rows[2].id].matched_by == "legacy"
    assert refreshed[match_rows[2].id].match_source == "s1"
    assert refreshed[match_rows[2].id].review_note == "人工已确认，禁止覆盖"
    assert refreshed[match_rows[2].id].reviewed_at == existing_reviewed_at
    assert db.query(ItemUrlMapping).filter(ItemUrlMapping.model_id == model.id).count() == 2


def test_same_title_exclude_updates_actionable_rows_without_url_mapping(db, match_client):
    model = ModelRecord(brand_code="Sony", model_code="WH-1000XM5", category_code="headphone")
    db.add(model)
    db.flush()
    upload = UploadFileRecord(filename="same-exclude.xlsx", status="done")
    db.add(upload)
    db.flush()
    clean_job = CleanJobRecord(file_ids=[upload.id], status="reviewing")
    db.add(clean_job)
    db.flush()

    raw_rows = [
        RawDataRecord(file_id=upload.id, platform="jd", item_id="sku-x", item_url="https://item.jd.com/sku-x.html", item_name="投影仪支架", brand_raw="配件"),
        RawDataRecord(file_id=upload.id, platform="jd", item_id="sku-y", item_url="https://item.jd.com/sku-y.html", item_name="投影仪 支架", brand_raw="配件"),
        RawDataRecord(file_id=upload.id, platform="jd", item_id="sku-z", item_url="https://item.jd.com/sku-z.html", item_name="投影仪支架", brand_raw="配件"),
    ]
    db.add_all(raw_rows)
    db.flush()
    match_rows = [
        MatchResult(clean_job_id=clean_job.id, raw_data_id=raw_rows[0].id, match_status="pending", model_id=model.id),
        MatchResult(clean_job_id=clean_job.id, raw_data_id=raw_rows[1].id, match_status="text_only", model_id=model.id),
        MatchResult(clean_job_id=clean_job.id, raw_data_id=raw_rows[2].id, match_status="confirmed", model_id=model.id),
    ]
    db.add_all(match_rows)
    db.commit()

    response = match_client.post(
        f"/api/match/items/{match_rows[0].id}/same-title-exclude",
        json={"reason": "不属于该品类", "include_statuses": ["pending", "text_only", "disputed"]},
    )

    assert response.status_code == 200
    assert response.json()["affected_count"] == 2
    refreshed = {row.id: row for row in db.query(MatchResult).all()}
    assert refreshed[match_rows[0].id].match_status == "excluded"
    assert refreshed[match_rows[0].id].model_id is None
    assert refreshed[match_rows[0].id].review_note == "不属于该品类"
    assert refreshed[match_rows[1].id].match_status == "excluded"
    assert refreshed[match_rows[2].id].match_status == "confirmed"
    assert db.query(ItemUrlMapping).count() == 0


def test_same_title_confirm_empty_include_statuses_affects_zero_rows(db, match_client):
    model = ModelRecord(brand_code="Sony", model_code="WH-1000XM5", category_code="headphone")
    db.add(model)
    db.flush()
    upload = UploadFileRecord(filename="same-empty.xlsx", status="done")
    db.add(upload)
    db.flush()
    clean_job = CleanJobRecord(file_ids=[upload.id], status="reviewing")
    db.add(clean_job)
    db.flush()
    raw_rows = [
        RawDataRecord(file_id=upload.id, platform="jd", item_id="empty-a", item_url="https://item.jd.com/empty-a.html", item_name="Sony WH-1000XM5", brand_raw="Sony"),
        RawDataRecord(file_id=upload.id, platform="jd", item_id="empty-b", item_url="https://item.jd.com/empty-b.html", item_name="sony wh 1000xm5", brand_raw="Sony"),
    ]
    db.add_all(raw_rows)
    db.flush()
    match_rows = [
        MatchResult(clean_job_id=clean_job.id, raw_data_id=raw_rows[0].id, match_status="pending"),
        MatchResult(clean_job_id=clean_job.id, raw_data_id=raw_rows[1].id, match_status="pending"),
    ]
    db.add_all(match_rows)
    db.commit()

    response = match_client.post(
        f"/api/match/items/{match_rows[0].id}/same-title-confirm",
        json={"model_id": model.id, "include_statuses": []},
    )

    assert response.status_code == 200
    assert response.json()["affected_count"] == 0
    refreshed = {row.id: row for row in db.query(MatchResult).all()}
    assert refreshed[match_rows[0].id].match_status == "pending"
    assert refreshed[match_rows[0].id].model_id is None
    assert refreshed[match_rows[1].id].match_status == "pending"
    assert refreshed[match_rows[1].id].model_id is None
    assert db.query(ItemUrlMapping).count() == 0


def test_same_title_confirm_rejects_invalid_include_statuses(db, match_client):
    model = ModelRecord(brand_code="Sony", model_code="WH-1000XM5", category_code="headphone")
    db.add(model)
    db.flush()
    upload = UploadFileRecord(filename="same-invalid.xlsx", status="done")
    db.add(upload)
    db.flush()
    clean_job = CleanJobRecord(file_ids=[upload.id], status="reviewing")
    db.add(clean_job)
    db.flush()
    raw = RawDataRecord(file_id=upload.id, platform="jd", item_id="invalid-a", item_name="Sony WH-1000XM5", brand_raw="Sony")
    db.add(raw)
    db.flush()
    match_row = MatchResult(clean_job_id=clean_job.id, raw_data_id=raw.id, match_status="pending")
    db.add(match_row)
    db.commit()

    non_list_response = match_client.post(
        f"/api/match/items/{match_row.id}/same-title-confirm",
        json={"model_id": model.id, "include_statuses": "pending"},
    )
    invalid_response = match_client.post(
        f"/api/match/items/{match_row.id}/same-title-confirm",
        json={"model_id": model.id, "include_statuses": ["confirmed"]},
    )

    assert non_list_response.status_code == 400
    assert "include_statuses 必须是数组" in non_list_response.json()["detail"]
    assert invalid_response.status_code == 400
    assert "不支持批量处理状态" in invalid_response.json()["detail"]


def test_same_title_confirm_runs_price_audit_without_committing(db, match_client, monkeypatch):
    model = ModelRecord(brand_code="Sony", model_code="WH-1000XM5", category_code="headphone")
    db.add(model)
    db.flush()
    upload = UploadFileRecord(filename="same-audit.xlsx", status="done")
    db.add(upload)
    db.flush()
    clean_job = CleanJobRecord(file_ids=[upload.id], status="reviewing")
    db.add(clean_job)
    db.flush()
    raw = RawDataRecord(file_id=upload.id, platform="jd", item_id="audit-a", item_url="https://item.jd.com/audit-a.html", item_name="Sony WH-1000XM5", brand_raw="Sony")
    db.add(raw)
    db.flush()
    match_row = MatchResult(clean_job_id=clean_job.id, raw_data_id=raw.id, match_status="pending")
    db.add(match_row)
    db.commit()
    audit_calls = []

    def fake_audit_price(_db, match_result_ids, commit=True):
        audit_calls.append({"match_result_ids": match_result_ids, "commit": commit})
        return {"items_processed": len(match_result_ids)}

    monkeypatch.setattr("app.api.match_api.audit_price", fake_audit_price)

    response = match_client.post(
        f"/api/match/items/{match_row.id}/same-title-confirm",
        json={"model_id": model.id, "include_statuses": ["pending"]},
    )

    assert response.status_code == 200
    assert audit_calls == [{"match_result_ids": [match_row.id], "commit": False}]


def _seed_pending_for_search(db, *, clean_job_id, upload_id, model_id, item_name, brand_raw):
    """辅助：构造一条 pending 状态的 MatchResult。"""
    rd = RawDataRecord(
        file_id=upload_id,
        platform="jd",
        item_id=f"sku-{item_name}",
        item_url=f"https://item.jd.com/{item_name}.html",
        item_name=item_name,
        brand_raw=brand_raw,
        sales_qty=10,
    )
    db.add(rd)
    db.flush()
    mr = MatchResult(
        clean_job_id=clean_job_id,
        raw_data_id=rd.id,
        model_id=model_id,
        match_status="pending",
        matched_by="auto",
        match_source="s1",
    )
    db.add(mr)
    db.flush()
    return mr


def test_pending_search_by_brand_raw_filters_on_raw_brand(db, match_client):
    from app.models.schemas import BrandRecord
    model_dji = ModelRecord(brand_code="DJI", model_code="Osmo6", category_code="camera")
    model_sony = ModelRecord(brand_code="Sony", model_code="WH-XM5", category_code="headphone")
    db.add_all([model_dji, model_sony])
    db.add(BrandRecord(brand_code="DJI", brand_name="大疆"))
    db.add(BrandRecord(brand_code="Sony", brand_name="索尼"))
    upload = UploadFileRecord(filename="search.xlsx", status="done")
    db.add(upload)
    db.flush()
    clean_job = CleanJobRecord(file_ids=[upload.id], status="done")
    db.add(clean_job)
    db.flush()
    dji_mr = _seed_pending_for_search(
        db, clean_job_id=clean_job.id, upload_id=upload.id,
        model_id=model_dji.id, item_name="Mavic 3 无人机", brand_raw="大疆DJI",
    )
    _seed_pending_for_search(
        db, clean_job_id=clean_job.id, upload_id=upload.id,
        model_id=model_sony.id, item_name="索尼耳机 WH-XM5", brand_raw="SONY 索尼",
    )
    db.commit()

    resp = match_client.get(
        f"/api/match/{clean_job.id}/pending",
        params={"status": "pending", "search_by": "brand_raw", "keyword": "大疆"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == dji_mr.id


def test_pending_search_by_item_name_default_preserves_previous_behavior(db, match_client):
    from app.models.schemas import BrandRecord
    model_dji = ModelRecord(brand_code="DJI", model_code="Osmo6", category_code="camera")
    db.add(model_dji)
    db.add(BrandRecord(brand_code="DJI", brand_name="大疆"))
    upload = UploadFileRecord(filename="search-name.xlsx", status="done")
    db.add(upload)
    db.flush()
    clean_job = CleanJobRecord(file_ids=[upload.id], status="done")
    db.add(clean_job)
    db.flush()
    hit = _seed_pending_for_search(
        db, clean_job_id=clean_job.id, upload_id=upload.id,
        model_id=model_dji.id, item_name="大疆无人机 Mavic 3", brand_raw="大疆",
    )
    _seed_pending_for_search(
        db, clean_job_id=clean_job.id, upload_id=upload.id,
        model_id=model_dji.id, item_name="配件套装", brand_raw="大疆",
    )
    db.commit()

    resp = match_client.get(
        f"/api/match/{clean_job.id}/pending",
        params={"status": "pending", "keyword": "Mavic"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == hit.id


def test_pending_search_by_brand_code_matches_code_or_brand_name(db, match_client):
    from app.models.schemas import BrandRecord
    model_dji = ModelRecord(brand_code="DJI", model_code="Osmo6", category_code="camera")
    model_sony = ModelRecord(brand_code="Sony", model_code="WH-XM5", category_code="headphone")
    db.add_all([model_dji, model_sony])
    db.add(BrandRecord(brand_code="DJI", brand_name="大疆"))
    db.add(BrandRecord(brand_code="Sony", brand_name="索尼"))
    upload = UploadFileRecord(filename="search-brand.xlsx", status="done")
    db.add(upload)
    db.flush()
    clean_job = CleanJobRecord(file_ids=[upload.id], status="done")
    db.add(clean_job)
    db.flush()
    dji_mr = _seed_pending_for_search(
        db, clean_job_id=clean_job.id, upload_id=upload.id,
        model_id=model_dji.id, item_name="Mavic 3", brand_raw="大疆",
    )
    _seed_pending_for_search(
        db, clean_job_id=clean_job.id, upload_id=upload.id,
        model_id=model_sony.id, item_name="WH-XM5", brand_raw="SONY",
    )
    db.commit()

    # 搜英文编码 DJI 命中
    resp_code = match_client.get(
        f"/api/match/{clean_job.id}/pending",
        params={"status": "pending", "search_by": "brand_code", "keyword": "DJI"},
    )
    assert resp_code.status_code == 200
    assert resp_code.json()["total"] == 1
    assert resp_code.json()["items"][0]["id"] == dji_mr.id

    # 搜中文名 大疆 也命中同一条
    resp_name = match_client.get(
        f"/api/match/{clean_job.id}/pending",
        params={"status": "pending", "search_by": "brand_code", "keyword": "大疆"},
    )
    assert resp_name.status_code == 200
    assert resp_name.json()["total"] == 1
    assert resp_name.json()["items"][0]["id"] == dji_mr.id


def test_pending_search_by_invalid_value_falls_back_to_item_name(db, match_client):
    model = ModelRecord(brand_code="DJI", model_code="Osmo6", category_code="camera")
    db.add(model)
    upload = UploadFileRecord(filename="search-fallback.xlsx", status="done")
    db.add(upload)
    db.flush()
    clean_job = CleanJobRecord(file_ids=[upload.id], status="done")
    db.add(clean_job)
    db.flush()
    hit = _seed_pending_for_search(
        db, clean_job_id=clean_job.id, upload_id=upload.id,
        model_id=model.id, item_name="Mavic 无人机", brand_raw="大疆",
    )
    _seed_pending_for_search(
        db, clean_job_id=clean_job.id, upload_id=upload.id,
        model_id=model.id, item_name="配件套装", brand_raw="大疆",
    )
    db.commit()

    resp = match_client.get(
        f"/api/match/{clean_job.id}/pending",
        params={"status": "pending", "search_by": "nonsense", "keyword": "Mavic"},
    )
    assert resp.status_code == 200
    assert resp.json()["total"] == 1
    assert resp.json()["items"][0]["id"] == hit.id


def test_confirm_single_review_pending_transitions_and_upserts_url_mapping(db):
    from app.api.match_api import confirm_single_review
    from app.models.schemas import (
        MatchResult,
        ModelRecord,
        RawDataRecord,
        ItemUrlMapping,
    )

    upload = UploadFileRecord(filename="task1.xlsx", status="done")
    db.add(upload); db.flush()
    rd = RawDataRecord(
        file_id=upload.id, platform="jd", item_id="10001",
        item_url="https://jd.com/10001", item_name="SJCAM速影 C200PRO",
        brand_raw="速影", price=724.6, sales_qty=18,
    )
    db.add(rd); db.flush()

    model = ModelRecord(brand_code="速影", model_code="C200PRO")
    db.add(model); db.flush()

    mr = MatchResult(
        clean_job_id=1, raw_data_id=rd.id, match_status="pending",
        matched_by="auto", match_source="text",
    )
    db.add(mr); db.commit()

    confirm_single_review(db, mr, model)
    db.commit()

    assert mr.match_status == "confirmed"
    assert mr.matched_by == "manual"
    assert mr.match_source == "manual"
    assert mr.model_id == model.id
    assert mr.reviewed_at is not None

    mapping = db.query(ItemUrlMapping).filter_by(platform="jd", item_id="10001").first()
    assert mapping is not None
    assert mapping.model_id == model.id
    assert mapping.brand_code == "速影"


# ── 批量确认接口（ids 模式）测试 ────────────────────────────────────────────

def test_batch_confirm_ids_mode_confirms_valid_and_reports_invalid(db, match_client):
    """ids 模式：混合有效+无效候选，逐条独立提交。"""
    from app.models.schemas import (
        MatchResult, MatchResultCandidate, ModelRecord, RawDataRecord,
        CleanJobRecord, UploadFileRecord,
    )

    upload = UploadFileRecord(filename="batch1.xlsx", status="done")
    db.add(upload); db.flush()

    job = CleanJobRecord(id=555, file_ids=[upload.id], status="done")
    db.add(job)

    model = ModelRecord(brand_code="速影", model_code="C200PRO")
    db.add(model); db.flush()

    def _pending(idx: int, status: str = "pending"):
        rd = RawDataRecord(
            file_id=upload.id, platform="jd", item_id=f"9{idx}",
            item_url=f"https://jd.com/9{idx}",
            item_name=f"商品{idx}", brand_raw="速影", price=1.0, sales_qty=1,
        )
        db.add(rd); db.flush()
        mr = MatchResult(
            clean_job_id=555, raw_data_id=rd.id, match_status=status,
            matched_by="auto", match_source="text", brand_identified=1,
        )
        db.add(mr); db.flush()
        cand = MatchResultCandidate(
            match_result_id=mr.id, model_id=model.id, match_source="text",
            score=100, rank=1,
        )
        db.add(cand)
        return mr

    mr_ok = _pending(1, "pending")
    mr_ok2 = _pending(2, "text_only")
    mr_wrong_status = _pending(3, "confirmed")   # 状态已变更（不在允许集合）
    db.commit()

    resp = match_client.post(
        f"/api/match/{555}/batch-confirm",
        json={"mode": "ids", "ids": [mr_ok.id, mr_ok2.id, mr_wrong_status.id]},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 3
    assert body["success"] == 2
    assert body["failed"] == 1
    assert body["truncated"] is False
    assert body["failures"][0]["id"] == mr_wrong_status.id
    assert body["failures"][0]["reason"] == "状态已变更"

    db.expire_all()
    assert db.query(MatchResult).get(mr_ok.id).match_status == "confirmed"
    assert db.query(MatchResult).get(mr_ok2.id).match_status == "confirmed"
    assert db.query(MatchResult).get(mr_wrong_status.id).match_status == "confirmed"  # 未变


def test_batch_confirm_ids_mode_flags_invalid_candidate_and_url_mapping_conflict(db, match_client):
    from app.models.schemas import (
        MatchResult, MatchResultCandidate, ModelRecord, RawDataRecord,
        ItemUrlMapping, CleanJobRecord, UploadFileRecord,
    )

    upload = UploadFileRecord(filename="batch2.xlsx", status="done")
    db.add(upload); db.flush()

    db.add(CleanJobRecord(id=556, file_ids=[upload.id], status="done"))

    good_model = ModelRecord(brand_code="速影", model_code="C200PRO")
    other_model = ModelRecord(brand_code="速影", model_code="C300")
    dash_model = ModelRecord(brand_code="速影", model_code="-")  # 无效
    db.add_all([good_model, other_model, dash_model]); db.flush()

    def _row(idx: int, cand_model: ModelRecord, brand_identified: int = 1):
        rd = RawDataRecord(
            file_id=upload.id, platform="jd", item_id=f"C{idx}",
            item_url=f"https://jd.com/C{idx}",
            item_name=f"P{idx}", brand_raw="速影", price=1.0, sales_qty=1,
        )
        db.add(rd); db.flush()
        mr = MatchResult(
            clean_job_id=556, raw_data_id=rd.id, match_status="pending",
            matched_by="auto", match_source="text",
            brand_identified=brand_identified,
        )
        db.add(mr); db.flush()
        db.add(MatchResultCandidate(
            match_result_id=mr.id, model_id=cand_model.id,
            match_source="text", score=100, rank=1,
        ))
        return mr, rd

    mr_invalid, _ = _row(1, dash_model)
    mr_unident, _ = _row(2, good_model, brand_identified=0)  # 未识别品牌
    mr_conflict, rd_conflict = _row(3, good_model)
    db.add(ItemUrlMapping(
        platform="jd", item_id="C3", item_url=rd_conflict.item_url,
        model_id=other_model.id, brand_code="速影", source="pre_existing",
    ))
    db.commit()

    resp = match_client.post(
        f"/api/match/{556}/batch-confirm",
        json={"mode": "ids", "ids": [mr_invalid.id, mr_unident.id, mr_conflict.id]},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    failures_by_id = {f["id"]: f["reason"] for f in body["failures"]}
    assert failures_by_id[mr_invalid.id] == "候选型号无效"
    assert failures_by_id[mr_unident.id] == "候选型号无效"
    assert "URL 映射冲突" in failures_by_id[mr_conflict.id]
    assert body["success"] == 0
    assert body["failed"] == 3


def test_batch_confirm_rejects_empty_ids(match_client):
    resp = match_client.post("/api/match/1/batch-confirm", json={"mode": "ids", "ids": []})
    assert resp.status_code == 400
    assert "ids 不能为空" in resp.text


def test_batch_confirm_rejects_over_limit_ids(match_client):
    resp = match_client.post(
        "/api/match/1/batch-confirm",
        json={"mode": "ids", "ids": list(range(1, 202))},
    )
    assert resp.status_code == 400
    assert "200" in resp.text


def test_batch_confirm_rejects_unknown_mode(match_client):
    resp = match_client.post("/api/match/1/batch-confirm", json={"mode": "wat"})
    assert resp.status_code == 400
