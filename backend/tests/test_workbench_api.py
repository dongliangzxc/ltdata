from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker

from app.api.workbench_api import router
from app.models.analytics_db import AnalyticsBase, PublishedItem, get_analytics_db
from app.models.database import get_db
from app.models.schemas import Base


@pytest.fixture(scope="function")
def client_and_db(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    AnalyticsBase.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    app = FastAPI()
    app.include_router(router)

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_analytics_db] = override_db

    client = TestClient(app)
    yield client, db, monkeypatch

    client.close()
    db.close()
    Base.metadata.drop_all(engine)
    AnalyticsBase.metadata.drop_all(engine)


def _seed_published(db):
    db.add_all([
        PublishedItem(
            publish_job_id=1,
            clean_job_id=101,
            match_result_id=1,
            platform="jd",
            month=202605,
            category_lv1="家电",
            category_lv2="厨房电器",
            category_name="电饭煲",
            item_id="item-1",
            item_name="Alpha rice cooker",
            item_image="https://example.com/1.jpg",
            item_url="https://example.com/item-1",
            ref_price=199.0,
            shop_name="Alpha Store",
            sales_qty=10,
            sales_amount=1990.0,
            price=199.0,
            brand_code="BRAND-A",
            brand_name="Brand A",
            model_code="MODEL-A",
            model_name="Model A",
            category_lv0="家电",
            calc_price=199.0,
            corrected_sales_qty=10,
            corrected_sales_amount=1990.0,
            published_at=datetime(2026, 5, 1, 12, 0, 0),
        ),
        PublishedItem(
            publish_job_id=2,
            clean_job_id=102,
            match_result_id=2,
            platform="jd",
            month=202605,
            category_lv1="家电",
            category_lv2="厨房电器",
            category_name="电饭煲",
            item_id="item-2",
            item_name="Beta rice cooker",
            item_image="https://example.com/2.jpg",
            item_url="https://example.com/item-2",
            ref_price=299.0,
            shop_name="Beta Store",
            sales_qty=20,
            sales_amount=5980.0,
            price=299.0,
            brand_code="BRAND-A",
            brand_name="Brand A",
            model_code="MODEL-A",
            model_name="Model A",
            category_lv0="家电",
            calc_price=299.0,
            corrected_sales_qty=20,
            corrected_sales_amount=5980.0,
            published_at=datetime(2026, 5, 1, 12, 0, 0),
        ),
    ])
    db.commit()


def test_query_data_filters_by_clean_job_id(client_and_db):
    client, db, monkeypatch = client_and_db
    _seed_published(db)
    monkeypatch.setattr(
        "app.api.workbench_api._load_workbench_context",
        lambda rows: ({}, {}),
    )

    response = client.get("/api/workbench/data?clean_job_id=101")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == 1


def test_export_passes_clean_job_id_to_background_thread(client_and_db):
    client, db, monkeypatch = client_and_db
    captured = {}

    class FakeThread:
        def __init__(self, target, args, daemon):
            captured["target"] = target
            captured["args"] = args
            captured["daemon"] = daemon

        def start(self):
            captured["started"] = True

    monkeypatch.setattr("app.api.workbench_api.threading.Thread", FakeThread)

    response = client.post(
        "/api/workbench/export",
        json={
            "clean_job_id": 101,
            "platform": "jd",
        },
    )

    assert response.status_code == 202, response.text
    assert captured["started"] is True
    assert captured["args"][1]["clean_job_id"] == 101
