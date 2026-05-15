"""Tests for P11 fast file deletion."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient
from app.main import app
from app.models.database import Base, get_db
from app.models.schemas import UploadFileRecord, RawDataRecord
from app.core.security import create_access_token

_AUTH_HEADERS = {"Authorization": f"Bearer {create_access_token('test')}"}


def _override_db(session):
    def _get():
        yield session
    return _get


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    Base.metadata.drop_all(engine)


def test_delete_file_returns_200(db):
    """DELETE /upload/files/{id} returns 200 and message."""
    record = UploadFileRecord(filename="test.xlsx", platform="jd", month_range="202501")
    db.add(record)
    db.commit()

    app.dependency_overrides[get_db] = _override_db(db)
    client = TestClient(app, headers=_AUTH_HEADERS)
    resp = client.delete(f"/api/upload/files/{record.id}")
    app.dependency_overrides.clear()

    assert resp.status_code == 200
    assert resp.json()["message"] == "已删除"


def test_delete_file_not_found(db):
    """DELETE /upload/files/{id} returns 404 if file does not exist."""
    app.dependency_overrides[get_db] = _override_db(db)
    client = TestClient(app, headers=_AUTH_HEADERS)
    resp = client.delete("/api/upload/files/999")
    app.dependency_overrides.clear()

    assert resp.status_code == 404


def test_delete_executes_batch_sql(db):
    """DELETE endpoint runs a batch SQL delete on raw_data, not ORM per-row."""
    record = UploadFileRecord(filename="batch_test.xlsx", platform="jd", month_range="202501")
    db.add(record)
    db.commit()

    # Add some raw_data rows so there's something to delete
    for i in range(3):
        raw = RawDataRecord(
            file_id=record.id,
            platform="jd",
            item_id=f"ITEM{i}",
            item_name=f"Title {i}",
            month=202501,
        )
        db.add(raw)
    db.commit()

    # Spy on db.execute to verify batch SQL is called
    original_execute = db.execute
    execute_calls = []

    def spy_execute(stmt, *args, **kwargs):
        execute_calls.append(str(stmt))
        return original_execute(stmt, *args, **kwargs)

    db.execute = spy_execute

    app.dependency_overrides[get_db] = _override_db(db)
    client = TestClient(app, headers=_AUTH_HEADERS)
    client.delete(f"/api/upload/files/{record.id}")
    app.dependency_overrides.clear()

    # Verify db.execute was called (batch SQL path)
    assert len(execute_calls) >= 1, "db.execute should have been called at least once"
    batch_calls = [c for c in execute_calls if "raw_data" in c.lower() or "DELETE" in c]
    assert len(batch_calls) >= 1, f"Expected a batch DELETE on raw_data, got calls: {execute_calls}"


def test_delete_removes_raw_data_rows(db):
    """DELETE /upload/files/{id} actually removes associated RawDataRecord rows from DB."""
    record = UploadFileRecord(filename="raw_delete_test.xlsx", platform="jd", month_range="202501")
    db.add(record)
    db.commit()

    for i in range(3):
        raw = RawDataRecord(
            file_id=record.id,
            platform="jd",
            item_id=f"RAW{i}",
            item_name=f"Product {i}",
            month=202501,
        )
        db.add(raw)
    db.commit()

    # Confirm rows exist before deletion
    before = db.query(RawDataRecord).filter(RawDataRecord.file_id == record.id).count()
    assert before == 3

    app.dependency_overrides[get_db] = _override_db(db)
    client = TestClient(app, headers=_AUTH_HEADERS)
    resp = client.delete(f"/api/upload/files/{record.id}")
    app.dependency_overrides.clear()

    assert resp.status_code == 200

    # Verify all RawDataRecord rows linked to this file are gone
    after = db.query(RawDataRecord).filter(RawDataRecord.file_id == record.id).count()
    assert after == 0, f"Expected 0 RawDataRecord rows after delete, found {after}"
