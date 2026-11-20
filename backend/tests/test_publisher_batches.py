from collections import Counter
from datetime import datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects import mysql

from app.models.analytics_db import AnalyticsBase, PublishedItem, PublishedItemSpec
from app.models.schemas import (
    CleanJobRecord, MatchResult, MatchResultAttr, ModelRecord, ModelSpec, RawDataRecord, UploadFileRecord,
)
from app.services import publisher
from tests.test_publisher import _row


@pytest.fixture
def analytics_db(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    AnalyticsBase.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False)()
    monkeypatch.setattr(publisher, "_ensure_analytics_tables", lambda: None)
    yield session
    session.close()
    engine.dispose()


def _seed(db, count=1005):
    upload = UploadFileRecord(filename="publish.xlsx", status="done")
    model = ModelRecord(brand_code="B", model_code="M", category_code="TV", model_name="model")
    job = CleanJobRecord(status="done", file_ids=[])
    db.add_all([upload, model, job])
    db.flush()
    db.bulk_insert_mappings(RawDataRecord, [dict(
        file_id=upload.id, platform="jd", month=202611, item_id=str(i), item_name=f"item{i}",
        sales_qty=10, sales_amount=1000, price=100,
    ) for i in range(count)])
    raw_ids = [r.id for r in db.query(RawDataRecord.id).order_by(RawDataRecord.id)]
    db.bulk_insert_mappings(MatchResult, [dict(
        clean_job_id=job.id, raw_data_id=raw_id, model_id=model.id,
        match_status="confirmed", matched_by="manual", sales_coefficient=2,
    ) for raw_id in raw_ids])
    db.add(ModelSpec(model_id=model.id, spec_name="size", spec_value="old"))
    first = db.query(MatchResult).order_by(MatchResult.id).first()
    db.add(MatchResultAttr(match_result_id=first.id, attr_name="size", attr_value="override"))
    db.commit()
    return job.id, model.id


def _snapshot(db):
    return (
        [dict(row._mapping) for row in db.query(*PublishedItem.__table__.c).order_by(PublishedItem.id)],
        [dict(row._mapping) for row in db.query(*PublishedItemSpec.__table__.c).order_by(PublishedItemSpec.id)],
    )


def test_publish_1005_items_and_specs_in_bounded_batches_and_one_transaction(db, analytics_db):
    job_id, _ = _seed(db)
    metrics = Counter()

    def execute(conn, cursor, statement, *args):
        if statement.startswith("INSERT INTO published_items "):
            metrics["items"] += 1
        if statement.startswith("INSERT INTO published_item_specs "):
            metrics["specs"] += 1

    def commit(session):
        metrics["commits"] += 1

    event.listen(analytics_db.bind, "before_cursor_execute", execute)
    event.listen(analytics_db, "after_commit", commit)
    try:
        result = publisher.run_publish(db, analytics_db, job_id)
    finally:
        event.remove(analytics_db.bind, "before_cursor_execute", execute)
        event.remove(analytics_db, "after_commit", commit)
    assert result == {"published_count": 1005, "skipped_pending_count": 0}
    assert metrics == {"items": 2, "specs": 2, "commits": 1}
    first = analytics_db.query(PublishedItem).filter_by(item_id="0").one()
    assert first.corrected_sales_qty == 20
    assert float(first.corrected_sales_amount) == 2000
    assert analytics_db.query(PublishedItemSpec).filter_by(published_item_id=first.id).one().spec_value == "override"
    publisher.run_publish(db, analytics_db, job_id)
    assert analytics_db.query(PublishedItem).count() == 1005
    assert analytics_db.query(PublishedItemSpec).count() == 1005


@pytest.mark.parametrize("stage", ["items", "specs"])
def test_later_batch_failure_restores_previous_publication_on_rollback(db, analytics_db, stage):
    job_id, _ = _seed(db)
    publisher.run_publish(db, analytics_db, job_id)
    before = _snapshot(analytics_db)
    calls = 0

    def fail(conn, cursor, statement, *args):
        nonlocal calls
        table = "published_items" if stage == "items" else "published_item_specs"
        if statement.startswith(f"INSERT INTO {table} "):
            calls += 1
            if calls == 2:
                raise RuntimeError("synthetic later batch failure")

    event.listen(analytics_db.bind, "before_cursor_execute", fail)
    try:
        with pytest.raises(RuntimeError, match="later batch"):
            publisher.run_publish(db, analytics_db, job_id)
        analytics_db.rollback()
    finally:
        event.remove(analytics_db.bind, "before_cursor_execute", fail)
    assert _snapshot(analytics_db) == before


def test_duplicate_item_across_batches_keeps_last_values_and_one_spec_set(db, analytics_db):
    job_id, _ = _seed(db)
    first, last = [db.query(RawDataRecord).order_by(order).first()
                   for order in (RawDataRecord.id.asc(), RawDataRecord.id.desc())]
    last.country_code = "US"  # raw uniqueness includes country; published uniqueness does not
    last.item_id = first.item_id
    last.item_name = "last value"
    db.commit()
    result = publisher.run_publish(db, analytics_db, job_id)
    assert result["published_count"] == 1004
    assert analytics_db.query(PublishedItem).count() == 1004
    assert analytics_db.query(PublishedItemSpec).count() == 1004
    item = analytics_db.query(PublishedItem).filter_by(item_id=first.item_id).one()
    assert item.item_name == "last value"
    # Attribute belongs to the first source row; the last winning row uses model specs.
    assert analytics_db.query(PublishedItemSpec).filter_by(published_item_id=item.id).one().spec_value == "old"


def test_pending_and_disabled_rows_still_do_not_publish(db, analytics_db):
    job_id, _ = _seed(db, count=3)
    rows = db.query(MatchResult).order_by(MatchResult.id).all()
    rows[0].match_status = "pending"
    rows[1].is_disabled = 1
    db.commit()
    result = publisher.run_publish(db, analytics_db, job_id)
    assert result == {"published_count": 1, "skipped_pending_count": 1}
    assert analytics_db.query(PublishedItem).count() == 1


def test_mysql_upsert_compiles_bounded_values_and_preserves_update_policy():
    statements = []
    fake_db = SimpleNamespace(
        get_bind=lambda: SimpleNamespace(dialect=mysql.dialect()),
        execute=lambda statement: statements.append(statement),
    )
    rows = [publisher._build_published_item_params(_row(item_id=str(i)), 7, datetime(2026, 11, 19))
            for i in range(1001)]
    publisher._upsert_published_items(fake_db, rows)
    assert len(statements) == 2
    sql = str(statements[0].compile(dialect=mysql.dialect()))
    assert "ON DUPLICATE KEY UPDATE" in sql
    assert "category_lv0 = VALUES(category_lv0)" in sql
    assert "category_lv1 = VALUES(category_lv1)" not in sql
