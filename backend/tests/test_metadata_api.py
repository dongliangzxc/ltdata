"""metadata API category permission tests."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.metadata import router
from app.core.auth_deps import get_current_user
from app.models.database import Base, get_db
from app.models.schemas import Category, MetadataSpec


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


def seed_categories(session):
    session.add_all([
        Category(code="TV", name="电视", sort_order=1),
        Category(code="AC", name="空调", sort_order=2),
    ])


def seed_metadata(session):
    session.add_all([
        MetadataSpec(category_code="TV", spec_name="尺寸", spec_type="文本型", required=0, single_select=1),
        MetadataSpec(category_code="AC", spec_name="匹数", spec_type="文本型", required=0, single_select=1),
    ])


def test_list_metadata_only_returns_visible_categories(client):
    with client.Session() as session:
        seed_categories(session)
        seed_metadata(session)
        session.commit()

    res = client.get("/api/metadata")

    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 1
    assert [item["category_code"] for item in data["items"]] == ["TV"]


def test_create_metadata_rejects_invisible_category(client):
    with client.Session() as session:
        seed_categories(session)
        session.commit()

    res = client.post("/api/metadata", json={
        "category_code": "AC",
        "spec_name": "匹数",
        "spec_type": "文本型",
        "spec_values": None,
        "required": False,
        "decimal_places": None,
        "single_select": True,
    })

    assert res.status_code == 403
    assert res.json()["detail"] == "无权限访问该品类"


def test_empty_category_permissions_can_see_all_metadata(client):
    client.current_user.category_permissions = []
    with client.Session() as session:
        seed_categories(session)
        seed_metadata(session)
        session.commit()

    res = client.get("/api/metadata")

    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 2
    assert {item["category_code"] for item in data["items"]} == {"TV", "AC"}
