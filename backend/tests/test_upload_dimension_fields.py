"""Tests for data_region/data_year/data_month on upload_files."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.models.database import Base, get_db
from fastapi import FastAPI
from app.api.upload import router
from app.models.schemas import UploadFileRecord


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

    def override_db():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override_db
    return TestClient(app)


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
        s.close()


def test_upload_file_defaults_none_dimensions(db):
    """data_region/data_year/data_month default to NULL."""
    rec = UploadFileRecord(filename="test.xlsx", row_count=0, status="done")
    db.add(rec)
    db.commit()
    db.refresh(rec)
    assert rec.data_region is None
    assert rec.data_year is None
    assert rec.data_month is None


def test_upload_file_stores_dimensions(db):
    """Store and retrieve all three dimension fields."""
    rec = UploadFileRecord(
        filename="test.xlsx", row_count=10, status="done",
        data_region="domestic", data_year=2026, data_month=3,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    assert rec.data_region == "domestic"
    assert rec.data_year == 2026
    assert rec.data_month == 3


def test_list_upload_files_filter_by_region(client):
    """GET /api/upload/files?data_region=domestic returns only matching rows."""
    from app.models.database import get_db as real_get_db
    db_gen = client.app.dependency_overrides[real_get_db]()
    db = next(db_gen)
    db.add(UploadFileRecord(filename="a.xlsx", row_count=1, status="done", data_region="domestic"))
    db.add(UploadFileRecord(filename="b.xlsx", row_count=1, status="done", data_region="overseas"))
    db.commit()
    try:
        next(db_gen)
    except StopIteration:
        pass

    r = client.get("/api/upload/files?data_region=domestic")
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 1
    assert items[0]["filename"] == "a.xlsx"
    assert items[0]["data_region"] == "domestic"


def test_list_upload_files_filter_by_year_month(client):
    """GET /api/upload/files?data_year=2026&data_month=3 returns matching rows."""
    from app.models.database import get_db as real_get_db
    db_gen = client.app.dependency_overrides[real_get_db]()
    db = next(db_gen)
    db.add(UploadFileRecord(filename="c.xlsx", row_count=1, status="done", data_year=2026, data_month=3))
    db.add(UploadFileRecord(filename="d.xlsx", row_count=1, status="done", data_year=2026, data_month=4))
    db.commit()
    try:
        next(db_gen)
    except StopIteration:
        pass

    r = client.get("/api/upload/files?data_year=2026&data_month=3")
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 1
    assert items[0]["filename"] == "c.xlsx"
