"""Durable queue, isolation, interruption recovery and real async API behaviour."""
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.orm import Session

from app.api import clean, match_api, publish_api
from app.core.auth_deps import get_current_user
from app.core.config import settings
from app.models.database import Base, get_db
from app.models.schemas import (
    AttrRule, Category, CleanedDataRecord, CleanJobItemRecord, CleanJobRecord,
    CleanTaskRun, DispatchBatch, DispatchItem, ItemUrlMapping, MatchResult,
    MatchResultAttr, ModelRecord, RawDataRecord, UploadFileRecord,
    MatchResultExtraValue,
    PublishJob,
)
from app.services import clean_task_queue as queue


@pytest.fixture(autouse=True)
def enabled_background(monkeypatch):
    monkeypatch.setattr(settings, "CLEAN_BACKGROUND_ENABLED", True)


def _client(db, *, category_permissions=None):
    app = FastAPI()
    for router in (clean.router, match_api.router, publish_api.router):
        app.include_router(router)

    def database():
        yield db

    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        is_admin=0 if category_permissions else 1, category_permissions=category_permissions,
    )
    return TestClient(app)


def _pending(db, *, category="headphone", month=202603, item_id="123"):
    if db.query(Category).filter_by(code=category).first() is None:
        db.add(Category(code=category, name=category))
    upload = UploadFileRecord(filename=f"{item_id}.xlsx", status="done", platform="jd")
    db.add(upload)
    db.flush()
    raw = RawDataRecord(file_id=upload.id, platform="jd", month=month, item_id=item_id,
                        item_url=f"https://item.jd.com/{item_id}.html", item_name="商品", shop_name="官方店")
    batch = DispatchBatch(file_id=upload.id, status="done")
    db.add_all([raw, batch])
    db.flush()
    db.add(DispatchItem(batch_id=batch.id, raw_data_id=raw.id, category_code=category))
    db.commit()
    return raw.id


def _submit(client, *, category="headphone", month=202603, **extra):
    response = client.post("/api/clean/tasks/upsert-monthly", json=dict(
        category_code=category, platform="jd", month=month, **extra,
    ))
    assert response.status_code == 200, response.text
    return response.json()["job"]["id"]


def test_submission_commits_queue_and_snapshot_without_running_clean_or_match(db, monkeypatch):
    raw_id = _pending(db)
    client = _client(db)
    monkeypatch.setattr(clean, "run_clean", lambda *a, **k: pytest.fail("HTTP request executed cleaning"))
    monkeypatch.setattr(clean, "run_match", lambda *a, **k: pytest.fail("HTTP request executed matching"))

    job_id = _submit(client)
    db.expire_all()
    assert db.get(CleanJobRecord, job_id).status == "queued"
    run = db.query(CleanTaskRun).one()
    assert (run.clean_job_id, run.state, run.stage, run.processed, run.total) == (job_id, "queued", "排队中", 0, 1)
    assert db.query(CleanJobItemRecord).one().raw_data_id == raw_id
    assert db.query(CleanedDataRecord).count() == 0


def test_category_submission_also_returns_queued_and_retains_membership(db):
    _pending(db)
    response = _client(db).post("/api/clean/tasks", json={"category_code": "headphone", "platform": "jd"})
    assert response.status_code == 200, response.text
    assert response.json()["match_status"] == "queued"
    assert response.json()["job"]["status"] == "queued"
    assert db.query(CleanTaskRun).count() == db.query(CleanJobItemRecord).count() == 1


def test_queue_failure_rolls_back_new_snapshot_and_job(db, monkeypatch):
    _pending(db)
    def fail(*a):
        raise RuntimeError("queue insert failed")
    monkeypatch.setattr(clean, "enqueue_clean_job", fail)
    response = _client(db).post("/api/clean/tasks/upsert-monthly", json={
        "category_code": "headphone", "platform": "jd", "month": 202603,
    })
    assert response.status_code == 500
    assert db.query(CleanJobRecord).count() == db.query(CleanJobItemRecord).count() == db.query(CleanTaskRun).count() == 0


