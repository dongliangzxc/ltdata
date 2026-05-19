import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.models.database import get_db
from app.models.schemas import (
    ModelRecord, UploadFileRecord, RawDataRecord,
    CleanJobRecord, MatchResult, ItemUrlMapping, CleanedDataRecord,
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
