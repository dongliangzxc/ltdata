"""Tests for category hierarchy: parent_code and sort_order fields."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.models.database import Base
from app.models.schemas import Category, CategoryOut
from fastapi.testclient import TestClient
from fastapi import FastAPI
from app.models.database import get_db
from app.api.categories_api import router as cat_router


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    try:
        yield s
    finally:
        s.rollback()
        s.close()


def test_category_new_fields_default(db):
    """parent_code defaults to NULL, sort_order defaults to 0."""
    c = Category(code="test", name="测试")
    db.add(c)
    db.commit()
    db.refresh(c)
    assert c.parent_code is None
    assert c.sort_order == 0


def test_category_stores_parent_and_sort_order(db):
    """parent_code and sort_order are stored and retrieved."""
    parent = Category(code="audio", name="音频", sort_order=0)
    db.add(parent)
    db.commit()
    child = Category(code="headphones", name="耳机", parent_code="audio", sort_order=2)
    db.add(child)
    db.commit()
    db.refresh(child)
    assert child.parent_code == "audio"
    assert child.sort_order == 2


def test_category_out_pydantic_roundtrip(db):
    """CategoryOut.model_validate works with new fields."""
    c = Category(code="tv", name="电视", parent_code="display", sort_order=5)
    db.add(c)
    db.commit()
    db.refresh(c)
    out = CategoryOut.model_validate(c)
    assert out.parent_code == "display"
    assert out.sort_order == 5


# ─────────────────────────── API Tests (TestClient) ───────────────────────────

@pytest.fixture(scope="function")
def client_and_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    app = FastAPI()
    app.include_router(cat_router)
    def override_db():
        yield db
    app.dependency_overrides[get_db] = override_db
    yield TestClient(app), db
    db.close()


def test_tree_returns_nested_children(client_and_db):
    """GET /api/categories/tree returns parent nodes with children nested."""
    client, db = client_and_db
    db.add(Category(code="audio", name="音频", sort_order=0))
    db.add(Category(code="headphones", name="耳机", parent_code="audio", sort_order=0))
    db.add(Category(code="speakers",   name="音箱", parent_code="audio", sort_order=1))
    db.commit()
    r = client.get("/api/categories/tree")
    assert r.status_code == 200
    tree = r.json()
    assert len(tree) == 1
    assert tree[0]["code"] == "audio"
    codes = {c["code"] for c in tree[0]["children"]}
    assert codes == {"headphones", "speakers"}


def test_tree_root_nodes_only_at_top(client_and_db):
    """Nodes with no parent appear only at top level."""
    client, db = client_and_db
    db.add(Category(code="video", name="视频", sort_order=0))
    db.add(Category(code="audio", name="音频", sort_order=1))
    db.commit()
    r = client.get("/api/categories/tree")
    tree = r.json()
    assert len(tree) == 2
    for node in tree:
        assert node["children"] == []


def test_flat_list_includes_parent_code(client_and_db):
    """GET /api/categories returns parent_code and sort_order on each item."""
    client, db = client_and_db
    db.add(Category(code="audio", name="音频"))
    db.add(Category(code="headphones", name="耳机", parent_code="audio", sort_order=3))
    db.commit()
    r = client.get("/api/categories")
    items = r.json()
    hp = next(i for i in items if i["code"] == "headphones")
    assert hp["parent_code"] == "audio"
    assert hp["sort_order"] == 3


def test_create_category_with_parent_code(client_and_db):
    """POST /api/categories accepts and stores parent_code."""
    client, db = client_and_db
    db.add(Category(code="audio", name="音频"))
    db.commit()
    r = client.post("/api/categories", json={"code": "headphones", "name": "耳机", "parent_code": "audio", "sort_order": 1})
    assert r.status_code == 201
    body = r.json()
    assert body["parent_code"] == "audio"
    assert body["sort_order"] == 1


def test_update_category_parent_and_sort(client_and_db):
    """PUT /api/categories/{id} accepts parent_code and sort_order."""
    client, db = client_and_db
    cat = Category(code="headphones", name="耳机")
    db.add(cat)
    db.add(Category(code="audio", name="音频"))
    db.commit()
    r = client.put(f"/api/categories/{cat.id}", json={"parent_code": "audio", "sort_order": 5})
    assert r.status_code == 200
    assert r.json()["parent_code"] == "audio"
    assert r.json()["sort_order"] == 5


def test_update_category_clears_parent_code(client_and_db):
    """PUT /categories/{id} with parent_code: null clears the parent (promotes to root)."""
    client, db = client_and_db
    cat = Category(code="headphones", name="耳机", parent_code="audio")
    db.add(cat)
    db.commit()
    r = client.put(f"/api/categories/{cat.id}", json={"parent_code": None})
    assert r.status_code == 200
    assert r.json()["parent_code"] is None


def test_update_category_rejects_indirect_cycle(client_and_db):
    """PUT /categories/{id} rejects a parent assignment that would create an indirect cycle."""
    client, db = client_and_db
    # chain: C -> B -> A (C is child of B, B is child of A)
    db.add(Category(code="A", name="A"))
    db.add(Category(code="B", name="B", parent_code="A"))
    db.add(Category(code="C", name="C", parent_code="B"))
    db.commit()
    # Try to set A's parent to C — would create A -> C -> B -> A
    a = db.query(Category).filter(Category.code == "A").first()
    r = client.put(f"/api/categories/{a.id}", json={"parent_code": "C"})
    assert r.status_code == 422


def test_delete_category_blocked_by_children(client_and_db):
    """DELETE /categories/{id} returns 409 when the category has children."""
    client, db = client_and_db
    parent = Category(code="audio", name="音频")
    child = Category(code="headphones", name="耳机", parent_code="audio")
    db.add(parent)
    db.add(child)
    db.commit()
    r = client.delete(f"/api/categories/{parent.id}")
    assert r.status_code == 409


def test_create_category_rejects_nonexistent_parent(client_and_db):
    """POST /categories returns 404 when parent_code does not exist."""
    client, db = client_and_db
    r = client.post("/api/categories", json={"code": "headphones", "name": "耳机", "parent_code": "nonexistent"})
    assert r.status_code == 404