@pytest.mark.parametrize("force", [{}, {"force_reclean": True}, {"force_rebuild": True}])
def test_repeated_submission_cannot_mutate_busy_snapshot(db, force):
    raw_id = _pending(db)
    client = _client(db)
    job_id = _submit(client)
    response = client.post("/api/clean/tasks/upsert-monthly", json={
        "category_code": "headphone", "platform": "jd", "month": 202603, **force,
    })
    assert response.status_code == 409
    assert db.query(CleanTaskRun).count() == 1
    assert db.query(CleanJobItemRecord).one().raw_data_id == raw_id
    assert db.get(CleanJobRecord, job_id).status == "queued"


def test_real_worker_cleans_matches_and_finishes_after_http_request_is_gone(db):
    raw_id = _pending(db)
    job_id = _submit(_client(db))
    assert queue.execute_next_run(db)
    db.expire_all()
    assert db.get(CleanJobRecord, job_id).status == "reviewing"
    run = db.query(CleanTaskRun).one()
    assert (run.state, run.stage) == ("done", "处理完成")
    assert db.query(CleanedDataRecord).one().raw_data_id == raw_id
    assert db.query(MatchResult).one().match_status == "pending"
    assert not queue.execute_next_run(db)


def _reviewed_job_with_new_dispatch(db, status="reviewing"):
    old_raw_id = _pending(db)
    client = _client(db)
    job_id = _submit(client)
    assert queue.execute_next_run(db)
    model = ModelRecord(brand_code="TEST", model_code="OLD", category_code="headphone")
    db.add(model)
    db.flush()
    result = db.query(MatchResult).one()
    result.model_id, result.match_status, result.matched_by = model.id, "confirmed", "manual"
    result.review_note, result.sales_coefficient = "保留原确认", 0.8
    attr = MatchResultAttr(match_result_id=result.id, attr_name="类型", attr_value="耳机")
    extra = MatchResultExtraValue(match_result_id=result.id, field_key="智能", field_value="是", source="manual")
    publication = PublishJob(clean_job_id=job_id, status="done", published_count=1)
    db.add_all([attr, extra, publication])
    db.get(CleanJobRecord, job_id).status = status
    db.commit()
    records = [result, attr, extra, publication, db.query(CleanedDataRecord).one()]
    before = [(type(obj), obj.id, {col.name: getattr(obj, col.name) for col in obj.__table__.columns})
              for obj in records]
    new_raw_id = _pending(db, item_id="456")
    return client, job_id, old_raw_id, new_raw_id, before


def _assert_original_results_unchanged(db, before):
    db.expire_all()
    for model, record_id, values in before:
        current = db.get(model, record_id)
        assert current is not None
        assert {col.name: getattr(current, col.name) for col in current.__table__.columns} == values


@pytest.mark.parametrize("status", ["reviewing", "done", "published"])
def test_reviewed_monthly_task_exposes_append_and_worker_preserves_original_results(db, status):
    client, job_id, old_id, new_id, before = _reviewed_job_with_new_dispatch(db, status)
    pool = client.get("/api/clean/pool/monthly?category_code=headphone&platform=jd&month=202603")
    assert pool.status_code == 200
    row = pool.json()[0]
    assert (row["existing_job_id"], row["pending_count"], row["queued_count"],
            row["has_reviewed_or_published"]) == (job_id, 1, 1, True)

    response = client.post("/api/clean/tasks/upsert-monthly", json={
        "category_code": "headphone", "platform": "jd", "month": 202603,
    })
    assert response.status_code == 200, response.text
    assert response.json()["action"] == "appended"
    assert response.json()["match_status"] == "queued"
    assert response.json()["snapshot_count"] == 1
    run = db.query(CleanTaskRun).one()
    assert (run.mode, run.input_count) == ("incremental", 1)
    queued_ids = [r[0] for r in db.query(CleanJobItemRecord.raw_data_id).filter(
        CleanJobItemRecord.clean_job_id == job_id,
        CleanJobItemRecord.id.between(run.snapshot_start_id, run.snapshot_end_id),
    )]
    assert queued_ids == [new_id]
    _assert_original_results_unchanged(db, before)
    assert queue.execute_next_run(db)
    _assert_original_results_unchanged(db, before)
    assert db.query(MatchResult).filter_by(clean_job_id=job_id).count() == 2
    assert db.query(MatchResult).filter_by(clean_job_id=job_id, raw_data_id=old_id).one().match_status == "confirmed"
    assert db.query(MatchResult).filter_by(clean_job_id=job_id, raw_data_id=new_id).count() == 1
    assert client.get("/api/clean/pool/monthly?category_code=headphone&platform=jd&month=202603").json() == []

    # Repeating the append neither reruns old rows nor creates another queue run.
    again = client.post("/api/clean/tasks/upsert-monthly", json={
        "category_code": "headphone", "platform": "jd", "month": 202603,
    })
    assert again.status_code == 200, again.text
    assert (again.json()["snapshot_count"], again.json()["match_status"]) == (0, "unchanged")
    assert db.query(CleanTaskRun).one().state == "done"
    _assert_original_results_unchanged(db, before)


