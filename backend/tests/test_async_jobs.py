"""Tests for WorkbenchExportJob and UploadConfirmJob ORM models."""
from datetime import datetime

from app.models.schemas import WorkbenchExportJob, UploadConfirmJob, UploadFileRecord


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
    assert job.stage == "pending"
    assert job.stage_label == "等待处理"
    assert job.filename is None
    assert job.total_rows is None
    assert job.processed_rows == 0
    assert job.inserted_rows == 0
    assert job.skipped_rows == 0
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
def test_list_upload_files_returns_uploaded_at_as_beijing_time_string(db, monkeypatch):
    from app.models.database import get_db

    record = UploadFileRecord(
        filename="demo.xlsx",
        platform="TM",
        month_range="202605",
        row_count=10,
        status="done",
        uploaded_at=datetime(2026, 5, 24, 15, 6, 58),
    )
    db.add(record)
    db.commit()

    app = _patch_app(db, monkeypatch)
    app.dependency_overrides[get_db] = lambda: (yield db)
    client = TestClient(app, raise_server_exceptions=True)
    resp = client.get("/api/upload/files", headers={"Authorization": "Bearer test_token"})
    app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body[0]["uploaded_at"] == "2026-05-24 23:06:58"


def test_upload_job_progress_helper_persists_stage_fields(db, monkeypatch):
    from sqlalchemy.orm import sessionmaker
    from app.api.upload import _update_upload_job_progress
    import app.api.upload as upload_api

    monkeypatch.setattr(upload_api, "SessionLocal", sessionmaker(bind=db.get_bind()))

    job = UploadConfirmJob(filename="demo.xlsx")
    db.add(job)
    db.commit()

    _update_upload_job_progress(
        db,
        job,
        status="running",
        stage="inserting",
        stage_label="正在写入数据",
        progress=75,
        total_rows=1000,
        processed_rows=700,
        inserted_rows=650,
        skipped_rows=50,
    )
    db.expire_all()
    db.refresh(job)

    assert job.status == "running"
    assert job.stage == "inserting"
    assert job.stage_label == "正在写入数据"
    assert job.progress == 75
    assert job.total_rows == 1000
    assert job.processed_rows == 700
    assert job.inserted_rows == 650
    assert job.skipped_rows == 50
    upload_api._upload_progress.pop(job.id, None)


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


def test_upload_confirm_job_detail_returns_persisted_progress(db, monkeypatch):
    from app.models.database import get_db
    from app.api.upload import _upload_progress

    job = UploadConfirmJob(
        filename="demo.xlsx",
        status="running",
        stage="inserting",
        stage_label="正在写入数据",
        progress=76,
        total_rows=1000,
        processed_rows=700,
        inserted_rows=650,
        skipped_rows=50,
    )
    db.add(job)
    db.commit()
    _upload_progress[job.id] = job.progress

    app = _patch_app(db, monkeypatch)
    app.dependency_overrides[get_db] = lambda: (yield db)
    client = TestClient(app, raise_server_exceptions=True)
    resp = client.get(f"/api/upload/confirm/jobs/{job.id}", headers={"Authorization": "Bearer test_token"})
    app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["filename"] == "demo.xlsx"
    assert body["status"] == "running"
    assert body["stage"] == "inserting"
    assert body["stage_label"] == "正在写入数据"
    assert body["progress"] == 76
    assert body["total_rows"] == 1000
    assert body["processed_rows"] == 700
    assert body["inserted_rows"] == 650
    assert body["skipped_rows"] == 50
    _upload_progress.pop(job.id, None)


