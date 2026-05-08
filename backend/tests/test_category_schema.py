"""验证 Category ORM 和 ModelRecord 字段变更"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.models.database import Base
from app.models.schemas import Category, ModelRecord

@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    S = sessionmaker(bind=engine)
    s = S()
    yield s
    s.close()

def test_category_create_and_query(db):
    cat = Category(code="soundbar", name="回音壁")
    db.add(cat)
    db.commit()
    found = db.query(Category).filter_by(code="soundbar").first()
    assert found is not None
    assert found.name == "回音壁"

def test_model_has_category_code_not_category_name(db):
    cat = Category(code="tv", name="电视")
    db.add(cat)
    db.flush()
    model = ModelRecord(brand_code="SONY", model_code="X90L", category_code="tv")
    db.add(model)
    db.commit()
    m = db.query(ModelRecord).first()
    assert m.category_code == "tv"
    assert not hasattr(m, "category_name")

def test_category_unique_code(db):
    from sqlalchemy.exc import IntegrityError
    db.add(Category(code="dup", name="A"))
    db.commit()
    db.add(Category(code="dup", name="B"))
    with pytest.raises(IntegrityError):
        db.commit()
