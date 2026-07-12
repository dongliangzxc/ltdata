from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.models.database import get_db
from app.models.schemas import (
    MatchTransferLog, MatchResult, RawDataRecord, ModelRecord,
    CleanJobRecord, UploadFileRecord, Category, CleanedDataRecord,
    ItemUrlMapping, MatchResultCandidate, MatchResultAttr,
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


def test_match_transfer_log_model_persists(db):
    log = MatchTransferLog(
        match_result_id=1,
        raw_data_id=2,
        from_clean_job_id=10,
        to_clean_job_id=20,
        operator=None,
        transferred_at=datetime(2026, 7, 12, 10, 0, 0),
    )
    db.add(log)
    db.commit()

    fetched = db.query(MatchTransferLog).first()
    assert fetched.match_result_id == 1
    assert fetched.from_clean_job_id == 10
    assert fetched.to_clean_job_id == 20
    assert fetched.transferred_at.year == 2026
