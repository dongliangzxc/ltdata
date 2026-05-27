from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.clean import router
from app.models.database import get_db
from app.models.schemas import (
    CleanJobRecord,
    CleanedDataRecord,
    DispatchBatch,
    DispatchItem,
    RawDataRecord,
    UploadFileRecord,
)


def _make_client(db):
    app = FastAPI()
    app.include_router(router)

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    return TestClient(app)


def test_run_dispatch_batch_clean_creates_one_job_per_category(db):
    client = _make_client(db)
    file_record = UploadFileRecord(filename="dispatch-clean.xlsx", platform="jd", row_count=2, status="done")
    db.add(file_record)
    db.flush()
    first_raw = RawDataRecord(
        file_id=file_record.id,
        platform="jd",
        month=202605,
        item_id="laser-tv-1",
        item_name="海信激光电视",
        brand_raw="海信",
        sales_qty=10,
        sales_amount=1000,
    )
    second_raw = RawDataRecord(
        file_id=file_record.id,
        platform="jd",
        month=202605,
        item_id="tv-1",
        item_name="普通电视",
        brand_raw="TCL",
        sales_qty=5,
        sales_amount=500,
    )
    db.add_all([first_raw, second_raw])
    db.flush()
    batch = DispatchBatch(file_id=file_record.id, status="done", total_rows=2, dispatched_rows=3, unmatched_rows=0)
    db.add(batch)
    db.flush()
    db.add_all([
        DispatchItem(batch_id=batch.id, raw_data_id=first_raw.id, category_code="projector", matched_rule_id=1),
        DispatchItem(batch_id=batch.id, raw_data_id=first_raw.id, category_code="tv", matched_rule_id=2),
        DispatchItem(batch_id=batch.id, raw_data_id=second_raw.id, category_code="tv", matched_rule_id=3),
    ])
    db.commit()

    response = client.post(f"/api/clean/run-dispatch-batch", json={"dispatch_batch_id": batch.id, "rules": {"dedup": True}})

    assert response.status_code == 200
    payload = response.json()
    assert payload["dispatch_batch_id"] == batch.id
    assert [job["dispatch_category_code"] for job in payload["jobs"]] == ["projector", "tv"]
    jobs = db.query(CleanJobRecord).order_by(CleanJobRecord.dispatch_category_code).all()
    assert [(job.dispatch_category_code, job.row_in, job.row_out) for job in jobs] == [
        ("projector", 1, 1),
        ("tv", 2, 2),
    ]
    assert db.query(CleanedDataRecord).count() == 3