def test_reviewed_monthly_append_failure_can_retry_without_overwriting_old_results(db, monkeypatch):
    client, job_id, old_id, new_id, before = _reviewed_job_with_new_dispatch(db)
    _submit(client)
    with monkeypatch.context() as patch:
        def fail(*args, **kwargs):
            raise RuntimeError("模拟新增匹配失败")
        patch.setattr(clean, "run_match", fail)
        assert queue.execute_next_run(db)
    assert db.get(CleanJobRecord, job_id).status == "failed"
    _assert_original_results_unchanged(db, before)
    assert db.query(CleanedDataRecord).filter_by(clean_job_id=job_id, raw_data_id=new_id).count() == 0
    assert client.post(f"/api/clean/tasks/{job_id}/retry").status_code == 200
    assert queue.execute_next_run(db)
    _assert_original_results_unchanged(db, before)
    assert db.query(MatchResult).filter_by(clean_job_id=job_id).count() == 2


def test_fifo_retry_and_failure_do_not_delete_task_or_block_next_job(db):
    _pending(db)
    _pending(db, month=202604, item_id="456")
    client = _client(db)
    first, second = _submit(client), _submit(client, month=202604)
    calls = []

    def executor(db, job, stage_progress_cb):
        calls.append(job.id)
        stage_progress_cb("清洗中", 0, 1)
        raise RuntimeError("模拟清洗失败")

    assert queue.execute_next_run(db, executor=executor)
    assert db.get(CleanJobRecord, first).status == "failed"
    assert db.get(CleanJobRecord, first).error_msg == "模拟清洗失败"
    assert db.query(CleanJobItemRecord).filter_by(clean_job_id=first).count() == 1
    assert db.get(CleanJobRecord, second).status == "queued"
    retry = client.post(f"/api/clean/tasks/{first}/retry")
    assert retry.status_code == 200, retry.text
    assert client.post(f"/api/clean/tasks/{first}/retry").status_code == 409
    assert queue.execute_next_run(db, executor=executor)
    assert calls == [first, second]
    assert db.get(CleanJobRecord, first).status == "queued"


def test_restart_only_marks_running_managed_jobs_and_preserves_queue(db):
    db.add_all([CleanJobRecord(id=1, status="matching"), CleanJobRecord(id=2, status="queued"),
                CleanJobRecord(id=3, status="created"), CleanJobRecord(id=4, status="reviewing")])
    db.flush()
    db.add_all([CleanTaskRun(clean_job_id=1, state="running", stage="型号匹配中", processed=500, total=1000),
                CleanTaskRun(clean_job_id=2, state="queued"), CleanTaskRun(clean_job_id=4, state="done")])
    db.commit()
    assert queue.recover_interrupted_runs(db) == 1
    assert db.get(CleanJobRecord, 1).status == "failed"
    assert db.query(CleanTaskRun).filter_by(clean_job_id=1).one().processed == 500
    assert db.get(CleanJobRecord, 2).status == "queued"
    assert db.get(CleanJobRecord, 3).status == "created"
    assert db.get(CleanJobRecord, 4).status == "reviewing"


def test_progress_is_scoped_lightweight_and_exposes_failure(db):
    _pending(db)
    _pending(db, category="camera", item_id="456")
    client = _client(db)
    first = _submit(client)
    second = _submit(client, category="camera")
    db.get(CleanJobRecord, first).status = "failed"
    db.get(CleanJobRecord, first).error_msg = "模拟失败"
    run = db.query(CleanTaskRun).filter_by(clean_job_id=first).one()
    run.state, run.stage, run.processed, run.total = "failed", "清洗中", 2, 5
    db.commit()
    statements = []
    def capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)
    event.listen(db.get_bind(), "before_cursor_execute", capture)
    try:
        response = _client(db, category_permissions=["headphone"]).get(f"/api/clean/jobs/progress?ids={first},{second}")
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", capture)
    assert response.status_code == 200, response.text
    assert len(response.json()) == 1
    result = response.json()[0]
    assert (result["id"], result["progress_processed"], result["progress_total"], result["can_retry"], result["error_msg"]) == (first, 2, 5, True, "模拟失败")
    assert not any("match_results" in sql or "raw_data" in sql or "COUNT(" in sql.upper() for sql in statements)


