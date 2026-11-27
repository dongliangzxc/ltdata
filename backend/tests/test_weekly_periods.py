"""Local-week acceptance through actual parsing, upload, dispatch, snapshots and publish."""
import importlib.util
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openpyxl import Workbook, load_workbook
from sqlalchemy import create_engine, text, inspect
from sqlalchemy.orm import Session

from tests.test_upload_cases import harness, finish_upload
from app.api import clean as clean_api, dispatch_api, rawdata, workbench_api
from app.core.auth_deps import get_current_user
from app.core.config import settings
from app.models.database import get_db
from app.models.schemas import (
    RawDataRecord, UploadFileRecord, UploadConfirmJob, Category, DispatchBatch,
    DispatchItem, DispatchRule, CleanJobRecord, CleanJobItemRecord, CleanedDataRecord,
)
from app.models.analytics_db import AnalyticsBase, PublishedItem
from app.services.data_period import normalize_week, inspect_upload_periods, apply_record_period
from app.services.clean_task_snapshot import get_monthly_clean_pool, upsert_monthly_task_snapshot
from app.services.data_cleaner import run_clean
from app.services.publisher import _upsert_published_items, delete_published_data


@pytest.mark.parametrize("value", [1, 2, 3, 4, 5, "1", "2", "3", "4", "5", " 3 ", 3.0])
def test_week_accepts_only_normalized_local_numbers(value):
    assert normalize_week(value, required=True) == int(float(str(value).strip()))


@pytest.mark.parametrize("value", [None, "", " ", 0, 6, -1, 2.5, True, False, [], {}, "03", "3.0", "第3周", "W03", "三", "３", "null", float("nan")])
def test_invalid_week_is_never_silently_replaced(value):
    with pytest.raises(ValueError):
        normalize_week(value, required=True)


def _xlsx(rows, headers=None):
    book = Workbook()
    book.active.append(headers or ["month", "week", "platform", "item_id", "item_name", "sales_qty", "sales_amount", "price"])
    for row in rows:
        book.active.append(row)
    stream = BytesIO()
    book.save(stream)
    return stream.getvalue()


def _upload(h, rows, **options):
    headers = ["month", "week", "platform", "item_id", "item_name", "sales_qty", "sales_amount", "price"]
    response = h.client.post("/api/upload/headers", files={"file": ("weekly.xlsx", _xlsx(rows, headers))})
    assert response.status_code == 200, response.text
    payload = dict(temp_file_id=response.json()["temp_file_id"], mapping={key: key for key in headers},
                   ignore_columns=[], country_code="CN", quality_reviewed=True, period_type="week", **options)
    return h.client.post("/api/upload/confirm", json=payload)


def test_upload_registers_thread_before_polling_can_mark_it_interrupted(harness):
    from app.api import upload as upload_api
    response = _upload(harness, [[202611, 1, "jd", "poll-race", "测试耳机", 1, 10, 10]])
    assert response.status_code == 202
    job_id = response.json()["job_id"]
    try:
        assert job_id in upload_api._upload_progress
        with harness.sessions() as db:
            job = db.get(UploadConfirmJob, job_id)
            job.status = "running"
            db.commit()
        # The upload thread is deferred by the harness; it has not published progress.
        polled = harness.client.get(f"/api/upload/confirm/jobs/{job_id}")
        assert polled.json()["status"] == "running"
        assert finish_upload(harness, response)["inserted"] == 1
    finally:
        upload_api._upload_progress.pop(job_id, None)


def test_upload_poll_rechecks_active_thread_after_database_query(monkeypatch):
    from app.api import upload as upload_api
    registry = {}
    monkeypatch.setattr(upload_api, "_upload_progress", registry)
    job = SimpleNamespace(id=98, status="running")
    class Query:
        def filter(self, *args): return self
        def all(self):
            registry[job.id] = 5
            return [job]
    db = SimpleNamespace(query=lambda *args: Query(), commit=lambda: None)
    upload_api._mark_interrupted_upload_jobs(db)
    assert job.status == "running"


