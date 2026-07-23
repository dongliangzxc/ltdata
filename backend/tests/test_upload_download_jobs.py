import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import upload as upload_api
from app.core.config import settings
from app.models.database import Base, get_db
from app.models.schemas import UploadFileRecord


@pytest.fixture()
def client(tmp_path, monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(upload_dir))
    monkeypatch.setattr(upload_api, "SessionLocal", Session)

    app = FastAPI()
    app.include_router(upload_api.router)

    def override_db():
        try:
            yield session
        finally:
            pass

    app.dependency_overrides[get_db] = override_db

    try:
        yield TestClient(app), session, upload_dir
    finally:
        session.close()
        Base.metadata.drop_all(engine)
        app.dependency_overrides.clear()


def wait_for_terminal_job(test_client: TestClient, job_id: int) -> dict:
    for _ in range(20):
        response = test_client.get(f"/api/upload/download-jobs/{job_id}")
        assert response.status_code == 200
        job = response.json()
        if job["status"] in {"done", "error"}:
            return job
        time.sleep(0.05)
    raise AssertionError("download job did not finish")


def test_create_download_job_prepares_original_file_and_downloads_it(client):
    test_client, session, upload_dir = client
    original = upload_dir / "slow-original.xlsx"
    original.write_bytes(b"prepared-by-background-job")
    record = UploadFileRecord(filename="slow-original.xlsx", status="done", row_count=3)
    session.add(record)
    session.commit()

    created = test_client.post(f"/api/upload/files/{record.id}/download-jobs")

    assert created.status_code == 200
    created_job = created.json()
    assert created_job["file_id"] == record.id
    assert created_job["status"] in {"pending", "running", "done"}
    job = wait_for_terminal_job(test_client, created_job["job_id"])
    assert job["status"] == "done"
    assert job["progress"] == 100
    assert job["filename"] == "slow-original.xlsx"
    assert job["download_url"] == f"/api/upload/download-jobs/{job['job_id']}/download"

    listed = test_client.get("/api/upload/download-jobs", params={"file_ids": str(record.id)})
    assert listed.status_code == 200
    assert listed.json()[0]["job_id"] == job["job_id"]

    downloaded = test_client.get(job["download_url"])
    assert downloaded.status_code == 200
    assert downloaded.content == b"prepared-by-background-job"
    assert "slow-original.xlsx" in downloaded.headers["content-disposition"]


def test_create_download_job_returns_404_for_missing_upload_record(client):
    test_client, _session, _upload_dir = client

    response = test_client.post("/api/upload/files/999/download-jobs")

    assert response.status_code == 404
    assert response.json()["detail"] == "上传记录不存在"


def test_download_job_reports_error_when_original_file_is_missing(client):
    test_client, session, _upload_dir = client
    record = UploadFileRecord(filename="missing.xlsx", status="done", row_count=3)
    session.add(record)
    session.commit()

    created = test_client.post(f"/api/upload/files/{record.id}/download-jobs")

    assert created.status_code == 200
    job = wait_for_terminal_job(test_client, created.json()["job_id"])
    assert job["status"] == "error"
    assert job["progress"] == 100
    assert job["error_msg"] == "原始上传文件不存在，无法下载"
    assert job["download_url"] is None


def test_download_job_rejects_download_before_done(client):
    test_client, session, _upload_dir = client
    record = UploadFileRecord(filename="missing.xlsx", status="done", row_count=3)
    session.add(record)
    session.commit()
    created = test_client.post(f"/api/upload/files/{record.id}/download-jobs")
    job_id = created.json()["job_id"]
    wait_for_terminal_job(test_client, job_id)

    response = test_client.get(f"/api/upload/download-jobs/{job_id}/download")

    assert response.status_code == 409
    assert response.json()["detail"] == "下载任务尚未完成"
