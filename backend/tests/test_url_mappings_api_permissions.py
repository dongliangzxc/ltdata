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


def _upload_and_confirm(client, *, category_code, brand_code, model_code, platform="jd", item_url=None):
    import io as _io
    import tempfile
    from openpyxl import Workbook
    from pathlib import Path

    wb = Workbook()
    ws = wb.active
    ws.append(["platform", "item_url", "brand_code", "model_code"])
    ws.append([platform, item_url or f"https://item.jd.com/{brand_code}-{model_code}.html", brand_code, model_code])
    buf = _io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        tmp.write(buf.getvalue())
        tmp_path = tmp.name

    try:
        headers = client.post(
            "/api/url-mappings/headers",
            files={"file": ("test.xlsx", open(tmp_path, "rb"), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
        assert headers.status_code == 200, headers.text
        temp_file_id = headers.json()["temp_file_id"]
        return client.post("/api/url-mappings/confirm", json={
            "temp_file_id": temp_file_id,
            "mapping": {"platform": "platform", "item_url": "item_url", "brand_code": "brand_code", "model_code": "model_code"},
            "ignore_columns": [],
            "category_code": category_code,
        })
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def test_confirm_checks_selected_category_permission_not_model_category(client):
    """型号归属品类在用户可见范围外时，只要导入所选品类可见即可通过（按所选品类校验）。"""
    with client.Session() as session:
        _, ac = seed_data(session)  # ac 归属 AC 品类，当前用户不可见
        session.commit()

    res = _upload_and_confirm(client, category_code="TV", brand_code="GREE", model_code="AC-1")

    assert res.status_code == 200
    assert res.json()["inserted"] == 1


def test_confirm_blocks_when_selected_category_not_visible(client):
    """导入所选品类本身不可见时仍应 403。"""
    with client.Session() as session:
        _, ac = seed_data(session)
        session.commit()

    res = _upload_and_confirm(client, category_code="AC", brand_code="GREE", model_code="AC-1")

    assert res.status_code == 403
    assert res.json()["detail"] == "无权限访问该品类"


def test_confirm_allows_placeholder_model_dash(client):
    """型号为 -（匹配不到型号）时允许占位导入，model_id 留空、保留品牌、记录所选品类。"""
    with client.Session() as session:
        seed_data(session)
        session.commit()

    res = _upload_and_confirm(client, category_code="TV", brand_code="360", model_code="-")

    assert res.status_code == 200
    data = res.json()
    assert data["inserted"] == 1
    assert not data["errors"]

    with client.Session() as session:
        row = session.query(ItemUrlMapping).filter_by(item_id="360--", platform="jd").first()
        assert row is not None
        assert row.brand_code == "360"
        assert row.model_id is None
        assert row.category_code == "TV"


def test_list_url_mappings_shows_placeholder_category_from_record(client):
    """占位导入的记录按自身 category_code 展示品类，不受型号归属影响。"""
    with client.Session() as session:
        seed_data(session)
        placeholder = ItemUrlMapping(
            platform="jd", item_id="360--", item_url="https://item.jd.com/360--.html",
            brand_code="360", model_id=None, category_code="TV",
        )
        session.add(placeholder)
        session.commit()

    res = client.get("/api/url-mappings")

    assert res.status_code == 200
    items = res.json()["items"]
    row = next(item for item in items if item["item_id"] == "360--")
    assert row["category_code"] == "TV"
