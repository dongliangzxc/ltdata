from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.main as main_module
from app.api import dispatch_api
from app.core.config import settings
from app.models import database as database_module
from app.models.schemas import Base, UploadDownloadJob, UploadFileRecord, WorkbenchExportJob


def test_dispatch_export_download_skips_auth_like_other_downloads(monkeypatch, tmp_path):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    monkeypatch.setattr(main_module, "SessionLocal", Session)
    monkeypatch.setattr(database_module, "SessionLocal", Session)
    monkeypatch.setattr(dispatch_api, "DISPATCH_EXPORT_DIR", tmp_path)

    db = Session()
    try:
        job = WorkbenchExportJob(
            status="done",
            progress=100,
            file_token="dispatch-token",
            filename="分发结果.xlsx",
        )
        db.add(job)
        db.commit()
        (tmp_path / "dispatch-token_分发结果.xlsx").write_bytes(b"xlsx")

        response = TestClient(main_module.app).get("/api/dispatch/export/download/dispatch-token")

        assert response.status_code == 200
    finally:
        db.close()
        Base.metadata.drop_all(engine)


def test_upload_download_job_file_download_skips_auth(monkeypatch, tmp_path):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    monkeypatch.setattr(main_module, "SessionLocal", Session)
    monkeypatch.setattr(database_module, "SessionLocal", Session)
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))

    db = Session()
    try:
        upload = UploadFileRecord(filename="original.xlsx", status="done", row_count=1)
        db.add(upload)
        db.flush()
        job = UploadDownloadJob(
            file_id=upload.id,
            status="done",
            progress=100,
            filename="original.xlsx",
            download_token="upload-token",
        )
        db.add(job)
        db.commit()
        (tmp_path / "original.xlsx").write_bytes(b"xlsx")

        response = TestClient(main_module.app).get(f"/api/upload/download-jobs/{job.id}/download")

        assert response.status_code == 200
    finally:
        db.close()
        Base.metadata.drop_all(engine)
