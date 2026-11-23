"""Upload fixtures through the real headers/confirm/parser/import pipeline.

Only SQLite-safe progress reporting and thread scheduling are substituted. No
production database or files are touched. Strict xfails describe confirmed bugs;
run with --runxfail to see the failing acceptance criteria after a repair.
"""
import io
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import upload as upload_api
from app.core.config import settings
from app.models.database import Base, get_db
from app.models.schemas import Country, RawDataRecord, UploadFileRecord, UploadConfirmJob
from app.services.excel_parser import parse_with_mapping


FIXTURES = Path(__file__).resolve().parents[2] / "sample_data" / "upload_cases"
CASES = {case["file"]: case for case in json.loads((FIXTURES / "manifest.json").read_text())["cases"]}
REQUIRED_MAPPING = {field: field for field in upload_api.REQUIRED_FIELDS}


def known_bug(reason):
    return pytest.mark.xfail(strict=True, raises=AssertionError, reason=reason)


@pytest.fixture
def harness(tmp_path, monkeypatch):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    with sessions() as session:
        session.add_all([
            Country(code="CN", name_cn="中国", currency_code="CNY", region="domestic"),
            Country(code="US", name_cn="美国", currency_code="USD", region="overseas"),
            Country(code="SG", name_cn="新加坡", currency_code="SGD", region="overseas"),
        ])
        session.commit()

    queued = []

    class DeferredThread:
        def __init__(self, target, args=(), **kwargs):
            self.target, self.args = target, args

        def start(self):
            queued.append(self)

    def progress(db, job, **values):
        # SQLite cannot write progress on a second connection while importing.
        # Keep the import transaction intact; error updates follow a rollback.
        for key, value in values.items():
            if value is not None:
                setattr(job, key, value)
        if values.get("status") == "error":
            db.commit()

    monkeypatch.setattr(upload_api, "threading", SimpleNamespace(Thread=DeferredThread))
    monkeypatch.setattr(upload_api, "SessionLocal", sessions)
    monkeypatch.setattr(upload_api, "_update_upload_job_progress", progress)
    monkeypatch.setattr(upload_api, "_get_upload_job_progress_state", lambda job_id: {})
    monkeypatch.setattr(upload_api, "_is_upload_job_cancelled", lambda job_id: False)
    monkeypatch.setattr(upload_api, "invalidate_rawdata_cache", lambda: None)
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    app = FastAPI()
    app.include_router(upload_api.router)

    def get_test_db():
        with sessions() as session:
            yield session

    app.dependency_overrides[get_db] = get_test_db
    with TestClient(app, raise_server_exceptions=False) as client:
        yield SimpleNamespace(client=client, sessions=sessions, queued=queued, upload_dir=tmp_path)
    engine.dispose()


def prepare_case(harness, filename, **overrides):
    case = CASES[filename]
    source = FIXTURES / filename
    response = harness.client.post("/api/upload/headers", files={"file": (source.name, source.read_bytes())})
    assert response.status_code == 200, response.text
    payload = {
        "temp_file_id": response.json()["temp_file_id"],
        "mapping": case["mapping"], "ignore_columns": case["ignore_columns"],
        "country_code": case.get("country_code", "CN"),
        # Import tests represent a user who has accepted the quality review.
        "quality_reviewed": True,
        **overrides,
    }
    return payload


def submit(harness, filename, **overrides):
    return harness.client.post("/api/upload/confirm", json=prepare_case(harness, filename, **overrides))


def finish_upload(harness, response):
    assert response.status_code == 202, response.text
    thread = harness.queued.pop(0)
    thread.target(*thread.args)
    response = harness.client.get(f"/api/upload/confirm/jobs/{response.json()['job_id']}")
    assert response.status_code == 200, response.text
    return response.json()


def import_case(harness, filename, **overrides):
    return finish_upload(harness, submit(harness, filename, **overrides))