def test_upload_poll_cannot_overwrite_a_job_completed_after_its_read(harness, monkeypatch):
    from app.api import upload as upload_api
    monkeypatch.setattr(upload_api, "_upload_progress", {})
    with harness.sessions() as db:
        job = UploadConfirmJob(filename="completed.xlsx", status="done", progress=100)
        db.add(job); db.commit(); job_id = job.id
        class StaleQuery:
            def filter(self, *args): return self
            def all(self): return [SimpleNamespace(id=job_id, status="running")]
        first = True
        def query(*args):
            nonlocal first
            if first:
                first = False
                return StaleQuery()
            return db.query(*args)
        upload_api._mark_interrupted_upload_jobs(SimpleNamespace(query=query, commit=db.commit))
        db.expire_all()
        assert db.get(UploadConfirmJob, job_id).status == "done"


def test_upload_month_and_five_weeks_coexist_and_deduplicate(harness):
    rows = [[202602, week, "jd", "same", "测试耳机", week, week * 10, 10] for week in [1, "2", 3.0, " 4 ", 5]]
    result = finish_upload(harness, _upload(harness, rows + rows[:1]))
    assert result["inserted"] == 5 and result["skipped"] == 1
    assert result["platform"] == "JD"
    assert finish_upload(harness, _upload(harness, rows))["inserted"] == 0
    with harness.sessions() as db:
        record = UploadFileRecord(filename="month.xlsx", status="done")
        db.add(record); db.flush()
        db.add(RawDataRecord(file_id=record.id, country_code="CN", platform="jd", month=202602, item_id="same"))
        db.commit()
        assert sorted(row.week_of_month for row in db.query(RawDataRecord)) == [0, 1, 2, 3, 4, 5]
        assert db.query(UploadFileRecord).filter_by(id=result["file_id"]).one().weeks == [1, 2, 3, 4, 5]


def test_real_upload_file_platform_selects_dispatch_rules(harness):
    result = finish_upload(harness, _upload(harness, [[202611, 1, "jd", "one", "周度验收耳机", 1, 10, 10]]))
    with harness.sessions() as db:
        db.add(Category(code="weekly_test", name="周度测试"))
        db.add(DispatchRule(category_code="weekly_test", platform="jd", field="item_name", match_type="contains", value="周度验收", is_active=1))
        db.commit()
        batch = dispatch_api.run_dispatch({"file_id": result["file_id"], "category_code": "weekly_test"}, db)
        assert batch.dispatched_rows == 1
        assert get_monthly_clean_pool(db, category_code="weekly_test", period_type="week")[0]["week_of_month"] == 1


@pytest.mark.parametrize("bad", ["第3周", "3.0", 6, 0, None, 2.5])
def test_invalid_week_blocks_even_reviewed_upload_before_job_creation(harness, bad):
    response = _upload(harness, [[202611, 1, "jd", "ok", "耳机", 1, 10, 10],
                               [202611, bad, "jd", "bad", "耳机", 1, 10, 10]])
    assert response.status_code == 422, response.text
    assert "第3行" in response.json()["detail"]
    with harness.sessions() as db:
        assert db.query(UploadConfirmJob).count() == db.query(RawDataRecord).count() == 0
    assert not harness.queued


def test_manual_week_and_column_conflict(harness):
    result = finish_upload(harness, _upload(harness, [[202611, None, "jd", "one", "耳机", 1, 10, 10]], week="3"))
    with harness.sessions() as db:
        assert db.query(RawDataRecord).one().week_of_month == 3
    assert _upload(harness, [[202611, 2, "jd", "two", "耳机", 1, 10, 10]], week=3).status_code == 422


def test_legacy_direct_upload_keeps_week_metadata_and_rejects_blank_weeks(harness):
    data = _xlsx([[202611, week, "jd", "same", "耳机", 1, 10, 10] for week in (1, 2)])
    response = harness.client.post("/api/upload", files={"file": ("legacy.xlsx", data)})
    assert response.status_code == 200, response.text
    assert response.json()["inserted"] == 2 and response.json()["weeks"] == [1, 2]
    with harness.sessions() as db:
        assert db.query(UploadFileRecord).one().period_type == "week"
    invalid = _xlsx([[202611, None, "jd", "bad", "耳机", 1, 10, 10]])
    assert harness.client.post("/api/upload", files={"file": ("bad.xlsx", invalid)}).status_code == 422
    with harness.sessions() as db:
        assert db.query(RawDataRecord).count() == 2


