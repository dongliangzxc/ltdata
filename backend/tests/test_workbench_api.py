from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker

from app.api.workbench_api import router
from app.core.auth_deps import get_current_user
from app.models.analytics_db import AnalyticsBase, PublishedItem, get_analytics_db
from app.models.database import get_db
from app.models.schemas import Base, Category


class DummyUser:
    def __init__(self, *, is_admin=0, category_permissions=None):
        self.is_admin = is_admin
        self.category_permissions = category_permissions


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

    current_user = {"value": DummyUser(is_admin=1)}

    def override_db():
        yield db

    def override_current_user():
        return current_user["value"]

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_analytics_db] = override_db
    app.dependency_overrides[get_current_user] = override_current_user

    client = TestClient(app)
    client.current_user = current_user
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


def _seed_category_permission_items(db):
    db.add_all([
        Category(code="rice_cooker", name="电饭煲", sort_order=1),
        Category(code="headphone", name="耳机", sort_order=2),
        PublishedItem(
            publish_job_id=1,
            clean_job_id=201,
            match_result_id=201,
            platform="jd",
            month=202606,
            category_name="电饭煲",
            item_id="rice-item",
            item_name="Rice cooker",
            price=199.0,
        ),
        PublishedItem(
            publish_job_id=2,
            clean_job_id=202,
            match_result_id=202,
            platform="jd",
            month=202606,
            category_name="耳机",
            item_id="headphone-item",
            item_name="Headphone",
            price=299.0,
        ),
    ])
    db.commit()


def test_workbench_filters_respect_category_permissions(client_and_db):
    client, db, _monkeypatch = client_and_db
    _seed_category_permission_items(db)
    client.current_user["value"] = DummyUser(category_permissions=["rice_cooker"])

    response = client.get("/api/workbench/filters")

    assert response.status_code == 200
    assert response.json()["categories"] == ["电饭煲"]


def test_workbench_data_respects_category_permissions(client_and_db):
    client, db, monkeypatch = client_and_db
    _seed_category_permission_items(db)
    client.current_user["value"] = DummyUser(category_permissions=["rice_cooker"])
    monkeypatch.setattr("app.api.workbench_api._load_workbench_context", lambda rows: ({}, {}))

    response = client.get("/api/workbench/data")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert [item["item_name"] for item in payload["items"]] == ["Rice cooker"]


def test_workbench_data_rejects_invisible_category_filter(client_and_db):
    client, db, _monkeypatch = client_and_db
    _seed_category_permission_items(db)
    client.current_user["value"] = DummyUser(category_permissions=["rice_cooker"])

    response = client.get("/api/workbench/data?category_name=耳机")

    assert response.status_code == 403
    assert response.json()["detail"] == "无权限访问该品类"


def test_workbench_export_rejects_invisible_category_filter(client_and_db):
    client, db, _monkeypatch = client_and_db
    _seed_category_permission_items(db)
    client.current_user["value"] = DummyUser(category_permissions=["rice_cooker"])

    response = client.post("/api/workbench/export", json={"category_name": "耳机"})

    assert response.status_code == 403
    assert response.json()["detail"] == "无权限访问该品类"


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
