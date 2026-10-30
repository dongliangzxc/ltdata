from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.match_api import router as match_router
from app.models.database import get_db
from app.models.schemas import (
    CleanJobRecord,
    CleanedDataRecord,
    MatchResult,
    RawDataRecord,
    UploadFileRecord,
)


@pytest.fixture()
def match_client(db):
    app = FastAPI()
    app.include_router(match_router)

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    return TestClient(app)


def _seed_summary_rows(db):
    upload = UploadFileRecord(filename="summary.xlsx", status="done")
    db.add(upload)
    db.flush()
    job = CleanJobRecord(file_ids=[upload.id], status="reviewed")
    db.add(job)
    db.flush()

    raw_one = RawDataRecord(file_id=upload.id, platform="jd", sales_qty=10, price=100)
    raw_two = RawDataRecord(file_id=upload.id, platform="jd", sales_qty=5, price=200)
    db.add_all([raw_one, raw_two])
    db.flush()
    db.add_all([
        MatchResult(
            clean_job_id=job.id, raw_data_id=raw_one.id,
            match_status="matched", matched_by="auto",
        ),
        MatchResult(
            clean_job_id=job.id, raw_data_id=raw_two.id,
            match_status="matched", matched_by="auto",
            sales_coefficient=2.0, adjusted_price=250,
        ),
    ])
    db.add(CleanedDataRecord(
        clean_job_id=job.id,
        raw_data_id=raw_two.id,
        corrected_sales_qty=8,
    ))
    db.commit()


def test_reviewed_summary_is_aggregated_in_database(match_client, db):
    _seed_summary_rows(db)

    response = match_client.get("/api/match/reviewed")
    assert response.status_code == 200, response.text
    assert response.json()["summary"] == {
        "original_price": 300.0,
        "adjusted_price": 350.0,
        "original_sales_qty": 15,
        "adjusted_sales_qty": 26,
        "original_consumption_amount": 2000.0,
        "adjusted_consumption_amount": 5000.0,
    }


def test_reviewed_summary_returns_zero_when_no_rows(match_client):
    response = match_client.get("/api/match/reviewed")
    assert response.status_code == 200, response.text
    assert response.json()["summary"] == {
        "original_price": 0.0,
        "adjusted_price": 0.0,
        "original_sales_qty": 0,
        "adjusted_sales_qty": 0,
        "original_consumption_amount": 0.0,
        "adjusted_consumption_amount": 0.0,
    }


def test_global_reviewed_route_summarizes_before_pagination():
    source = Path(__file__).resolve().parents[1] / "app" / "api" / "match_api.py"
    text = source.read_text()
    route_index = text.index('@router.get("/reviewed", response_model=None)')
    next_route_index = text.index("\n@router.", route_index + 1)
    route_source = text[route_index:next_route_index]

    assert "_summarize_match_results_query(db, summary_q)" in route_source
    assert '"summary": summary' in route_source
    assert route_source.index("summary = _summarize_match_results_query") < route_source.index("offset((page - 1) * page_size)")