def _seed(db):
    db.add(Category(code="weekly_test", name="周度测试"))
    file = UploadFileRecord(filename="weekly.xlsx", period_type="week", weeks=[1, 2], platform="jd", status="done")
    db.add(file); db.flush()
    batch = DispatchBatch(file_id=file.id, status="done")
    db.add(batch); db.flush()
    rule = DispatchRule(category_code="weekly_test", field="item_name", match_type="contains", value="耳机", is_active=1)
    db.add(rule); db.flush()
    rows = []
    for week in [0, 1, 2]:
        row = RawDataRecord(file_id=file.id, country_code="CN", platform="jd", month=202611, week_of_month=week,
                            week=str(week) if week else None, item_id="same", item_name="耳机", shop_name="店铺",
                            sales_qty=10 + week, sales_amount=(10 + week) * 10, price=10)
        db.add(row); db.flush()
        db.add(DispatchItem(batch_id=batch.id, raw_data_id=row.id, category_code="weekly_test", matched_rule_id=rule.id))
        rows.append(row)
    db.commit()
    return rows, batch


def _client(db, router):
    app = FastAPI(); app.include_router(router)
    def get_session():
        yield db
    app.dependency_overrides[get_db] = get_session
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(is_admin=1, id=1)
    return TestClient(app)


def test_pool_tasks_append_and_cleaning_are_isolated_by_week(db):
    rows, batch = _seed(db)
    assert [r["week_of_month"] for r in get_monthly_clean_pool(db)] == [0]
    weekly = get_monthly_clean_pool(db, period_type="week")
    assert sorted(r["week_of_month"] for r in weekly) == [1, 2]
    ids = []
    for week in [0, 1, 2]:
        job, count, _, _ = upsert_monthly_task_snapshot(db, category_code="weekly_test", platform="jd", month=202611, week=week, rules=None)
        assert count == 1
        assert [item.raw_data_id for item in job.snapshot_items] == [rows[week].id]
        job.status = "reviewing"; ids.append(job.id)
        db.flush()
    assert len(set(ids)) == 3
    job = db.get(CleanJobRecord, ids[1])
    assert run_clean(db, job.id, [rows[0].file_id], {"dedup": True}) == 1
    assert db.query(CleanedDataRecord).filter_by(clean_job_id=job.id).one().week_of_month == 1
    legacy = CleanJobRecord(file_ids=[rows[0].file_id], rules={}, status="done")
    db.add(legacy); db.flush()
    assert run_clean(db, legacy.id, [rows[0].file_id], {"dedup": True}) == 3
    assert sorted(r.week_of_month for r in db.query(CleanedDataRecord).filter_by(clean_job_id=legacy.id)) == [0, 1, 2]


def test_period_queries_coverage_and_export_keep_weeks(db):
    rows, _ = _seed(db)
    client = _client(db, dispatch_api.router)
    monthly = client.get("/api/dispatch/rule-coverage", params={"months": 202611})
    weekly = client.get("/api/dispatch/rule-coverage", params={"months": 202611, "period_type": "week"})
    assert monthly.status_code == weekly.status_code == 200
    assert {r["week_of_month"] for r in weekly.json()["rows"]} == {1, 2}
    assert sum(r["assigned_count"] for r in monthly.json()["rows"]) == 1
    query = dispatch_api._latest_dispatch_export_query(db, "weekly_test", "jd", [202611], period_type="week", weeks=[2])
    buffer = BytesIO(); dispatch_api._write_dispatch_export_query(query, 1, buffer)
    sheet = load_workbook(BytesIO(buffer.getvalue())).active
    values = list(sheet.values)
    assert values[1][values[0].index("周次")] == 2
    raw_client = _client(db, rawdata.router)
    result = raw_client.get("/api/rawdata", params={"period_type": "week", "week": "2"})
    assert result.status_code == 200, result.text
    assert result.json()["total"] == 1 and result.json()["items"][0]["week_of_month"] == 2
    monthly_export = raw_client.get("/api/rawdata/export", params={"period_type": "month", "month": 202611})
    assert monthly_export.status_code == 200, monthly_export.text
    monthly_rows = list(load_workbook(BytesIO(monthly_export.content)).active.values)
    assert monthly_rows[1][monthly_rows[0].index("周次")] is None, "internal monthly sentinel must not leak into exported week input"