def inspect_case(harness, filename, **overrides):
    payload = prepare_case(harness, filename, **overrides)
    response = harness.client.post("/api/upload/validate", json=payload)
    assert response.status_code == 200, response.text
    assert not harness.queued
    with harness.sessions() as session:
        assert session.query(UploadFileRecord).count() == 0
        assert session.query(RawDataRecord).count() == 0
    return payload, response.json()


@pytest.mark.parametrize("filename", [
    "normal/jd.xlsx", "normal/tmall_utf8.csv", "normal/taobao_gbk.csv",
    "normal/202610_amazon_US_filename.xlsx", "normal/shopee.csv",
    "normal/custom_columns.csv", "normal/quoted_multiline.csv",
])
def test_normal_upload_files(harness, filename):
    job = import_case(harness, filename)
    assert job["status"] == "done", job
    assert job["inserted"] == CASES[filename]["inserted"]
    assert job["skipped"] == 0
    with harness.sessions() as session:
        assert session.query(RawDataRecord).count() == job["inserted"]


def test_extra_columns_and_ignored_columns(harness):
    job = import_case(harness, "normal/custom_columns.csv")
    assert job["status"] == "done"
    with harness.sessions() as session:
        rows = session.query(RawDataRecord).order_by(RawDataRecord.id).all()
        assert [item.extra_data for item in rows] == [{"颜色": "蓝色"}, {"颜色": "白色"}]


def test_text_ids_multiline_quotes_and_zeroes(harness):
    job = import_case(harness, "normal/quoted_multiline.csv")
    assert job["status"] == "done"
    with harness.sessions() as session:
        rows = session.query(RawDataRecord).order_by(RawDataRecord.id).all()
        assert rows[0].item_name == '测试标题, 含"引号"\n第二行'
        assert rows[1].item_id == "000001234567890123456789"
        assert rows[1].sales_qty == rows[1].sales_amount == rows[1].price == 0


@pytest.mark.parametrize("filename", ["dedup/in_file.csv", "dedup/cross_chunk_5002.csv"])
def test_dedup_across_rows_and_chunks(harness, filename):
    job = import_case(harness, filename)
    assert job["status"] == "done", job
    assert job["row_count"] == CASES[filename]["rows"]
    assert job["inserted"] == CASES[filename]["inserted"]
    assert job["skipped"] == 1
    assert len(job["preview"]) == min(50, CASES[filename]["rows"])
    with harness.sessions() as session:
        assert session.query(RawDataRecord).count() == job["inserted"]


def test_reimport_and_country_isolation(harness):
    first = import_case(harness, "dedup/reimport_a.csv")
    overlap = import_case(harness, "dedup/reimport_b.csv")
    repeat = import_case(harness, "dedup/reimport_a.csv")
    overseas = import_case(harness, "dedup/reimport_a.csv", country_code="US")
    assert [job["inserted"] for job in [first, overlap, repeat, overseas]] == [2, 1, 0, 2]
    assert [job["skipped"] for job in [first, overlap, repeat, overseas]] == [0, 1, 2, 0]
    with harness.sessions() as session:
        assert session.query(RawDataRecord).count() == 5


def test_missing_required_mapping_rejected_before_job_creation(harness):
    response = submit(harness, "invalid/missing_price.csv")
    assert response.status_code == 422
    assert "price" in response.json()["detail"]
    assert not harness.queued


def test_corrupt_excel_rejected_and_temp_removed(harness):
    source = FIXTURES / "invalid/corrupt.xlsx"
    response = harness.client.post("/api/upload/headers", files={"file": (source.name, source.read_bytes())})
    assert response.status_code == 422
    assert not list((harness.upload_dir / "tmp").iterdir())


def test_fractional_quantity_can_be_confirmed_after_warning(harness):
    payload, report = inspect_case(harness, "invalid/fractional_qty.csv")
    assert report["counts"]["invalid_number"] == 1
    assert report["samples"][0]["value"] == "1.5"
    job = finish_upload(harness, harness.client.post("/api/upload/confirm", json=payload))
    assert job["status"] == "done", job
    with harness.sessions() as session:
        assert session.query(RawDataRecord).one().sales_qty is None
        assert session.query(UploadFileRecord).count() == 1