def test_busy_job_cannot_delete_publish_supplement_or_edit_match(db):
    _pending(db)
    client = _client(db)
    job_id = _submit(client)
    db.add(MatchResult(clean_job_id=job_id, raw_data_id=db.query(RawDataRecord).first().id, match_status="pending"))
    db.commit()
    match_id = db.query(MatchResult).one().id
    assert client.delete(f"/api/clean/jobs/{job_id}").status_code == 409
    assert client.post("/api/publish/run", json={"clean_job_id": job_id}).status_code == 409
    assert client.post(f"/api/clean/tasks/{job_id}/rerun-with-current-rules").status_code == 409
    assert client.post(f"/api/clean/tasks/{job_id}/supplement", files={"file": ("new.csv", b"x\n1", "text/csv")}).status_code == 409
    assert client.put(f"/api/match/confirm/{match_id}", json={"model_id": 1}).status_code == 409


def test_progress_throttles_but_persists_phase_changes_and_completion(db, monkeypatch):
    db.add(CleanJobRecord(id=1, status="cleaning"))
    db.flush()
    run = CleanTaskRun(clean_job_id=1, state="running", worker_token="owned")
    db.add(run)
    db.commit()
    writer = queue.CleanProgressWriter(db, run.id, "owned")
    monkeypatch.setattr(queue.time, "monotonic", lambda: 10.0)
    writer("清洗中", 0, 100)
    writer("清洗中", 50, 100)
    db.expire_all()
    assert db.get(CleanTaskRun, run.id).processed == 0
    writer("清洗中", 100, 100)
    writer("型号匹配中", 0, 90)
    db.expire_all()
    saved = db.get(CleanTaskRun, run.id)
    assert (saved.stage, saved.processed, saved.total) == ("型号匹配中", 0, 90)
    saved.worker_token = "other"
    db.commit()
    with pytest.raises(queue.LostCleanOwnership):
        writer("型号匹配中", 90, 90)


def test_execution_lock_excludes_another_process_and_releases(tmp_path):
    database = tmp_path / "queue.db"
    bind = create_engine(f"sqlite:///{database}")
    code = "from sqlalchemy import create_engine; from app.services.clean_task_queue import clean_execution_lock; e=create_engine(" + repr(f"sqlite:///{database}") + ");\nwith clean_execution_lock(e) as c: print(c is not None)"
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]))
    with queue.clean_execution_lock(bind) as connection:
        assert connection is not None
        result = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=15)
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "False"
    with queue.clean_execution_lock(bind) as connection:
        assert connection is not None


@pytest.mark.parametrize("acquired,fail", [(True, False), (True, True), (False, False)])
def test_mysql_execution_lock_releases_owned_lock_even_when_work_fails(acquired, fail):
    calls = []
    class Connection:
        invalidated = False
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def execute(self, statement, params):
            calls.append(str(statement))
            return SimpleNamespace(scalar=lambda: int(acquired))
        def commit(self):
            pass
        def rollback(self):
            pass
    bind = SimpleNamespace(dialect=SimpleNamespace(name="mysql"),
                           url=SimpleNamespace(database="isolated-test"), connect=Connection)
    def work():
        with queue.clean_execution_lock(bind) as connection:
            assert (connection is not None) is acquired
            if fail:
                raise RuntimeError("work failed")
    if fail:
        with pytest.raises(RuntimeError, match="work failed"):
            work()
    else:
        work()
    assert sum("GET_LOCK" in statement for statement in calls) == 1
    assert sum("RELEASE_LOCK" in statement for statement in calls) == int(acquired)


