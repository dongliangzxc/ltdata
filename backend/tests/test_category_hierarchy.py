"""Tests for category hierarchy: parent_code and sort_order fields."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.models.database import Base
from app.models.schemas import Category, CategoryOut


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
