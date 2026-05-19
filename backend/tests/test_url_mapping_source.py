"""Tests for source/data_year/data_month on item_url_mappings."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.models.database import Base
from app.models.schemas import ItemUrlMapping


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


def test_url_mapping_source_defaults_none(db):
    """source/data_year/data_month default to NULL."""
    m = ItemUrlMapping(platform="jd", item_id="12345", brand_code="SONY")
    db.add(m)
    db.commit()
    db.refresh(m)
    assert m.source is None
    assert m.data_year is None
    assert m.data_month is None


def test_url_mapping_stores_source_and_dims(db):
    """source, data_year, data_month are stored and retrieved."""
    m = ItemUrlMapping(
        platform="jd", item_id="99999", brand_code="JBL",
        source="url_import", data_year=2026, data_month=5,
    )
    db.add(m)
    db.commit()
    db.refresh(m)
    assert m.source == "url_import"
    assert m.data_year == 2026
    assert m.data_month == 5