@pytest.mark.parametrize("ack", [None, False, "true", 1])
def test_direct_confirm_cannot_silently_import_warnings(harness, ack):
    payload = prepare_case(harness, "invalid/missing_values.csv", quality_reviewed=ack)
    response = harness.client.post("/api/upload/confirm", json=payload)
    assert response.status_code == 409, response.text
    assert "3 行共 3 处" in response.json()["detail"]
    assert "仍然上传" in response.json()["detail"]
    assert response.json()["code"] == "upload_quality_review_required"
    assert response.json()["report"]["issue_count"] == 3
    assert response.json()["report"]["filename"] == "missing_values.csv"
    assert not harness.queued
    with harness.sessions() as session:
        assert session.query(UploadConfirmJob).count() == 0
        assert session.query(UploadFileRecord).count() == 0
        assert session.query(RawDataRecord).count() == 0
    # The same temporary file remains available for review and confirmation.
    report = harness.client.post("/api/upload/validate", json=payload)
    assert report.status_code == 200
    assert report.json()["issue_count"] == 3
    payload["quality_reviewed"] = True
    job = finish_upload(harness, harness.client.post("/api/upload/confirm", json=payload))
    assert job["status"] == "done", job
    assert job["inserted"] == 3


def test_direct_clean_confirm_remains_compatible_without_review_flag(harness):
    payload = prepare_case(harness, "normal/quoted_multiline.csv")
    payload.pop("quality_reviewed")
    job = finish_upload(harness, harness.client.post("/api/upload/confirm", json=payload))
    assert job["status"] == "done", job
    assert job["inserted"] == 2


def test_reviewed_confirm_does_not_scan_large_files_twice(harness, monkeypatch):
    payload, report = inspect_case(harness, "invalid/bad_numbers.csv")
    assert report["issue_count"] == 3
    def unexpected_scan(*args, **kwargs):
        raise AssertionError("A reviewed file must not be scanned twice")
    monkeypatch.setattr(upload_api, "inspect_upload_values", unexpected_scan)
    job = finish_upload(harness, harness.client.post("/api/upload/confirm", json=payload))
    assert job["status"] == "done", job


def test_later_chunk_failure_rolls_back_earlier_rows(harness, monkeypatch):
    real_iterator = upload_api.iter_mapped_chunks

    def fail_after_first_chunk(*args, **kwargs):
        yield next(real_iterator(*args, **kwargs))
        raise ValueError("injected second-chunk failure")

    monkeypatch.setattr(upload_api, "iter_mapped_chunks", fail_after_first_chunk)
    job = import_case(harness, "dedup/cross_chunk_5002.csv")
    assert job["status"] == "error", job
    assert "injected second-chunk failure" in job["error_msg"]
    with harness.sessions() as session:
        assert session.query(RawDataRecord).count() == 0
        assert session.query(UploadFileRecord).count() == 0


def test_same_name_upload_preserves_each_original(harness):
    first = import_case(harness, "same_name/a/data.csv")
    second = import_case(harness, "same_name/b/data.csv")
    assert first["status"] == second["status"] == "done"
    for job, folder in [(first, "a"), (second, "b")]:
        assert job["filename"] == "data.csv"
        downloaded = harness.client.get(f"/api/upload/files/{job['file_id']}/download")
        assert downloaded.status_code == 200
        assert downloaded.content == (FIXTURES / f"same_name/{folder}/data.csv").read_bytes()
        assert "data.csv" in downloaded.headers["content-disposition"]
    with harness.sessions() as session:
        files = session.query(UploadFileRecord).all()
        assert len({file.stored_filename for file in files}) == 2
        assert all(file.stored_filename for file in files)
        assert session.query(RawDataRecord).count() == 2


def test_legacy_upload_endpoint_preserves_same_name_originals(harness):
    uploaded = []
    for folder in ["a", "b"]:
        original = (FIXTURES / f"same_name/{folder}/data.csv").read_bytes()
        response = harness.client.post("/api/upload", files={"file": ("data.csv", original)})
        assert response.status_code == 200, response.text
        uploaded.append((response.json()["file_id"], original))
    for file_id, original in uploaded:
        response = harness.client.get(f"/api/upload/files/{file_id}/download")
        assert response.status_code == 200
        assert response.content == original


