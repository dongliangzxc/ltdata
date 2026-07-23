from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
import pytest

from app.api.upload import router
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

    app = FastAPI()
    app.include_router(router)

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


def test_download_upload_file_returns_original_file(client):
    test_client, session, upload_dir = client
    original = upload_dir / "original-upload.xlsx"
    original.write_bytes(b"uploaded-content")
    record = UploadFileRecord(filename="original-upload.xlsx", status="done", row_count=3)
    session.add(record)
    session.commit()

    response = test_client.get(f"/api/upload/files/{record.id}/download")

    assert response.status_code == 200
    assert response.content == b"uploaded-content"
    assert "attachment" in response.headers["content-disposition"]
    assert "original-upload.xlsx" in response.headers["content-disposition"]


def test_download_upload_file_returns_404_for_missing_record(client):
    test_client, _session, _upload_dir = client

    response = test_client.get("/api/upload/files/999/download")

    assert response.status_code == 404
    assert response.json()["detail"] == "上传记录不存在"


def test_download_upload_file_returns_404_for_missing_file(client):
    test_client, session, _upload_dir = client
    record = UploadFileRecord(filename="missing.xlsx", status="done", row_count=3)
    session.add(record)
    session.commit()

    response = test_client.get(f"/api/upload/files/{record.id}/download")

    assert response.status_code == 404
    assert response.json()["detail"] == "原始上传文件不存在，无法下载"
