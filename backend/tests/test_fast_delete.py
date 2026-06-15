"""Tests for P11 fast file deletion."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient
from app.main import app
from app.models.database import Base, get_db
from app.models.schemas import CleanJobItemRecord, CleanJobRecord, CleanedDataRecord, FilteredItem, UploadFileRecord, RawDataRecord
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


@pytest.mark.parametrize(
    ("reference_name", "make_reference"),
    [
        (
            "clean_job_items",
            lambda job, raw: CleanJobItemRecord(clean_job_id=job.id, raw_data_id=raw.id, category_code="soundbar", platform="jd"),
        ),
        (
            "cleaned_data",
            lambda job, raw: CleanedDataRecord(clean_job_id=job.id, raw_data_id=raw.id, item_id=raw.item_id),
        ),
        (
            "filtered_items",
            lambda job, raw: FilteredItem(clean_job_id=job.id, raw_data_id=raw.id, matched_keyword="test"),
        ),
    ],
)
def test_delete_rejects_file_with_downstream_raw_data_reference(db, reference_name, make_reference):
    record = UploadFileRecord(filename=f"{reference_name}.xlsx", platform="jd", month_range="202501")
    db.add(record)
    db.flush()
    raw = RawDataRecord(file_id=record.id, platform="jd", item_id="ITEM1", item_name="Title 1", month=202501)
    db.add(raw)
    db.flush()
    job = CleanJobRecord(file_ids=[record.id], rules={"dedup": True}, status="reviewing", row_in=1, row_out=1)
    db.add(job)
    db.flush()
    db.add(make_reference(job, raw))
    db.commit()

    app.dependency_overrides[get_db] = _override_db(db)
    client = TestClient(app, headers=_AUTH_HEADERS)
    resp = client.delete(f"/api/upload/files/{record.id}")
    app.dependency_overrides.clear()

    assert resp.status_code == 400
    assert "已进入分发/清洗任务" in resp.json()["detail"]
    assert db.query(UploadFileRecord).filter_by(id=record.id).count() == 1
    assert db.query(RawDataRecord).filter_by(id=raw.id).count() == 1


def test_delete_nullifies_dispatch_batch_file_id():
    """DELETE /upload/files/{id} sets dispatch_batches.file_id to NULL (preserves dispatch data)."""
    from app.models.schemas import DispatchBatch
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = TestingSessionLocal()

    file_record = UploadFileRecord(filename="f.xlsx", platform="jd", month_range="2024-01", row_count=0, status="done")
    db.add(file_record)
    db.commit()
    db.refresh(file_record)

    batch = DispatchBatch(file_id=file_record.id, status="done")
    db.add(batch)
    db.commit()
    db.refresh(batch)
    batch_id = batch.id

    app.dependency_overrides[get_db] = _override_db(db)
    client2 = TestClient(app, headers=_AUTH_HEADERS)
    resp = client2.delete(f"/api/upload/files/{file_record.id}")
    app.dependency_overrides.clear()
    db.close()

    assert resp.status_code == 200
    db2 = TestingSessionLocal()
    updated_batch = db2.query(DispatchBatch).filter(DispatchBatch.id == batch_id).first()
    db2.close()
    assert updated_batch is not None
    assert updated_batch.file_id is None
