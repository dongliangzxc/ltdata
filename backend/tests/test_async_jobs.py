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
