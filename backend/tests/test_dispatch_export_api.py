from datetime import datetime

import pytest

from app.api import dispatch_api
from app.api.dispatch_api import DispatchExportParams, create_dispatch_export_job
from app.models.schemas import (
    ColumnTemplate,
    DispatchBatch,
    DispatchItem,
    RawDataRecord,
    UploadFileRecord,
    WorkbenchExportJob,
)


class NoopThread:
    def __init__(self, target=None, args=(), daemon=None):
        self.target = target
        self.args = args
        self.daemon = daemon

    def start(self):
        return None


def _disable_export_thread(monkeypatch):
    monkeypatch.setattr(dispatch_api.threading, "Thread", NoopThread)


def _seed_dispatch_row(db, *, file_id, batch_id, raw_id, month, category_code="camera", platform="jd"):
    raw = RawDataRecord(
        id=raw_id,
        file_id=file_id,
        platform=platform,
        month=month,
        item_id=f"item-{raw_id}",
        item_name=f"商品 {raw_id}",
    )
    item = DispatchItem(
        batch_id=batch_id,
        raw_data_id=raw_id,
        category_code=category_code,
    )
    db.add_all([raw, item])


def _seed_latest_dispatch_data(db):
    template = ColumnTemplate(name="测试模板", module="sales", mapping={}, ignore_columns=[])
    db.add(template)
    db.flush()
    file_record = UploadFileRecord(
        filename="dispatch.xlsx",
        platform="jd",
        row_count=3,
        status="done",
        template_id=template.id,
    )
    db.add(file_record)
    db.flush()
    batch = DispatchBatch(file_id=file_record.id, status="done", total_rows=3, dispatched_rows=3, unmatched_rows=0)
    db.add(batch)
    db.flush()
    _seed_dispatch_row(db, file_id=file_record.id, batch_id=batch.id, raw_id=1, month=202601)
    _seed_dispatch_row(db, file_id=file_record.id, batch_id=batch.id, raw_id=2, month=202602)
    _seed_dispatch_row(db, file_id=file_record.id, batch_id=batch.id, raw_id=3, month=202603)
    db.commit()


def test_create_dispatch_export_accepts_multiple_months(db, monkeypatch):
    _seed_latest_dispatch_data(db)
    _disable_export_thread(monkeypatch)

    response = create_dispatch_export_job(
        DispatchExportParams(category_code="camera", months=[202602, 202601]),
        db,
    )

    assert response == {"job_id": 1, "status": "pending"}
    job = db.query(WorkbenchExportJob).filter(WorkbenchExportJob.id == response["job_id"]).first()
    assert job.month == 202601
    assert job.params == {"month": 202601, "months": [202601, 202602]}


def test_create_dispatch_export_keeps_legacy_month_compatibility(db, monkeypatch):
    _seed_latest_dispatch_data(db)
    _disable_export_thread(monkeypatch)

    response = create_dispatch_export_job(
        DispatchExportParams(category_code="camera", month=202602),
        db,
    )

    job = db.query(WorkbenchExportJob).filter(WorkbenchExportJob.id == response["job_id"]).first()
    assert job.month == 202602
    assert job.params == {"month": 202602, "months": [202602]}


def test_create_dispatch_export_rejects_invalid_months(db):
    _seed_latest_dispatch_data(db)

    with pytest.raises(dispatch_api.HTTPException) as exc_info:
        create_dispatch_export_job(DispatchExportParams(category_code="camera", months=[202613]), db)

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "月份格式应为 YYYYMM"


def test_create_dispatch_export_rejects_empty_filters_with_empty_months(db):
    with pytest.raises(dispatch_api.HTTPException) as exc_info:
        create_dispatch_export_job(DispatchExportParams(months=[]), db)

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "请选择品类、平台或月份后再导出"


def test_latest_dispatch_export_query_filters_multiple_months(db):
    _seed_latest_dispatch_data(db)

    rows = dispatch_api._latest_dispatch_export_query(db, "camera", None, [202601, 202603]).order_by(RawDataRecord.month).all()

    assert [raw.month for _item, raw, _file, _template in rows] == [202601, 202603]


def test_dispatch_export_job_out_includes_months_for_new_and_legacy_jobs(db):
    new_job = WorkbenchExportJob(
        id=1,
        status="pending",
        progress=0,
        category_code="camera",
        platform="jd",
        month=202601,
        params={"months": [202601, 202602], "month": 202601},
        created_at=datetime.utcnow(),
    )
    legacy_job = WorkbenchExportJob(
        id=2,
        status="pending",
        progress=0,
        category_code="camera",
        platform="jd",
        month=202603,
        created_at=datetime.utcnow(),
    )

    assert dispatch_api._dispatch_export_job_out(new_job)["months"] == [202601, 202602]
    assert dispatch_api._dispatch_export_job_out(legacy_job)["months"] == [202603]
