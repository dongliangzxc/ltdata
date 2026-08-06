"""URL mapping API category permission tests."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.url_mapping_api import router
from app.core.auth_deps import get_current_user
from app.models.database import Base, get_db
from app.models.schemas import Category, ItemUrlMapping, ModelRecord


class DummyUser:
    def __init__(self, *, is_admin=0, category_permissions=None):
        self.is_admin = is_admin
        self.category_permissions = category_permissions


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

    current_user = DummyUser(is_admin=0, category_permissions=["TV"])

    def override_db():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    def override_current_user():
        return current_user

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_current_user
    test_client = TestClient(app)
    test_client.Session = Session
    test_client.current_user = current_user
    return test_client


def seed_data(session):
    tv = ModelRecord(brand_code="SONY", model_code="TV-1", category_code="TV", brand_name="索尼", model_name="电视一")
    ac = ModelRecord(brand_code="GREE", model_code="AC-1", category_code="AC", brand_name="格力", model_name="空调一")
    session.add_all([
        Category(code="TV", name="电视", sort_order=1),
        Category(code="AC", name="空调", sort_order=2),
        tv,
        ac,
    ])
    session.flush()
    session.add_all([
        ItemUrlMapping(platform="jd", item_id="tv-item", item_url="https://item.jd.com/tv-item.html", model_id=tv.id, brand_code="SONY", price=1000),
        ItemUrlMapping(platform="jd", item_id="ac-item", item_url="https://item.jd.com/ac-item.html", model_id=ac.id, brand_code="GREE", price=2000),
    ])
    return tv, ac


def test_list_url_mappings_only_returns_visible_model_categories(client):
    with client.Session() as session:
        seed_data(session)
        session.commit()

    res = client.get("/api/url-mappings")

    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 1
    assert [item["item_id"] for item in data["items"]] == ["tv-item"]
    assert data["items"][0]["category_code"] == "TV"


def test_create_url_mapping_rejects_invisible_model_category(client):
    with client.Session() as session:
        _, ac = seed_data(session)
        session.commit()
        ac_id = ac.id

    res = client.post("/api/url-mappings", json={
        "platform": "tmall",
        "item_id": "new-ac-item",
        "item_url": "https://detail.tmall.com/item.htm?id=new-ac-item",
        "model_id": ac_id,
        "price": 3000,
    })

    assert res.status_code == 403
    assert res.json()["detail"] == "无权限访问该品类"


def test_list_url_mappings_hides_legacy_headphone_rows_outside_scope(client):
    with client.Session() as session:
        session.add_all([
            Category(code="TV", name="电视", sort_order=1),
            Category(code="headphone", name="耳机", sort_order=2),
            ItemUrlMapping(
                platform="jd",
                item_id="legacy-headphone",
                item_url="https://item.jd.com/legacy-headphone.html",
                model_id=None,
                brand_code="SONY",
                source=None,
                price=99,
            ),
        ])
        session.commit()

    res = client.get("/api/url-mappings")

    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 0
    assert data["items"] == []
