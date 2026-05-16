"""Tests for WorkbenchExportJob and UploadConfirmJob ORM models."""
from app.models.schemas import WorkbenchExportJob, UploadConfirmJob


def test_workbench_export_job_defaults(db):
    job = WorkbenchExportJob()
    db.add(job)
    db.flush()
    assert job.id is not None
    assert job.status == "pending"
    assert job.progress == 0
    assert job.file_token is None
    assert job.filename is None


def test_upload_confirm_job_defaults(db):
    job = UploadConfirmJob(file_id=42)
    db.add(job)
    db.flush()
    assert job.id is not None
    assert job.status == "pending"
    assert job.progress == 0
    assert job.result_data is None


def test_workbench_export_job_done(db):
    job = WorkbenchExportJob(
        status="done",
        progress=100,
        file_token="abc123",
        filename="分析数据_20260516_100条.xlsx",
    )
    db.add(job)
    db.flush()
    fetched = db.query(WorkbenchExportJob).filter_by(id=job.id).first()
    assert fetched.status == "done"
    assert fetched.file_token == "abc123"


def test_upload_confirm_job_with_result(db):
    job = UploadConfirmJob(
        file_id=1,
        status="done",
        progress=100,
        result_data={"file_id": 1, "row_count": 500, "inserted": 450, "skipped": 50},
    )
    db.add(job)
    db.flush()
    fetched = db.query(UploadConfirmJob).filter_by(id=job.id).first()
    assert fetched.result_data["row_count"] == 500


# ── workbench export API ────────────────────────────────────────
import threading
from contextlib import asynccontextmanager
from fastapi.testclient import TestClient


@asynccontextmanager
async def _noop_lifespan(application):
    yield


def _patch_app(db, monkeypatch):
    """Apply test-time patches: DB overrides, auth bypass, lifespan stub."""
    from app.main import app
    from app.models.database import get_db
    from app.models.analytics_db import get_analytics_db

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_analytics_db] = override_db

    # Bypass JWT auth middleware
    monkeypatch.setattr("app.core.security.verify_token", lambda token: "test_user")
    monkeypatch.setattr("app.main.verify_token", lambda token: "test_user")

    # Stub out lifespan so TestClient doesn't connect to MySQL
    monkeypatch.setattr(app.router, "lifespan_context", _noop_lifespan)

    return app


def test_wb_export_returns_job_id(db, monkeypatch):
    """POST /workbench/export 应立即返回 job_id，不阻塞。"""
    # Prevent the background thread from actually running (which would connect to MySQL)
    monkeypatch.setattr(
        "app.api.workbench_api._run_wb_export_thread",
        lambda job_id, params: None,
    )
    started = []
    original_thread = threading.Thread

    class FakeThread:
        def __init__(self, target=None, args=(), daemon=None, **kwargs):
            self._target = target
            self._args = args

        def start(self):
            started.append(True)
            # Do NOT call target — it would connect to MySQL

    monkeypatch.setattr(threading, "Thread", FakeThread)

    app = _patch_app(db, monkeypatch)
    client = TestClient(app, raise_server_exceptions=True)
    resp = client.post(
        "/api/workbench/export",
        json={},
        headers={"Authorization": "Bearer test_token"},
    )
    app.dependency_overrides.clear()

    assert resp.status_code == 202
    body = resp.json()
    assert "job_id" in body
    assert body["status"] == "pending"
    assert started


def test_wb_export_job_not_found(db, monkeypatch):
    app = _patch_app(db, monkeypatch)
    client = TestClient(app, raise_server_exceptions=True)
    resp = client.get(
        "/api/workbench/export/jobs/99999",
        headers={"Authorization": "Bearer test_token"},
    )
    app.dependency_overrides.clear()

    assert resp.status_code == 404


# ── upload confirm API ──────────────────────────────────────────
def test_upload_confirm_returns_job_id(db, monkeypatch, tmp_path):
    """POST /upload/confirm 应立即返回 job_id，不阻塞。"""
    import threading
    from app.models.database import get_db

    # Prevent background thread from running (would connect to MySQL)
    monkeypatch.setattr(
        "app.api.upload._run_upload_confirm_thread",
        lambda *args, **kwargs: None,
    )
    started = []
    original_thread = threading.Thread

    class FakeThread:
        def __init__(self, target=None, args=(), daemon=None, **kwargs):
            self._target = target
            self._args = args

        def start(self):
            started.append(True)
            # Do NOT call target — it would connect to MySQL

    monkeypatch.setattr(threading, "Thread", FakeThread)

    # 创建假的临时文件
    fake_id = "testfakeid123"
    fake_filename = "test.xlsx"
    upload_tmp = tmp_path / "tmp"
    upload_tmp.mkdir()
    (upload_tmp / f"{fake_id}_{fake_filename}").write_bytes(b"fake")

    # monkeypatch UPLOAD_DIR
    from app.core import config
    monkeypatch.setattr(config.settings, "UPLOAD_DIR", str(tmp_path))

    app = _patch_app(db, monkeypatch)
    app.dependency_overrides[get_db] = lambda: (yield db)

    client = TestClient(app, raise_server_exceptions=True)
    resp = client.post(
        "/api/upload/confirm",
        json={
            "temp_file_id": fake_id,
            "mapping": {
                "col_item_id":   "item_id",
                "col_month":     "month",
                "col_platform":  "platform",
                "col_item_name": "item_name",
                "col_sales_qty": "sales_qty",
                "col_amount":    "sales_amount",
                "col_price":     "price",
            },
            "ignore_columns": [],
        },
        headers={"Authorization": "Bearer test_token"},
    )
    app.dependency_overrides.clear()

    assert resp.status_code == 202
    body = resp.json()
    assert "job_id" in body
    assert body["status"] == "pending"
    assert started


def test_upload_confirm_job_not_found(db, monkeypatch):
    from app.models.database import get_db

    app = _patch_app(db, monkeypatch)
    app.dependency_overrides[get_db] = lambda: (yield db)

    client = TestClient(app, raise_server_exceptions=True)
    resp = client.get(
        "/api/upload/confirm/jobs/99999",
        headers={"Authorization": "Bearer test_token"},
    )
    app.dependency_overrides.clear()

    assert resp.status_code == 404