def test_failed_legacy_upload_preserves_existing_original(harness):
    original = (FIXTURES / "same_name/a/data.csv").read_bytes()
    response = harness.client.post("/api/upload", files={"file": ("data.csv", original)})
    assert response.status_code == 200, response.text
    file_id = response.json()["file_id"]
    failed = harness.client.post("/api/upload", files={"file": ("data.csv", b'"unterminated')})
    assert failed.status_code == 422
    downloaded = harness.client.get(f"/api/upload/files/{file_id}/download")
    assert downloaded.status_code == 200
    assert downloaded.content == original
    assert len(list((harness.upload_dir / "originals").iterdir())) == 1


def test_same_name_download_jobs_use_each_upload_record(harness):
    files = [import_case(harness, f"same_name/{folder}/data.csv") for folder in ["a", "b"]]
    for file, folder in zip(files, ["a", "b"]):
        created = harness.client.post(f"/api/upload/files/{file['file_id']}/download-jobs")
        assert created.status_code == 200
        thread = harness.queued.pop(0)
        thread.target(*thread.args)
        job_id = created.json()["job_id"]
        response = harness.client.get(f"/api/upload/download-jobs/{job_id}/download")
        assert response.status_code == 200
        assert response.content == (FIXTURES / f"same_name/{folder}/data.csv").read_bytes()
        assert "data.csv" in response.headers["content-disposition"]


def test_batch_preserves_same_name_originals(harness):
    first = import_case(harness, "same_name/a/data.csv", batch_key="same-name-batch")
    second = import_case(harness, "same_name/b/data.csv", batch_key="same-name-batch")
    response = harness.client.get("/api/upload/batches/same-name-batch/download")
    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert set(archive.namelist()) == {"data.csv", f"{second['file_id']}_data.csv"}
        assert archive.read("data.csv") == (FIXTURES / "same_name/a/data.csv").read_bytes()
        assert archive.read(f"{second['file_id']}_data.csv") == (FIXTURES / "same_name/b/data.csv").read_bytes()
    assert first["file_id"] != second["file_id"]


def test_new_upload_does_not_overwrite_legacy_same_name_file(harness):
    legacy_bytes = (FIXTURES / "same_name/a/data.csv").read_bytes()
    (harness.upload_dir / "data.csv").write_bytes(legacy_bytes)
    with harness.sessions() as session:
        legacy = UploadFileRecord(filename="data.csv", status="done", row_count=1)
        session.add(legacy)
        session.commit()
        legacy_id = legacy.id
    new = import_case(harness, "same_name/b/data.csv")
    assert new["status"] == "done"
    response = harness.client.get(f"/api/upload/files/{legacy_id}/download")
    assert response.status_code == 200
    assert response.content == legacy_bytes


def test_missing_new_original_does_not_download_legacy_same_name_file(harness):
    new = import_case(harness, "same_name/b/data.csv")
    with harness.sessions() as session:
        record = session.get(UploadFileRecord, new["file_id"])
        (harness.upload_dir / "originals" / record.stored_filename).unlink()
    (harness.upload_dir / "data.csv").write_bytes(b"unrelated legacy file")
    response = harness.client.get(f"/api/upload/files/{new['file_id']}/download")
    assert response.status_code == 404


@known_bug("P1: required source column names are not validated")
def test_nonexistent_required_source_column_is_rejected(harness):
    mapping = {**REQUIRED_MAPPING, "nonexistent": "item_name"}
    del mapping["item_name"]
    response = submit(harness, "normal/quoted_multiline.csv", mapping=mapping)
    assert response.status_code == 422


@known_bug("P1: ignored columns still satisfy required mapping validation")
def test_ignored_required_source_column_is_rejected(harness):
    response = submit(harness, "normal/quoted_multiline.csv", ignore_columns=["item_name"])
    assert response.status_code == 422


