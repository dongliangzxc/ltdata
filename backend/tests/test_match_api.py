import pytest
from app.models.schemas import (
    ModelRecord, UploadFileRecord, RawDataRecord,
    CleanJobRecord, MatchResult, ItemUrlMapping,
)
from app.api.match_api import confirm_match


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