def test_list_upload_confirm_jobs_returns_actionable_named_jobs_by_default(db, monkeypatch):
    from app.models.database import get_db

    done = UploadConfirmJob(filename="done.xlsx", status="done", stage="done", stage_label="处理完成", progress=100)
    running = UploadConfirmJob(filename="running.xlsx", status="running", stage="reading", stage_label="正在读取文件", progress=5)
    pending = UploadConfirmJob(filename="pending.xlsx", status="pending", stage="pending", stage_label="等待处理", progress=0)
    failed = UploadConfirmJob(filename="failed.xlsx", status="error", stage="error", stage_label="文件解析失败", progress=20)
    unnamed = UploadConfirmJob(filename=None, status="running", stage="pending", stage_label="等待处理", progress=0)
    empty_name = UploadConfirmJob(filename="", status="running", stage="pending", stage_label="等待处理", progress=0)
    db.add_all([done, running, pending, failed, unnamed, empty_name])
    db.commit()

    from app.api.upload import _upload_progress
    _upload_progress[running.id] = running.progress

    app = _patch_app(db, monkeypatch)
    app.dependency_overrides[get_db] = lambda: (yield db)
    client = TestClient(app, raise_server_exceptions=True)
    resp = client.get("/api/upload/confirm/jobs", headers={"Authorization": "Bearer test_token"})
    app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert [row["filename"] for row in body] == ["failed.xlsx", "pending.xlsx", "running.xlsx"]
    assert {row["status"] for row in body} == {"pending", "running", "error"}
    _upload_progress.pop(running.id, None)


def test_list_upload_confirm_jobs_can_query_done_jobs_by_status(db, monkeypatch):
    from app.models.database import get_db

    done = UploadConfirmJob(filename="done.xlsx", status="done", stage="done", stage_label="处理完成", progress=100)
    running = UploadConfirmJob(filename="running.xlsx", status="running", stage="reading", stage_label="正在读取文件", progress=5)
    unnamed_done = UploadConfirmJob(filename=None, status="done", stage="done", stage_label="处理完成", progress=100)
    db.add_all([done, running, unnamed_done])
    db.commit()

    app = _patch_app(db, monkeypatch)
    app.dependency_overrides[get_db] = lambda: (yield db)
    client = TestClient(app, raise_server_exceptions=True)
    resp = client.get("/api/upload/confirm/jobs?status=done", headers={"Authorization": "Bearer test_token"})
    app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert [row["filename"] for row in body] == ["done.xlsx"]
    assert body[0]["status"] == "done"


def test_list_upload_confirm_jobs_marks_stale_running_jobs_interrupted(db, monkeypatch):
    from app.models.database import get_db

    job = UploadConfirmJob(filename="stale.xlsx", status="running", stage="deduping", stage_label="正在去重检查", progress=53)
    db.add(job)
    db.commit()

    app = _patch_app(db, monkeypatch)
    app.dependency_overrides[get_db] = lambda: (yield db)
    client = TestClient(app, raise_server_exceptions=True)
    resp = client.get("/api/upload/confirm/jobs", headers={"Authorization": "Bearer test_token"})
    app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body[0]["filename"] == "stale.xlsx"
    assert body[0]["status"] == "error"
    assert body[0]["stage"] == "interrupted"
    assert body[0]["stage_label"] == "任务已中断"
    assert "后台处理线程已中断" in body[0]["error_msg"]


def test_cancel_upload_confirm_job_marks_running_job_cancelled(db, monkeypatch):
    from app.models.database import get_db

    job = UploadConfirmJob(filename="running.xlsx", status="running", stage="reading", stage_label="正在读取文件", progress=5)
    db.add(job)
    db.commit()

    app = _patch_app(db, monkeypatch)
    app.dependency_overrides[get_db] = lambda: (yield db)
    client = TestClient(app, raise_server_exceptions=True)
    resp = client.post(f"/api/upload/confirm/jobs/{job.id}/cancel", headers={"Authorization": "Bearer test_token"})
    app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "cancelled"
    assert body["stage"] == "cancelled"
    assert body["stage_label"] == "已取消"
    assert body["finished_at"] is not None


def test_cancel_upload_confirm_job_rejects_finished_job(db, monkeypatch):
    from app.models.database import get_db

    job = UploadConfirmJob(filename="done.xlsx", status="done", stage="done", stage_label="处理完成", progress=100)
    db.add(job)
    db.commit()

    app = _patch_app(db, monkeypatch)
    app.dependency_overrides[get_db] = lambda: (yield db)
    client = TestClient(app, raise_server_exceptions=True)
    resp = client.post(f"/api/upload/confirm/jobs/{job.id}/cancel", headers={"Authorization": "Bearer test_token"})
    app.dependency_overrides.clear()

    assert resp.status_code == 409


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