def test_weekly_completion_and_append_never_take_another_week(db):
    rows, _ = _seed(db)
    job, _, _, _ = upsert_monthly_task_snapshot(db, category_code="weekly_test", platform="jd", month=202611, week=1, rules=None)
    job.status = "reviewing"; db.commit()
    original_id = job.id
    file = UploadFileRecord(filename="new.xlsx", status="done")
    db.add(file); db.flush()
    batch = DispatchBatch(file_id=file.id, status="done")
    db.add(batch); db.flush()
    for week in (1, 2):
        raw = RawDataRecord(file_id=file.id, month=202611, week_of_month=week, platform="jd", item_id="new", item_name="耳机")
        db.add(raw); db.flush()
        db.add(DispatchItem(batch_id=batch.id, raw_data_id=raw.id, category_code="weekly_test"))
    db.commit()
    client = _client(db, clean_api.router)
    response = client.get(f"/api/clean/tasks/{job.id}/completion")
    assert response.status_code == 200, response.text
    assert response.json()["new_items"] == 1
    same, count, action, ids = upsert_monthly_task_snapshot(db, category_code="weekly_test", platform="jd", month=202611, week=1, rules=None, incremental_append=True)
    assert same.id == original_id and count == 1 and action == "appended" and len(ids) == 1
    assert same.source_scope["period_key"] == "W:202611:01"
    assert {r.week_of_month for r in db.query(RawDataRecord).join(CleanJobItemRecord, CleanJobItemRecord.raw_data_id == RawDataRecord.id).filter(CleanJobItemRecord.clean_job_id == same.id)} == {1}


def test_supplement_inherits_week_and_conflicts_roll_back(db, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "CLEAN_BACKGROUND_ENABLED", True)
    _seed(db)
    job, _, _, _ = upsert_monthly_task_snapshot(db, category_code="weekly_test", platform="jd", month=202611, week=2, rules=None)
    job.status = "reviewing"; db.commit()
    client = _client(db, clean_api.router)
    conflict = _xlsx([[202611, 1, "jd", "bad", "耳机", 1, 10, 10]])
    response = client.post(f"/api/clean/tasks/{job.id}/supplement", files={"file": ("conflict.xlsx", conflict)})
    assert response.status_code == 422, response.text
    assert db.query(RawDataRecord).count() == 3
    assert db.query(UploadFileRecord).count() == 1
    data = _xlsx([["added", "耳机", 5, 50, 10]], ["item_id", "item_name", "sales_qty", "sales_amount", "price"])
    response = client.post(f"/api/clean/tasks/{job.id}/supplement", files={"file": ("supplement.xlsx", data)})
    assert response.status_code == 200, response.text
    assert response.json()["data"]["inserted_rows"] == 1
    assert db.query(RawDataRecord).filter_by(item_id="added").one().week_of_month == 2
    db.refresh(job)
    assert job.source_scope["period_key"] == "W:202611:02"


def test_progress_details_are_split_by_local_week(db):
    from app.api.stats_api import _progress_stats
    _seed(db)
    details = _progress_stats(db)["categories"]
    assert {r["week_of_month"] for r in details} == {0, 1, 2}
    assert all(r["dispatched"] == 1 for r in details)


def test_publish_same_sku_weeks_survive_republication_and_deletion():
    engine = create_engine("sqlite:///:memory:"); AnalyticsBase.metadata.create_all(engine)
    with Session(engine) as db:
        items = [dict(platform="jd", item_id="sku", month=202611, week_of_month=w,
                      publish_job_id=1, clean_job_id=w + 10, match_result_id=w + 100, sales_qty=w + 1) for w in (0, 1, 2)]
        _upsert_published_items(db, items); db.commit()
        _upsert_published_items(db, [{**items[1], "sales_qty": 99}]); db.commit()
        assert {r.week_of_month: r.sales_qty for r in db.query(PublishedItem)} == {0: 1, 1: 99, 2: 3}
        assert workbench_api._build_query(db, {}).count() == 1
        assert workbench_api._build_query(db, {"period_type": "week", "week": "2"}).one().sales_qty == 3
        delete_published_data(db, 11); db.commit()
        assert {r.week_of_month for r in db.query(PublishedItem)} == {0, 2}
    engine.dispose()


