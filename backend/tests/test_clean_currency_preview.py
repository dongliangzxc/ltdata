"""Clean preview returns country and CNY conversion values."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.clean import router
from app.core.auth_deps import get_current_user
from app.models.database import Base, get_db
from app.models.schemas import (
    CleanJobRecord,
    CleanedDataRecord,
    Country,
    ExchangeRate,
    UploadFileRecord,
)


class DummyUser:
    is_admin = 1
    category_permissions = []


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    app = FastAPI()
    app.include_router(router)

    def override_db():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: DummyUser()
    test_client = TestClient(app)
    test_client.Session = Session
    return test_client


def test_preview_includes_country_and_cny_amounts(client):
    with client.Session() as session:
        session.add_all([
            Country(code="CN", name_cn="中国", currency_code="CNY", region="domestic", is_active=1),
            Country(code="US", name_cn="美国", currency_code="USD", currency_symbol="$", region="overseas", is_active=1),
            ExchangeRate(country_code="US", currency_code="USD", rate_to_cny=7.2),
        ])
        upload = UploadFileRecord(filename="us.xlsx", platform="amazon", row_count=1, status="done", country_code="US")
        session.add(upload)
        session.flush()
        job = CleanJobRecord(file_ids=[upload.id], status="reviewing")
        session.add(job)
        session.flush()
        session.add(CleanedDataRecord(
            clean_job_id=job.id,
            country_code="US",
            platform="amazon",
            item_name="speaker",
            sales_qty=2,
            sales_amount=100,
            price=50,
        ))
        session.commit()
        job_id = job.id

    res = client.get(f"/api/clean/jobs/{job_id}/preview")
    assert res.status_code == 200, res.text
    payload = res.json()
    assert payload["rates"]["US"]["rate_to_cny"] == 7.2
    item = payload["items"][0]
    assert item["country_code"] == "US"
    assert item["currency_code"] == "USD"
    assert item["sales_amount_cny"] == 720.0
    assert item["price_cny"] == 360.0