def test_required_cells_can_be_confirmed_after_warning(harness):
    payload, report = inspect_case(harness, "invalid/missing_values.csv")
    assert report["affected_rows"] == report["issue_count"] == 3
    assert report["counts"]["missing_required"] == 3
    assert [sample["row"] for sample in report["samples"]] == [2, 3, 4]
    job = finish_upload(harness, harness.client.post("/api/upload/confirm", json=payload))
    assert job["status"] == "done", job
    assert job["inserted"] == 3


def test_invalid_numbers_can_be_confirmed_after_warning(harness):
    payload, report = inspect_case(harness, "invalid/bad_numbers.csv")
    assert report["counts"]["invalid_number"] == 3
    assert report["affected_rows"] == 2
    assert {sample["value"] for sample in report["samples"]} == {"1,299.00", "￥99.00", "未知"}
    job = finish_upload(harness, harness.client.post("/api/upload/confirm", json=payload))
    assert job["status"] == "done", job
    assert job["inserted"] == 2
    with harness.sessions() as session:
        rows = session.query(RawDataRecord).order_by(RawDataRecord.id).all()
        assert rows[0].price is None
        assert rows[0].sales_amount is None
        assert rows[1].sales_qty is None


def test_invalid_month_can_be_confirmed_after_warning(harness):
    payload, report = inspect_case(harness, "invalid/invalid_month.csv")
    assert report["counts"]["invalid_month"] == 2
    job = finish_upload(harness, harness.client.post("/api/upload/confirm", json=payload))
    assert job["status"] == "done", job
    with harness.sessions() as session:
        assert {row.month for row in session.query(RawDataRecord)} == {202600, 202613}


def test_clean_data_check_has_no_warnings_and_creates_no_job(harness):
    payload, report = inspect_case(harness, "normal/quoted_multiline.csv")
    assert report["issue_count"] == report["affected_rows"] == 0
    assert report["total_rows"] == 2
    job = finish_upload(harness, harness.client.post("/api/upload/confirm", json=payload))
    assert job["status"] == "done"


@pytest.mark.parametrize("temp_id, expected", [("../*", 400), ("", 400), ("00000000-0000-0000-0000-000000000000", 404)])
def test_invalid_or_expired_check_request(harness, temp_id, expected):
    response = harness.client.post("/api/upload/validate", json={"temp_file_id": temp_id})
    assert response.status_code == expected
    assert not harness.queued


@known_bug("P2: empty workbooks are marked done with zero rows")
def test_empty_workbook_is_rejected(harness):
    job = import_case(harness, "invalid/empty.xlsx")
    assert job["status"] == "error", job


@known_bug("P2: two columns can map to the same standard field")
def test_duplicate_target_mapping_is_rejected_before_start(harness):
    response = submit(harness, "invalid/duplicate_target.csv")
    assert response.status_code == 422


@known_bug("P2: extension validation is case sensitive")
def test_uppercase_csv_extension_is_supported(harness):
    source = FIXTURES / "invalid/uppercase.CSV"
    response = harness.client.post("/api/upload/headers", files={"file": (source.name, source.read_bytes())})
    assert response.status_code == 200


@known_bug("P1: filename metadata silently overwrites conflicting row values")
def test_filename_row_conflict_is_reported(harness):
    job = import_case(harness, "filename_conflict/202611_amazon_US_conflict.csv")
    assert job["status"] == "error", job


@known_bug("P2: UI year overrides filename year in upload history")
def test_history_year_matches_imported_month(harness):
    job = import_case(harness, "normal/202610_amazon_US_filename.xlsx", data_year=2025)
    assert job["status"] == "done", job
    with harness.sessions() as session:
        file = session.get(UploadFileRecord, job["file_id"])
        row = session.query(RawDataRecord).first()
        assert file.data_year == row.month // 100


def test_only_first_sheet_is_currently_read():
    case = CASES["invalid/multiple_sheets.xlsx"]
    rows, _, _ = parse_with_mapping(FIXTURES / case["file"], case["mapping"], [])
    assert [row["item_id"] for row in rows] == ["UPLOAD-TEST-SHEET-1"]
