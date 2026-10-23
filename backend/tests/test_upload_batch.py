"""Batch download/delete APIs for grouped upload history."""
import io
import zipfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.upload import router
from app.core.config import settings
from app.models.database import Base, get_db
from app.models.schemas import UploadFileRecord


@pytest.fixture
def client(tmp_path, monkeypatch):
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
        session = Session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_db
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    test_client = TestClient(app)
    test_client.Session = Session
    test_client.tmp_path = tmp_path
    return test_client


def _seed_batch(client, key="batch-001"):
    with client.Session() as session:
        for index in (1, 2):
            filename = f"file-{index}.xlsx"
            (client.tmp_path / filename).write_bytes(f"content-{index}".encode())
            session.add(UploadFileRecord(
                filename=filename, platform="amazon", row_count=1,
                status="done", batch_key=key,
            ))
        session.commit()


def test_download_batch_returns_zip(client):
    _seed_batch(client)

    res = client.get("/api/upload/batches/batch-001/download")

    assert res.status_code == 200
    assert res.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(res.content)) as archive:
        assert sorted(archive.namelist()) == ["file-1.xlsx", "file-2.xlsx"]


def test_delete_batch_removes_all_files(client):
    _seed_batch(client)

    res = client.delete("/api/upload/batches/batch-001")

    assert res.status_code == 200
    assert res.json()["deleted_files"] == 2
    with client.Session() as session:
        assert session.query(UploadFileRecord).filter(UploadFileRecord.batch_key == "batch-001").count() == 0


def test_unknown_batch_returns_404(client):
    assert client.get("/api/upload/batches/missing/download").status_code == 404
    assert client.delete("/api/upload/batches/missing").status_code == 404
