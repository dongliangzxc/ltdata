from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.analytics_db import AnalyticsBase, PublishedItem
from app.models.schemas import (
    CleanedDataRecord,
    CleanJobRecord,
    MatchResult,
    ModelRecord,
    RawDataRecord,
    UploadFileRecord,
)


@pytest.fixture
def analytics_db(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    AnalyticsBase.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    monkeypatch.setattr("app.services.price_auditor.AnalyticsSession", Session)

    session = Session()
    try:
        yield session
    finally:
        session.close()
        AnalyticsBase.metadata.drop_all(bind=engine)


def _seed_match_result(db, *, price=Decimal("110.00"), month=202607, status="matched"):
    upload = UploadFileRecord(
        filename="price-audit.xlsx",
        platform="jd",
        month_range=str(month),
        row_count=1,
    )
    db.add(upload)
    db.flush()

    raw = RawDataRecord(
        file_id=upload.id,
        platform="jd",
        month=month,
        item_id=f"item-{month}-{price}",
        item_name="Price Audit Item",
        brand_raw="TST",
        price=price,
    )
    db.add(raw)
    db.flush()

    clean_job = CleanJobRecord(
        file_ids=[upload.id],
        rules={},
        status="done",
        row_in=1,
        row_out=1,
    )
    db.add(clean_job)
    db.flush()

    model = ModelRecord(
        brand_code="TST",
        model_code="AUDIT-100",
        brand_name="Test Brand",
        model_name="Audit Model",
        category_code="test",
    )
    db.add(model)
    db.flush()

    match_result = MatchResult(
        clean_job_id=clean_job.id,
        raw_data_id=raw.id,
        model_id=model.id,
        match_status=status,
    )
    db.add(match_result)
    db.commit()
    return match_result.id


def _seed_history(
    analytics_db,
    *,
    model_code="AUDIT-100",
    months=(202601, 202602, 202603, 202604, 202605, 202606),
    price=Decimal("100.00"),
):
    for index, month in enumerate(months, start=1):
        analytics_db.add(
            PublishedItem(
                publish_job_id=1,
                clean_job_id=1,
                match_result_id=index,
                platform="jd",
                month=month,
                item_id=f"history-{month}",
                item_name="Historical Item",
                price=price,
                brand_code="TST",
                model_code=model_code,
                model_name="Audit Model",
            )
        )
    analytics_db.commit()


@pytest.mark.parametrize(
    ("current_price", "expected_flag"),
    [
        (Decimal("110.00"), "ok"),
        (Decimal("121.00"), "high"),
        (Decimal("79.00"), "low"),
    ],
)
def test_audit_price_flags_current_price_against_previous_six_month_average(
    db,
    analytics_db,
    current_price,
    expected_flag,
):
    from app.services.price_auditor import audit_price

    match_result_id = _seed_match_result(db, price=current_price, month=202607)
    _seed_history(analytics_db, price=Decimal("100.00"))

    result = audit_price(db, [match_result_id])

    match_result = db.get(MatchResult, match_result_id)
    assert result == {"audited": 1}
    assert match_result.price_flag == expected_flag
    assert match_result.price_ref == Decimal("100.00")


def test_audit_price_marks_no_history_when_analytics_history_missing(db, analytics_db):
    from app.services.price_auditor import audit_price

    match_result_id = _seed_match_result(db, price=Decimal("110.00"), month=202607)

    result = audit_price(db, [match_result_id])

    match_result = db.get(MatchResult, match_result_id)
    assert result == {"audited": 1}
    assert match_result.price_flag == "no_history"
    assert match_result.price_ref is None


def test_audit_price_marks_no_history_when_current_price_missing(db, analytics_db):
    from app.services.price_auditor import audit_price

    match_result_id = _seed_match_result(db, price=None, month=202607)
    _seed_history(analytics_db, price=Decimal("100.00"))

    result = audit_price(db, [match_result_id])

    match_result = db.get(MatchResult, match_result_id)
    assert result == {"audited": 1}
    assert match_result.price_flag == "no_history"
    assert match_result.price_ref is None


def test_run_match_triggers_price_audit_for_auto_matched_result(db, analytics_db):
    from app.services.matcher import run_match

    _seed_history(
        analytics_db,
        model_code="AUD100",
        months=(202510, 202511, 202512, 202601, 202602, 202603),
        price=Decimal("100.00"),
    )

    upload = UploadFileRecord(
        filename="price-audit-match.xlsx",
        platform="jd",
        month_range="202604",
        row_count=1,
    )
    db.add(upload)
    db.flush()

    model = ModelRecord(
        brand_code="AUD",
        model_code="AUD100",
        brand_name="Audit Brand",
        model_name="Audit Model 100",
        category_code="test",
    )
    db.add(model)
    db.flush()

    raw = RawDataRecord(
        file_id=upload.id,
        platform="jd",
        month=202604,
        item_id="audit-current-202604",
        item_name="Audit Brand AUD100 current item",
        brand_raw="AUD",
        price=Decimal("121.00"),
    )
    db.add(raw)
    db.flush()

    job = CleanJobRecord(
        file_ids=[upload.id],
        rules={},
        status="done",
        row_in=1,
        row_out=1,
    )
    db.add(job)
    db.flush()

    db.add(CleanedDataRecord(
        raw_data_id=raw.id,
        clean_job_id=job.id,
        platform="jd",
        month=202604,
        item_id="audit-current-202604",
        item_name="Audit Brand AUD100 current item",
        brand_raw="AUD",
        price=Decimal("121.00"),
    ))
    db.commit()

    result = run_match(db, job.id)

    match_result = db.query(MatchResult).filter(MatchResult.clean_job_id == job.id).one()
    assert result == {"total": 1, "matched": 1, "pending": 0}
    assert match_result.price_flag == "high"
    assert match_result.price_ref == Decimal("100.00")
