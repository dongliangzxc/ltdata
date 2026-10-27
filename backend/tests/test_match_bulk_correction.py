"""Bulk coefficient and correction import tests."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import match_api
from app.api.match_api import router
from app.core.auth_deps import get_current_user
from app.models.database import Base, get_db
from app.models.schemas import (
    Category,
    CleanJobRecord,
    MatchResult,
    ModelRecord,
    RawDataRecord,
    UploadFileRecord,
)


class DummyUser:
    is_admin = 1
    permissions = []
    category_permissions = []


@pytest.fixture
def client(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: (lambda: None)()
    # Provide a real session per request.
    def override_db():
        session = Session()
        try:
            yield session
        finally:
            session.close()
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: DummyUser()
    monkeypatch.setattr(match_api, "audit_price", lambda *args, **kwargs: {"audited": 0})
    test_client = TestClient(app)
    test_client.Session = Session
    return test_client


def _seed(client, price=100):
    with client.Session() as db:
        db.add(Category(code="headphone", name="耳机"))
        db.add(ModelRecord(brand_code="BOSE", model_code="SB900", category_code="headphone", brand_name="Bose", model_name="Soundbar"))
        upload = UploadFileRecord(filename="test.xlsx", platform="jd", row_count=1, status="done")
        db.add(upload)
        db.flush()
        job = CleanJobRecord(file_ids=[upload.id], status="reviewing", category_code="headphone")
        db.add(job)
        db.flush()
        raw = RawDataRecord(
            file_id=upload.id, platform="jd", month=202609, item_id="item-1",
            item_name="Original name", price=price, sales_qty=10, sales_amount=1000,
        )
        db.add(raw)
        db.flush()
        model = db.query(ModelRecord).filter_by(model_code="SB900").one()
        match = MatchResult(
            clean_job_id=job.id, raw_data_id=raw.id, model_id=model.id,
            match_status="matched", matched_by="auto", match_source="s1",
            adjusted_price=110,
        )
        db.add(match)
        db.commit()
        return job.id, match.id


def test_bulk_sales_coefficient(client):
    job_id, match_id = _seed(client)
    res = client.post("/api/match/reviewed/bulk-coefficient", json={
        "clean_job_id": job_id, "tab": "all", "target": "sales", "coefficient": 1.1,
    })
    assert res.status_code == 200, res.text
    assert res.json()["updated_count"] == 1
    with client.Session() as db:
        assert float(db.query(MatchResult).filter_by(id=match_id).one().sales_coefficient) == 1.1


def test_bulk_price_coefficient(client):
    job_id, match_id = _seed(client, price=100)
    res = client.post("/api/match/reviewed/bulk-coefficient", json={
        "clean_job_id": job_id, "tab": "all", "target": "price", "coefficient": 0.9,
    })
    assert res.status_code == 200, res.text
    with client.Session() as db:
        assert float(db.query(MatchResult).filter_by(id=match_id).one().adjusted_price) == 90.0


def test_bulk_sales_coefficient_respects_excluded_ids(client):
    job_id, first_match_id = _seed(client)
    with client.Session() as db:
        job = db.query(CleanJobRecord).filter_by(id=job_id).one()
        upload = db.query(UploadFileRecord).first()
        model = db.query(ModelRecord).filter_by(model_code="SB900").one()
        raw = RawDataRecord(
            file_id=upload.id, platform="jd", month=202609, item_id="item-2",
            item_name="Second name", price=50, sales_qty=5, sales_amount=250,
        )
        db.add(raw)
        db.flush()
        second = MatchResult(
            clean_job_id=job.id, raw_data_id=raw.id, model_id=model.id,
            match_status="matched", matched_by="auto", match_source="s1",
        )
        db.add(second)
        db.commit()
        second_match_id = second.id

    res = client.post("/api/match/reviewed/bulk-coefficient", json={
        "clean_job_id": job_id, "tab": "all", "target": "sales",
        "coefficient": 1.2, "exclude_ids": [first_match_id],
    })
    assert res.status_code == 200, res.text
    assert res.json()["updated_count"] == 1
    with client.Session() as db:
        assert db.query(MatchResult).filter_by(id=first_match_id).one().sales_coefficient is None
        assert float(db.query(MatchResult).filter_by(id=second_match_id).one().sales_coefficient) == 1.2