def test_strict_audit_failure_keeps_snapshot_and_can_retry_automatic_attributes(db, monkeypatch):
    _pending(db)
    model = ModelRecord(brand_code="SONY", model_code="MODEL", category_code="headphone")
    db.add(model)
    db.flush()
    db.add_all([ItemUrlMapping(platform="jd", item_id="123", model_id=model.id),
                AttrRule(attr_name="连接", attr_value="蓝牙", keyword="商品", match_type="contains", is_active=1)])
    db.commit()
    client = _client(db)
    job_id = _submit(client)
    def fail(*args, **kwargs):
        raise RuntimeError("价格审核失败")
    monkeypatch.setattr("app.services.matcher.audit_price", fail)
    assert queue.execute_next_run(db)
    assert db.get(CleanJobRecord, job_id).status == "failed"
    assert db.query(MatchResultAttr).count() == 1
    assert db.query(CleanJobItemRecord).count() == 1
    assert client.post(f"/api/clean/tasks/{job_id}/retry").status_code == 200
    def audited(db, ids, commit=True, progress_cb=None):
        if progress_cb:
            progress_cb(len(ids), len(ids))
        return {"audited": len(ids)}
    monkeypatch.setattr("app.services.matcher.audit_price", audited)
    assert queue.execute_next_run(db)
    assert db.get(CleanJobRecord, job_id).status == "reviewing"


@pytest.mark.parametrize("manual_kind", ["review", "extra_field"])
def test_retry_refuses_to_discard_manual_changes(db, manual_kind):
    raw_id = _pending(db)
    client = _client(db)
    job_id = _submit(client)
    def fail(*args, **kwargs):
        raise RuntimeError("failed")
    queue.execute_next_run(db, executor=fail)
    result = MatchResult(clean_job_id=job_id, raw_data_id=raw_id,
                         matched_by="manual" if manual_kind == "review" else "auto",
                         match_status="confirmed" if manual_kind == "review" else "pending")
    db.add(result)
    db.flush()
    if manual_kind == "extra_field":
        db.add(MatchResultExtraValue(match_result_id=result.id, field_key="智能", field_value="是", source="manual"))
    db.commit()
    assert client.post(f"/api/clean/tasks/{job_id}/retry").status_code == 409


def test_reclean_rejects_manual_extra_fields_before_queueing_or_deleting_outputs(db):
    _pending(db)
    client = _client(db)
    job_id = _submit(client)
    queue.execute_next_run(db)
    result = db.query(MatchResult).one()
    db.add(MatchResultExtraValue(match_result_id=result.id, field_key="智能", field_value="是", source="manual"))
    db.commit()
    response = client.post("/api/clean/tasks/upsert-monthly", json={
        "category_code": "headphone", "platform": "jd", "month": 202603, "force_reclean": True,
    })
    assert response.status_code == 400, response.text
    assert db.query(MatchResultExtraValue).one().field_value == "是"
    assert db.get(CleanJobRecord, job_id).status == "reviewing"


def test_mysql_progress_path_uses_its_own_session_not_the_output_transaction(db):
    db.add(CleanJobRecord(id=1, status="cleaning"))
    db.flush()
    run = CleanTaskRun(clean_job_id=1, state="running", worker_token="owned")
    db.add(run)
    db.commit()
    run_id = run.id
    opened = []
    def factory():
        session = Session(db.get_bind())
        opened.append(session)
        return session
    output_transaction = SimpleNamespace(get_bind=lambda: SimpleNamespace(dialect=SimpleNamespace(name="mysql")))
    writer = queue.CleanProgressWriter(output_transaction, run_id, "owned", session_factory=factory)
    writer("清洗中", 1000, 2000)
    db.expire_all()
    assert len(opened) == 1
    assert db.get(CleanTaskRun, run_id).processed == 1000


def test_finalizing_job_remains_locked_until_queue_execution_is_finished(db):
    db.add(CleanJobRecord(id=1, status="reviewing"))
    db.flush()
    db.add(CleanTaskRun(clean_job_id=1, state="running"))
    db.commit()
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as error:
        queue.ensure_clean_job_idle(db, 1)
    assert error.value.status_code == 409


def test_failed_old_owner_cannot_overwrite_a_new_queue_attempt(db):
    _pending(db)
    job_id = _submit(_client(db))
    def interrupted(db, job, stage_progress_cb):
        run = db.query(CleanTaskRun).filter_by(clean_job_id=job.id).one()
        run.state, run.worker_token = "queued", None
        db.commit()
        raise RuntimeError("old owner failed")
    queue.execute_next_run(db, executor=interrupted)
    db.expire_all()
    assert db.get(CleanJobRecord, job_id).status == "queued"
    assert db.query(CleanTaskRun).one().state == "queued"


