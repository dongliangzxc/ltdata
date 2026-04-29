"""
model_aliases API 测试（SQLite 内存库）
"""
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.models.database import Base
from app.models.schemas import ModelRecord, ModelAlias


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def set_pragma(conn, _):
        conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def test_model_alias_orm_exists(db):
    """ModelAlias ORM 可以写入和查询。"""
    m = ModelRecord(brand_code="SONY", model_code="HT-A7000",
                    brand_name="索尼", category_name="SOUNDBAR")
    db.add(m)
    db.flush()

    alias = ModelAlias(model_id=m.id, alias_code="HTA7000")
    db.add(alias)
    db.commit()

    result = db.query(ModelAlias).filter(ModelAlias.model_id == m.id).all()
    assert len(result) == 1
    assert result[0].alias_code == "HTA7000"


from fastapi.testclient import TestClient
from app.main import app
from app.models.database import get_db
from app.core.security import create_access_token

_AUTH_HEADERS = {"Authorization": f"Bearer {create_access_token('test')}"}


def _override_db(session):
    def _get():
        yield session
    return _get


def test_add_and_list_aliases(db):
    """POST /api/models/{id}/aliases 新增别名，GET 返回列表。"""
    app.dependency_overrides[get_db] = _override_db(db)
    client = TestClient(app, headers=_AUTH_HEADERS)

    m = ModelRecord(brand_code="SONY", model_code="HT-X9000F",
                    brand_name="索尼", category_name="SOUNDBAR")
    db.add(m)
    db.commit()

    res = client.post(f"/api/models/{m.id}/aliases", json={"alias_code": "HTX9000F"})
    assert res.status_code == 200
    data = res.json()
    assert data["alias_code"] == "HTX9000F"
    assert "id" in data

    res2 = client.get(f"/api/models/{m.id}/aliases")
    assert res2.status_code == 200
    items = res2.json()
    assert len(items) == 1
    assert items[0]["alias_code"] == "HTX9000F"

    app.dependency_overrides.clear()


def test_delete_alias(db):
    """DELETE /api/models/{id}/aliases/{alias_id} 删除别名。"""
    app.dependency_overrides[get_db] = _override_db(db)
    client = TestClient(app, headers=_AUTH_HEADERS)

    m = ModelRecord(brand_code="SONY", model_code="HT-S400",
                    brand_name="索尼", category_name="SOUNDBAR")
    db.add(m)
    db.flush()
    alias = ModelAlias(model_id=m.id, alias_code="HTS400")
    db.add(alias)
    db.commit()

    res = client.delete(f"/api/models/{m.id}/aliases/{alias.id}")
    assert res.status_code == 200

    remaining = db.query(ModelAlias).filter(ModelAlias.model_id == m.id).all()
    assert len(remaining) == 0

    app.dependency_overrides.clear()