@pytest.mark.parametrize("duplicate_table", ["raw_data", "published_items"])
def test_migration_preserves_legacy_raw_duplicates_but_blocks_published_duplicates(duplicate_table):
    path = Path(__file__).resolve().parents[1] / "alembic/versions/p82a1b2c3d4e5_weekly_periods.py"
    spec = importlib.util.spec_from_file_location("weekly_legacy_duplicates", path)
    migration = importlib.util.module_from_spec(spec); spec.loader.exec_module(migration)
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        for statement in [
            "CREATE TABLE raw_data(id INTEGER PRIMARY KEY, country_code TEXT, item_id TEXT, month INTEGER, platform TEXT, week TEXT)",
            "CREATE INDEX idx_raw_dedup_lookup ON raw_data(country_code,item_id,month,platform)",
            "CREATE INDEX idx_raw_data_month_platform ON raw_data(month,platform)",
            "CREATE TABLE cleaned_data(id INTEGER PRIMARY KEY, week TEXT)",
            "CREATE TABLE clean_jobs(id INTEGER PRIMARY KEY)",
            "CREATE TABLE upload_files(id INTEGER PRIMARY KEY)",
            "CREATE TABLE export_jobs(id INTEGER PRIMARY KEY)",
            "CREATE TABLE published_items(id INTEGER PRIMARY KEY, platform TEXT, item_id TEXT, month INTEGER)",
        ]:
            connection.execute(text(statement))
        for row_id in (42, 43):
            connection.execute(text(f"INSERT INTO {duplicate_table}(id,item_id,month,platform) VALUES(:id,'legacy',202611,'jd')"), {"id": row_id})
        if duplicate_table == "raw_data":
            connection.execute(text("UPDATE raw_data SET country_code='CN',week='W21'"))
        migration.op = Operations(MigrationContext.configure(connection))
        if duplicate_table == "published_items":
            with pytest.raises(RuntimeError, match="published_items存在"):
                migration.upgrade()
            assert "week_of_month" not in {c["name"] for c in inspect(connection).get_columns("raw_data")}
        else:
            migration.upgrade(); migration.upgrade()
            assert connection.execute(text("SELECT id,week,week_of_month FROM raw_data ORDER BY id")).all() == [(42, "W21", 0), (43, "W21", 0)]
            assert not inspect(connection).get_unique_constraints("raw_data")
            assert next(i for i in inspect(connection).get_indexes("raw_data") if i["name"] == "idx_raw_dedup_lookup")["column_names"][-1] == "week_of_month"
            migration.downgrade()
            assert connection.execute(text("SELECT id,week FROM raw_data ORDER BY id")).all() == [(42, "W21"), (43, "W21")]
            assert not inspect(connection).get_unique_constraints("raw_data")
    engine.dispose()


def test_full_publication_keeps_each_weeks_specs_and_manual_attributes(db, monkeypatch):
    from app.models.schemas import ModelRecord, ModelSpec, MatchResult, MatchResultAttr
    from app.models.analytics_db import PublishedItemSpec
    from app.services import publisher
    engine = create_engine("sqlite:///:memory:"); AnalyticsBase.metadata.create_all(engine)
    monkeypatch.setattr(publisher, "_ensure_analytics_tables", lambda: None)
    file = UploadFileRecord(filename="publish.xlsx", status="done")
    model = ModelRecord(brand_code="WEEK", model_code="TEST", category_code="weekly_test")
    db.add_all([file, model]); db.flush()
    db.add(ModelSpec(model_id=model.id, spec_name="类型", spec_value="基础"))
    jobs = []
    for week in (1, 2):
        job = CleanJobRecord(file_ids=[file.id], status="done", week_of_month=week)
        raw = RawDataRecord(file_id=file.id, platform="jd", month=202611, week_of_month=week,
                            item_id="same", item_name="耳机", sales_qty=week, sales_amount=week * 10, price=10)
        db.add_all([job, raw]); db.flush()
        match = MatchResult(clean_job_id=job.id, raw_data_id=raw.id, model_id=model.id,
                            match_status="confirmed", matched_by="manual", is_disabled=0)
        db.add(match); db.flush()
        db.add(MatchResultAttr(match_result_id=match.id, attr_name="类型", attr_value=f"第{week}周确认"))
        jobs.append(job.id)
    db.commit()
    with Session(engine) as analytics:
        for job_id in jobs:
            assert publisher.run_publish(db, analytics, job_id)["published_count"] == 1
        def specs():
            return {item.week_of_month: value for item, value in analytics.query(PublishedItem, PublishedItemSpec.spec_value).join(PublishedItemSpec, PublishedItemSpec.published_item_id == PublishedItem.id)}
        assert specs() == {1: "第1周确认", 2: "第2周确认"}
        publisher.run_publish(db, analytics, jobs[0])
        assert specs() == {1: "第1周确认", 2: "第2周确认"}
    engine.dispose()


