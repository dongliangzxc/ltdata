"""Tests for URL-based matching system"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.models.schemas import Base, ItemUrlMapping, ModelRecord

SQLITE_URL = "sqlite:///:memory:"
engine = create_engine(SQLITE_URL, connect_args={"check_same_thread": False}, poolclass=StaticPool)
Base.metadata.drop_all(bind=engine)
Base.metadata.create_all(bind=engine)
TestSession = sessionmaker(bind=engine)


def test_item_url_mapping_orm():
    """ItemUrlMapping ORM can be created and queried"""
    db = TestSession()
    model = ModelRecord(brand_code="BOSE", model_code="SB850", category_name="SOUNDBAR")
    db.add(model)
    db.flush()

    m = ItemUrlMapping(platform="jd", item_id="100045223280", model_id=model.id, price=1999.0)
    db.add(m)
    db.commit()

    found = db.query(ItemUrlMapping).filter_by(item_id="100045223280").first()
    assert found is not None
    assert found.platform == "jd"
    assert found.model_id == model.id
    assert float(found.price) == 1999.0
    db.close()