def test_independent_worker_consumes_persisted_queue_and_recovers_after_restart(tmp_path):
    database = tmp_path / "worker.db"
    url = f"sqlite:///{database}"
    bind = create_engine(url)
    Base.metadata.create_all(bind)
    with Session(bind) as db:
        _pending(db)
        _pending(db, month=202604, item_id="456")
        client = _client(db)
        first, second = _submit(client), _submit(client, month=202604)
        db.add(CleanJobRecord(id=999, status="matching"))
        db.flush()
        db.add(CleanTaskRun(clean_job_id=999, state="running", stage="型号匹配中"))
        db.commit()
    # The API's session is closed before the independent worker even starts.
    env = dict(os.environ, DATABASE_URL=url,
               ANALYTICS_DATABASE_URL=f"sqlite:///{tmp_path / 'analytics.db'}",
               UPLOAD_DIR=str(tmp_path / "uploads"), EXPORT_DIR=str(tmp_path / "exports"),
               PYTHONPATH=str(Path(__file__).resolve().parents[1]))

    def consume(ids, name):
        log_path = tmp_path / f"{name}.log"
        with log_path.open("w") as log:
            process = subprocess.Popen([sys.executable, "-m", "app.workers.clean_worker"],
                                       env=env, stdout=log, stderr=subprocess.STDOUT)
            try:
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    with Session(bind) as reader:
                        states = dict(reader.query(CleanJobRecord.id, CleanJobRecord.status).filter(CleanJobRecord.id.in_(ids)).all())
                    if states and all(states.get(job_id) == "reviewing" for job_id in ids):
                        break
                    if process.poll() is not None:
                        pytest.fail(log_path.read_text())
                    time.sleep(0.05)
                else:
                    pytest.fail(log_path.read_text())
            finally:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            assert process.returncode == 0, log_path.read_text()

    consume([first, second], "first-worker")
    with Session(bind) as db:
        assert db.get(CleanJobRecord, 999).status == "failed"
        assert db.query(CleanedDataRecord).count() == 2
        _pending(db, month=202605, item_id="789")
        third = _submit(_client(db), month=202605)
    consume([third], "restarted-worker")
    with Session(bind) as db:
        assert db.query(CleanedDataRecord).count() == 3
        assert db.query(CleanTaskRun).filter_by(state="queued").count() == 0


def test_queue_schema_upgrades_from_current_production_and_downgrades_without_losing_job(tmp_path, monkeypatch):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import text
    from sqlalchemy.dialects.mysql import dialect
    from sqlalchemy.schema import CreateTable
    assert "queued_at DATETIME(6)" in str(CreateTable(CleanTaskRun.__table__).compile(dialect=dialect()))
    database = tmp_path / "migration.db"
    url = f"sqlite:///{database}"
    bind = create_engine(url)
    with bind.begin() as conn:
        conn.execute(text("CREATE TABLE clean_jobs (id INTEGER PRIMARY KEY)"))
        conn.execute(text("INSERT INTO clean_jobs (id) VALUES (7)"))
        conn.execute(text("CREATE TABLE upload_files (id INTEGER PRIMARY KEY, filename VARCHAR(255) NOT NULL)"))
        conn.execute(text("CREATE TABLE item_url_mappings (id INTEGER PRIMARY KEY, item_id VARCHAR(100))"))
    monkeypatch.setattr(settings, "DATABASE_URL", url)
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "alembic"))
    command.stamp(config, "p74a1b2c3d4e5")
    command.upgrade(config, "head")
    assert {column["name"] for column in inspect(bind).get_columns("clean_jobs")} >= {"id", "progress", "progress_stage", "error_msg"}
    assert "clean_task_runs" in inspect(bind).get_table_names()
    assert any(index["name"] == "idx_clean_runs_queue" for index in inspect(bind).get_indexes("clean_task_runs"))
    command.downgrade(config, "p74a1b2c3d4e5")
    assert "clean_task_runs" not in inspect(bind).get_table_names()
    with bind.connect() as conn:
        assert conn.execute(text("SELECT id FROM clean_jobs")).scalar() == 7
