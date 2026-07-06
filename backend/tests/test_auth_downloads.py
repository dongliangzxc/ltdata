from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.main as main_module
from app.api import dispatch_api
from app.models import database as database_module
from app.models.schemas import Base, WorkbenchExportJob


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