def test_mysql_migration_generates_local_week_unique_constraints(monkeypatch):
    path = Path(__file__).resolve().parents[1] / "alembic/versions/p82a1b2c3d4e5_weekly_periods.py"
    spec = importlib.util.spec_from_file_location("weekly_mysql_migration", path)
    migration = importlib.util.module_from_spec(spec); spec.loader.exec_module(migration)
    from io import StringIO
    output = StringIO()
    operations = Operations(MigrationContext.configure(dialect_name="mysql", opts={"as_sql": True, "output_buffer": output}))
    monkeypatch.setattr(migration, "op", operations)
    monkeypatch.setattr(migration, "_analytics_schema", lambda: "weekly_analytics")
    monkeypatch.setattr(migration.sa, "inspect", lambda bind: SimpleNamespace(get_columns=lambda *a, **kw: [], has_table=lambda *a, **kw: True, get_indexes=lambda *a, **kw: [], get_unique_constraints=lambda table, **kw: [{"name": "uq_raw_dedup" if table == "raw_data" else "uq_published_item", "column_names": []}]))
    migration.upgrade()
    sql = output.getvalue()
    assert "ADD COLUMN week_of_month SMALLINT NOT NULL DEFAULT '0'" in sql
    assert "UNIQUE (country_code, item_id, month, platform, week_of_month)" in sql
    assert "ALTER TABLE weekly_analytics.published_items" in sql
    assert "UNIQUE (platform, item_id, month, week_of_month)" in sql


def test_migration_retains_legacy_week_and_refuses_lossy_downgrade():
    path = Path(__file__).resolve().parents[1] / "alembic/versions/p82a1b2c3d4e5_weekly_periods.py"
    spec = importlib.util.spec_from_file_location("weekly_migration", path)
    migration = importlib.util.module_from_spec(spec); spec.loader.exec_module(migration)
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        for statement in [
            "CREATE TABLE raw_data(id INTEGER PRIMARY KEY, country_code TEXT, item_id TEXT, month INTEGER, platform TEXT, week TEXT, CONSTRAINT uq_raw_dedup UNIQUE(country_code,item_id,month,platform))",
            "CREATE INDEX idx_raw_dedup_lookup ON raw_data(country_code,item_id,month,platform)",
            "CREATE INDEX idx_raw_data_month_platform ON raw_data(month,platform)",
            "CREATE TABLE cleaned_data(id INTEGER PRIMARY KEY, week TEXT)",
            "CREATE TABLE clean_jobs(id INTEGER PRIMARY KEY)",
            "CREATE TABLE upload_files(id INTEGER PRIMARY KEY)",
            "CREATE TABLE export_jobs(id INTEGER PRIMARY KEY)",
            "CREATE TABLE published_items(id INTEGER PRIMARY KEY, platform TEXT, item_id TEXT, month INTEGER, CONSTRAINT uq_published_item UNIQUE(platform,item_id,month))",
            "INSERT INTO raw_data VALUES(42, 'CN', 'sku', 202611, 'jd', 'W21')",
        ]:
            connection.execute(text(statement))
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        assert connection.execute(text("SELECT id, week, week_of_month FROM raw_data")).one() == (42, "W21", 0)
        connection.execute(text("INSERT INTO raw_data(id,country_code,item_id,month,platform,week_of_month) VALUES(43,'CN','sku',202611,'jd',2)"))
        with pytest.raises(RuntimeError, match="已有周度数据"):
            migration.downgrade()
        connection.execute(text("DELETE FROM raw_data WHERE id=43"))
        migration.downgrade()
        assert "week_of_month" not in {column["name"] for column in inspect(connection).get_columns("raw_data")}
        assert connection.execute(text("SELECT id, week FROM raw_data")).one() == (42, "W21")
        # Initial SQL installations may lack the published unique constraint.
        with migration.op.batch_alter_table("published_items") as batch:
            batch.drop_constraint("uq_published_item", type_="unique")
        migration.upgrade()
        migration.upgrade()  # Safe resume after partially completed MySQL DDL.
        assert inspect(connection).get_unique_constraints("published_items")[0]["column_names"] == ["platform", "item_id", "month", "week_of_month"]
    engine.dispose()
