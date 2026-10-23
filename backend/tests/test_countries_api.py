"""Country and exchange-rate configuration API tests."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.countries_api import router
from app.core.auth_deps import get_current_user
from app.models.database import Base, get_db
from app.models.schemas import Country


class DummyUser:
    def __init__(self, *, is_admin=1, username="admin"):
        self.is_admin = is_admin
        self.username = username


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
    current_user = DummyUser(is_admin=1)

    def override_db():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: current_user
    test_client = TestClient(app)
    test_client.Session = Session
    test_client.current_user = current_user
    return test_client


def seed_cn(client):
    with client.Session() as session:
        session.add(Country(
            code="CN", name_cn="中国", name_en="China",
            currency_code="CNY", currency_symbol="¥",
            region="domestic", is_active=1, sort_order=0,
        ))
        session.commit()


def test_master_can_create_country_and_rate(client):
    seed_cn(client)

    res = client.post("/api/countries", json={
        "code": "us",
        "name_cn": "美国",
        "name_en": "United States",
        "currency_code": "usd",
        "currency_symbol": "$",
        "region": "overseas",
        "is_active": 1,
        "sort_order": 10,
    })
    assert res.status_code == 201, res.text
    assert res.json()["code"] == "US"
    assert res.json()["currency_code"] == "USD"

    res = client.post("/api/exchange-rates", json={
        "country_code": "US",
        "rate_to_cny": 7.2,
        "remark": "test",
    })
    assert res.status_code == 201, res.text
    rate = res.json()
    assert rate["country_code"] == "US"
    assert rate["currency_code"] == "USD"
    assert rate["rate_to_cny"] == 7.2

    options = client.get("/api/exchange-rates/options").json()
    assert {item["country_code"] for item in options} == {"CN", "US"}
    us = next(item for item in options if item["country_code"] == "US")
    assert us["rate_to_cny"] == 7.2


def test_non_master_cannot_write_country_config(client):
    seed_cn(client)
    client.current_user.is_admin = 0

    res = client.post("/api/countries", json={
        "code": "DE",
        "name_cn": "德国",
        "currency_code": "EUR",
        "region": "overseas",
    })
    assert res.status_code == 403

    res = client.get("/api/exchange-rates")
    assert res.status_code == 403


def test_country_options_are_readable_by_normal_user(client):
    seed_cn(client)
    client.current_user.is_admin = 0

    res = client.get("/api/countries/options")
    assert res.status_code == 200
    assert res.json()[0]["code"] == "CN"


def test_cannot_create_rate_for_cny(client):
    seed_cn(client)

    res = client.post("/api/exchange-rates", json={
        "country_code": "CN",
        "rate_to_cny": 1,
    })
    assert res.status_code == 400
