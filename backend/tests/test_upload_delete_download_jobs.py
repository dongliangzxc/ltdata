"""Upload deletion with real FK enforcement, including download-job children."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.api import upload as upload_api
from app.models.database import Base, get_db
from app.models.schemas import (
    CleanJobItemRecord, CleanJobRecord, DispatchBatch, RawDataRecord,
    UploadDownloadJob, UploadFileRecord,
)


@pytest.fixture
def env(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'delete.db'}")

    @event.listens_for(engine, "connect")
    def enforce_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    monkeypatch.setattr(upload_api, "SessionLocal", Session)
    app = FastAPI()
    app.include_router(upload_api.router)

    def get_session():
        with Session() as db:
            yield db

    app.dependency_overrides[get_db] = get_session
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, Session, engine
    engine.dispose()


def seed(Session, statuses=("done",), batch_key="batch-delete"):
    with Session() as db:
        record = UploadFileRecord(filename="weekly.xlsx", batch_key=batch_key)
        db.add(record)
        db.flush()
        db.add(RawDataRecord(file_id=record.id, item_id=f"item-{record.id}", month=209901))
        db.add(DispatchBatch(file_id=record.id, status="done"))
        for status in statuses:
            db.add(UploadDownloadJob(file_id=record.id, filename=record.filename, status=status))
        db.commit()
        return record.id


def endpoint(route, file_id):
    return f"/api/upload/files/{file_id}" if route == "file" else "/api/upload/batches/batch-delete"


def test_fixture_enforces_download_job_foreign_key(env):
    _client, Session, _engine = env
    file_id = seed(Session)
    with Session() as db, pytest.raises(IntegrityError):
        db.execute(text("DELETE FROM upload_files WHERE id=:id"), {"id": file_id})


@pytest.mark.parametrize("route", ["file", "batch"])
@pytest.mark.parametrize("status", ["pending", "running", "done", "error"])
def test_delete_cleans_download_jobs_and_preserves_other_files(env, route, status):
    client, Session, _engine = env
    file_id = seed(Session, (status, status))
    other_id = seed(Session, batch_key="other-batch")
    if route == "batch":
        second_id = seed(Session, ("done", "error"))
    else:
        second_id = None

    response = client.delete(endpoint(route, file_id))

    assert response.status_code == 200, response.text
    if route == "batch":
        assert response.json()["deleted_files"] == 2
    removed_ids = [file_id] + ([second_id] if second_id else [])
    with Session() as db:
        assert db.query(UploadFileRecord).filter(UploadFileRecord.id.in_(removed_ids)).count() == 0
        assert db.query(UploadDownloadJob).filter(UploadDownloadJob.file_id.in_(removed_ids)).count() == 0
        assert db.query(RawDataRecord).filter(RawDataRecord.file_id.in_(removed_ids)).count() == 0
        assert db.query(DispatchBatch).filter(DispatchBatch.file_id.is_(None)).count() == len(removed_ids)
        assert db.get(UploadFileRecord, other_id) is not None
        assert db.query(UploadDownloadJob).filter_by(file_id=other_id).count() == 1
        assert db.query(RawDataRecord).filter_by(file_id=other_id).count() == 1
    assert client.delete(endpoint(route, file_id)).status_code == 404


@pytest.mark.parametrize("route", ["file", "batch"])
def test_downstream_guard_preserves_download_jobs_too(env, route):
    client, Session, _engine = env
    file_id = seed(Session)
    if route == "batch":
        seed(Session)
    with Session() as db:
        raw = db.query(RawDataRecord).filter_by(file_id=file_id).one()
        job = CleanJobRecord(file_ids=[file_id])
        db.add(job)
        db.flush()
        db.add(CleanJobItemRecord(clean_job_id=job.id, raw_data_id=raw.id, category_code="test"))
        db.commit()

    response = client.delete(endpoint(route, file_id))

    assert response.status_code == 400
    assert "已进入分发/清洗任务" in response.json()["detail"]
    with Session() as db:
        expected = 2 if route == "batch" else 1
        assert db.query(UploadFileRecord).count() == expected
        assert db.query(UploadDownloadJob).count() == expected
        assert db.query(RawDataRecord).count() == expected


@pytest.mark.parametrize("route", ["file", "batch"])
def test_failed_parent_delete_rolls_back_all_children(env, route):
    client, Session, engine = env
    file_id = seed(Session)
    # Simulate another restrictive reference discovered only at the final DELETE.
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE extra_reference (file_id INTEGER REFERENCES upload_files(id))"))
        connection.execute(text("INSERT INTO extra_reference VALUES (:id)"), {"id": file_id})

    assert client.delete(endpoint(route, file_id)).status_code == 500

    with Session() as db:
        assert db.get(UploadFileRecord, file_id) is not None
        assert db.query(UploadDownloadJob).filter_by(file_id=file_id).count() == 1
        assert db.query(RawDataRecord).filter_by(file_id=file_id).count() == 1
        assert db.query(DispatchBatch).filter_by(file_id=file_id).count() == 1


def test_download_worker_ignores_job_removed_by_file_deletion(env):
    client, Session, _engine = env
    file_id = seed(Session, ("pending",))
    with Session() as db:
        job_id = db.query(UploadDownloadJob).filter_by(file_id=file_id).one().id
    assert client.delete(endpoint("file", file_id)).status_code == 200

    upload_api._run_upload_download_job(job_id)

    with Session() as db:
        assert db.query(UploadDownloadJob).count() == 0
