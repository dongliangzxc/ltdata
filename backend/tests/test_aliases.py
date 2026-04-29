"""
model_aliases API 测试（SQLite 内存库）
"""
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from app.models.database import Base
from app.models.schemas import ModelRecord, ModelAlias


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
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
