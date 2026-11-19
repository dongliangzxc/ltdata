"""Clean task supplement upload appends only new rows and preserves old results."""
import io
from pathlib import Path

import pytest
from openpyxl import load_workbook
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.clean import router
from app.api import clean
from app.core.config import settings
from app.core.auth_deps import get_current_user
from app.models.database import Base, get_db
from app.models.schemas import (
    Category,
    CleanJobItemRecord,
    CleanJobRecord,
    CleanedDataRecord,
    CleanDuplicateRecord,
    CleanTaskRun,
    ColumnTemplate,
    DispatchBatch,
    DispatchItem,
    MatchResult,
    MatchResultAttr,
    MatchResultExtraValue,
    ModelRecord,
    ItemUrlMapping,
    PublishJob,
    FilteredItem,
    RawDataRecord,
    UploadFileRecord,
)
from app.services import clean_task_queue as queue, matcher


@pytest.fixture(autouse=True)
def supplement_settings(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, 'CLEAN_BACKGROUND_ENABLED', True)
    monkeypatch.setattr(settings, 'UPLOAD_DIR', str(tmp_path))


class DummyUser:
    is_admin = 1
    category_permissions = []


@pytest.fixture
def client():
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
    app.dependency_overrides[get_current_user] = lambda: DummyUser()
    test_client = TestClient(app)
    test_client.Session = Session
    return test_client


def _seed_task(session):
    session.add(Category(code="laptop", name="笔记本"))
    upload = UploadFileRecord(filename="old.xlsx", platform="jd", row_count=1, status="done")
    session.add(upload)
    session.flush()
    old_raw = RawDataRecord(
        file_id=upload.id,
        country_code="CN",
        platform="jd",
        month=202609,
        item_id="old-1",
        item_name="旧数据",
        sales_qty=1,
        sales_amount=100,
        price=100,
    )
    session.add(old_raw)
    session.flush()
    job = CleanJobRecord(
        file_ids=[upload.id],
        rules={"dedup": True},
        status="reviewing",
        category_code="laptop",
        dispatch_category_code="laptop",
        platform="jd",
        source_scope={"months": [202609], "platforms": ["jd"], "file_ids": [upload.id]},
        row_in=1,
        row_out=1,
    )
    session.add(job)
    session.flush()
    session.add(CleanJobItemRecord(
        clean_job_id=job.id,
        raw_data_id=old_raw.id,
        category_code="laptop",
        platform="jd",
    ))
    session.add(CleanedDataRecord(
        clean_job_id=job.id,
        raw_data_id=old_raw.id,
        country_code="CN",
        platform="jd",
        month=202609,
        item_id="old-1",
        shop_name="旧店铺",
    ))
    session.add(MatchResult(
        clean_job_id=job.id,
        raw_data_id=old_raw.id,
        match_status="confirmed",
        matched_by="manual",
        model_id=1,
    ))
    template = ColumnTemplate(
        name="笔记本补充模板",
        module="sales",
        mapping={
            "商品ID": "item_id",
            "商品名称": "item_name",
            "销量": "sales_qty",
            "销售额": "sales_amount",
            "价格": "price",
            "月份": "month",
            "平台": "platform",
            "商品链接": "item_url",
        },
        ignore_columns=[],
        is_builtin=0,
    )
    session.add(template)
    session.commit()
    return job.id, template.id, old_raw.id


def test_supplement_appends_new_rows_and_keeps_old_results(client):
    with client.Session() as session:
        job_id, template_id, old_raw_id = _seed_task(session)

    csv_content = (
        "商品ID,商品名称,销量,销售额,价格,月份,平台\n"
        "new-1,新增数据,2,200,100,202609,jd\n"
        "old-1,旧数据,1,100,100,202609,jd\n"
    )
    res = client.post(
        f"/api/clean/tasks/{job_id}/supplement",
        files={"file": ("supplement.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")},
        data={"template_id": str(template_id)},
    )
    assert res.status_code == 200, res.text
    data = res.json()["data"]
    assert data["inserted_rows"] == 1
    assert data["duplicate_rows"] == 1
    assert data["appended_items"] == 1
    assert data["row_in"] == 2
    assert data['match_status'] == data['status'] == 'queued'

    with client.Session() as session:
        assert session.query(MatchResult).count() == 1
        assert queue.execute_next_run(session)

    with client.Session() as session:
        new_raw = session.query(RawDataRecord).filter(RawDataRecord.item_id == "new-1").one()
        assert new_raw.country_code == "CN"
        assert new_raw.platform == "jd"
        assert new_raw.month == 202609
        assert session.query(CleanJobItemRecord).filter(
            CleanJobItemRecord.clean_job_id == job_id,
            CleanJobItemRecord.raw_data_id == new_raw.id,
        ).one()
        batch = session.query(DispatchBatch).filter(DispatchBatch.file_id == new_raw.file_id).one()
        assert batch.status == "done"
        assert session.query(DispatchItem).filter(
            DispatchItem.batch_id == batch.id,
            DispatchItem.raw_data_id == new_raw.id,
            DispatchItem.category_code == "laptop",
        ).one()
        assert session.query(MatchResult).filter(
            MatchResult.clean_job_id == job_id,
            MatchResult.raw_data_id == new_raw.id,
        ).one()
        old_result = session.query(MatchResult).filter(
            MatchResult.clean_job_id == job_id,
            MatchResult.raw_data_id == old_raw_id,
        ).one()
        assert old_result.match_status == "confirmed"


def _submit(client, job_id, template_id, rows='new-1,新增数据,2,200,100,202609,jd,https://item.jd.com/new-1.html\n'):
    content = '商品ID,商品名称,销量,销售额,价格,月份,平台,商品链接\n' + rows
    return client.post(f'/api/clean/tasks/{job_id}/supplement',
        files={'file': ('supplement.csv', content.encode('utf-8'), 'text/csv')},
        data={'template_id': str(template_id)})


def test_supplement_template_download_contains_fillable_examples_and_instructions(client):
    from urllib.parse import unquote

    response = client.get('/api/clean/supplement-template')
    assert response.status_code == 200
    assert 'spreadsheetml.sheet' in response.headers['content-type']
    assert '补充数据上传示例.xlsx' in unquote(response.headers['content-disposition'])
    workbook = load_workbook(io.BytesIO(response.content))
    assert workbook.sheetnames == ['补充数据', '填写说明']
    data = workbook.worksheets[0]
    assert list(next(data.values)) == [
        'item_id', 'item_name', 'sales_qty', 'sales_amount', 'price', 'brand_raw', 'shop_name', 'item_url',
    ]
    assert data.max_row == 3
    assert data['A2'].data_type == 's' and data['A2'].number_format == '@'
    assert data['C2'].data_type == data['D2'].data_type == data['E2'].data_type == 'n'
    assert data.freeze_panes == 'A2'
    notes = list(workbook['填写说明'].values)
    assert {row[0] for row in notes if row[2] == '是'} == clean.SUPPLEMENT_REQUIRED_FIELDS
    assert any(row[0] == '任务范围' and '品类、平台、月份' in row[3] for row in notes)
    assert any(row[0] == '使用方法' and '替换' in row[3] for row in notes)


def test_supplement_template_has_chinese_comments_on_every_header(client):
    response = client.get('/api/clean/supplement-template')
    assert response.status_code == 200
    workbook = load_workbook(io.BytesIO(response.content))
    data = workbook['补充数据']
    descriptions = {row[0]: row for row in workbook['填写说明'].iter_rows(min_row=2, max_row=9, values_only=True)}
    for index, header in enumerate(data[1], start=1):
        _, label, required, description = descriptions[header.value]
        assert header.comment is not None, f'{header.value} must explain its meaning without switching sheets'
        assert label in header.comment.text
        assert ('必填' if required == '是' else '选填') in header.comment.text
        assert description in header.comment.text
        assert f'示例：{data.cell(2, index).value}' in header.comment.text
        assert header.comment.author == '洛图数据平台'
    assert '总销售金额' in data['D1'].comment.text
    assert '单件商品' in data['E1'].comment.text


def test_downloaded_supplement_template_uploads_and_cleans_without_saved_mapping(client):
    with client.Session() as session:
        job_id, _, _ = _seed_task(session)
        # A similar saved mapping must not corrupt the standard example fields.
        headers = ['item_id', 'item_name', 'sales_qty', 'sales_amount', 'price', 'brand_raw', 'shop_name', 'item_url']
        from app.services.import_helper import col_fingerprint
        session.add(ColumnTemplate(
            name='旧标准列模板', module='sales', col_fingerprint=col_fingerprint(headers),
            mapping={header: '__ext__' for header in headers}, ignore_columns=[], is_builtin=0,
        ))
        session.commit()
        old = _outputs(session, job_id)
    template = client.get('/api/clean/supplement-template')
    response = client.post(
        f'/api/clean/tasks/{job_id}/supplement',
        files={'file': ('补充数据上传示例.xlsx', template.content, template.headers['content-type'])},
    )
    assert response.status_code == 200, response.text
    result = response.json()['data']
    assert result['inserted_rows'] == result['appended_items'] == 2
    assert result['duplicate_rows'] == 0
    assert result['match_status'] == 'queued'
    with client.Session() as session:
        rows = session.query(RawDataRecord).filter_by(file_id=result['file_id']).order_by(RawDataRecord.id).all()
        assert [(row.item_id, row.month, row.platform, row.source_category_code) for row in rows] == [
            ('EXAMPLE-001', 202609, 'jd', 'laptop'), ('EXAMPLE-002', 202609, 'jd', 'laptop'),
        ]
        assert float(rows[0].price) == 129 and rows[0].sales_qty == 10
        assert rows[0].brand_raw == '示例品牌' and rows[0].shop_name == '示例店铺'
        assert rows[0].item_url == 'https://example.com/items/EXAMPLE-001'
        assert queue.execute_next_run(session)
        assert session.get(CleanJobRecord, job_id).status == 'reviewing'
        assert session.query(MatchResult).filter_by(clean_job_id=job_id).count() == 3
        for key, previous in old.items():
            assert _outputs(session, job_id)[key][:len(previous)] == previous


def test_supplement_template_requires_authentication(client):
    from fastapi import HTTPException

    def unauthenticated():
        raise HTTPException(401, '请先登录')

    client.app.dependency_overrides[get_current_user] = unauthenticated
    assert client.get('/api/clean/supplement-template').status_code == 401


def _outputs(session, job_id):
    models = (CleanedDataRecord, FilteredItem, MatchResult, CleanDuplicateRecord)
    result = {model.__name__: [tuple(getattr(row, col.name) for col in model.__table__.columns)
        for row in session.query(model).filter_by(clean_job_id=job_id).order_by(model.id)] for model in models}
    for model in (MatchResultAttr, MatchResultExtraValue):
        result[model.__name__] = [tuple(getattr(row, col.name) for col in model.__table__.columns)
            for row in session.query(model).join(MatchResult).filter(MatchResult.clean_job_id == job_id).order_by(model.id)]
    return result


def test_upload_only_enqueues_and_does_not_take_global_worker_lock(client, monkeypatch):
    with client.Session() as session:
        job_id, template, _ = _seed_task(session)
        old = _outputs(session, job_id)
    with monkeypatch.context() as patch:
        patch.setattr(clean, 'run_clean', lambda *a, **k: pytest.fail('HTTP executed cleaning'))
        patch.setattr(clean, 'run_match', lambda *a, **k: pytest.fail('HTTP executed matching'))
        patch.setattr(queue, 'clean_execution_lock', lambda *a, **k: pytest.fail('Upload waited for another task'))
        response = _submit(client, job_id, template)
    assert response.status_code == 200, response.text
    with client.Session() as session:
        assert _outputs(session, job_id) == old
        run = session.query(CleanTaskRun).one()
        assert (run.mode, run.state, run.input_count) == ('incremental', 'queued', 1)
        upload = session.get(UploadFileRecord, response.json()['data']['file_id'])
        assert (Path(settings.UPLOAD_DIR) / upload.filename).is_file()


def test_supplement_batches_matching_once_and_preserves_old_manual_fields(client, monkeypatch):
    with client.Session() as session:
        job_id, template, _ = _seed_task(session)
        old_result = session.query(MatchResult).one()
        session.add(MatchResultExtraValue(match_result_id=old_result.id, field_key='智能', field_value='是', source='manual'))
        session.add(MatchResultAttr(match_result_id=old_result.id, attr_name='连接', attr_value='蓝牙'))
        session.commit()
        old = _outputs(session, job_id)
    rows = ''.join(f'new-{i},新增商品{i},1,100,100,202609,jd\n' for i in range(1005))
    response = _submit(client, job_id, template, rows)
    assert response.status_code == 200, response.text
    contexts = []
    original = matcher._load_match_context
    def context(*a, **k):
        contexts.append(1)
        return original(*a, **k)
    monkeypatch.setattr(matcher, '_load_match_context', context)
    monkeypatch.setattr(matcher, 'run_match_for_result', lambda *a, **k: pytest.fail('per-row matching'))
    with client.Session() as session:
        assert queue.execute_next_run(session)
        assert session.get(CleanJobRecord, job_id).status == 'reviewing'
        assert session.query(MatchResult).count() == 1006
        assert len(contexts) == 1
        for key, previous in old.items():
            current = _outputs(session, job_id)[key]
            assert current[:len(previous)] == previous


def test_price_failure_is_visible_atomic_and_retry_preserves_old_manual_and_published_data(client, monkeypatch):
    with client.Session() as session:
        job_id, template, _ = _seed_task(session)
        result = session.query(MatchResult).one()
        session.add(MatchResultExtraValue(match_result_id=result.id, field_key='智能', field_value='是', source='manual'))
        session.add(PublishJob(clean_job_id=job_id, status='done'))
        model = ModelRecord(brand_code='TEST', model_code='MODEL', category_code='laptop')
        session.add(model); session.flush()
        session.add(ItemUrlMapping(platform='jd', item_id='new-1', model_id=model.id))
        session.commit()
        old = _outputs(session, job_id)
    assert _submit(client, job_id, template).status_code == 200
    with client.Session() as session:
        run = session.query(CleanTaskRun).one()
        bounds = (run.snapshot_start_id, run.snapshot_end_id, run.input_count)
    audited = []
    def fail_price(db, ids, **kwargs):
        assert kwargs['commit'] is False
        audited.extend(ids)
        raise RuntimeError('价格审核失败：测试异常')
    with monkeypatch.context() as patch:
        patch.setattr(matcher, 'audit_price', fail_price)
        with client.Session() as session:
            assert queue.execute_next_run(session)
    assert audited, 'test must reach real batch price audit'
    with client.Session() as session:
        job = session.get(CleanJobRecord, job_id)
        assert job.status == 'failed' and '价格审核失败' in job.error_msg
        assert session.query(CleanTaskRun).one().state == 'failed'
        assert _outputs(session, job_id) == old
        assert session.query(CleanJobItemRecord).count() == session.query(RawDataRecord).count() == 2
        assert job.row_out == 1
    progress = client.get(f'/api/clean/jobs/progress?ids={job_id}').json()[0]
    assert progress['status'] == 'failed' and progress['can_retry']
    assert _submit(client, job_id, template).status_code == 409, 'must retry preserved scope, not upload again'
    retry = client.post(f'/api/clean/tasks/{job_id}/retry')
    assert retry.status_code == 200, retry.text
    def audit(db, ids, **kwargs):
        assert kwargs['commit'] is False
        assert len(ids) == 1
        return {'audited': 1}
    monkeypatch.setattr(matcher, 'audit_price', audit)
    with client.Session() as session:
        run = session.query(CleanTaskRun).one()
        assert (run.snapshot_start_id, run.snapshot_end_id, run.input_count) == bounds
        assert queue.execute_next_run(session)
        assert not queue.execute_next_run(session)
        job = session.get(CleanJobRecord, job_id)
        assert (job.status, job.error_msg, job.row_in, job.row_out) == ('reviewing', None, 2, 2)
        for key, previous in old.items():
            assert _outputs(session, job_id)[key][:len(previous)] == previous
        assert session.query(PublishJob).count() == 1
        assert session.query(MatchResult).count() == 2


@pytest.mark.parametrize('failure', ['copy', 'queue', 'move', 'commit'])
def test_enqueue_or_file_failure_rolls_back_entire_upload(client, monkeypatch, failure):
    from sqlalchemy import event
    with client.Session() as session:
        job_id, template, _ = _seed_task(session)
        old = _outputs(session, job_id)
    def fail(*a, **k):
        raise RuntimeError('controlled submission failure')
    def fail_commit(session):
        if session.query(CleanTaskRun).count():
            fail()
    def fail_copy(source, target):
        target.write(b'partial upload')
        fail()
    with monkeypatch.context() as patch:
        if failure == 'copy': patch.setattr(clean.shutil, 'copyfileobj', fail_copy)
        elif failure == 'queue': patch.setattr(clean, 'enqueue_clean_job', fail)
        elif failure == 'move': patch.setattr(clean.shutil, 'move', fail)
        else: event.listen(client.Session, 'before_commit', fail_commit)
        try: response = _submit(client, job_id, template)
        finally:
            if failure == 'commit': event.remove(client.Session, 'before_commit', fail_commit)
    assert response.status_code == 500, response.text
    with client.Session() as session:
        assert session.query(RawDataRecord).count() == session.query(UploadFileRecord).count() == 1
        assert session.query(CleanJobItemRecord).count() == 1
        assert session.query(DispatchItem).count() == session.query(DispatchBatch).count() == session.query(CleanTaskRun).count() == 0
        assert _outputs(session, job_id) == old
        assert session.get(CleanJobRecord, job_id).status == 'reviewing'
    assert not list(Path(settings.UPLOAD_DIR).glob('补充-*'))
    assert not list((Path(settings.UPLOAD_DIR) / 'tmp').glob('*'))


def test_all_duplicate_file_does_not_enqueue_or_keep_file(client):
    with client.Session() as session: job_id, template, _ = _seed_task(session)
    response = _submit(client, job_id, template, 'old-1,旧数据,1,100,100,202609,jd\n')
    assert response.status_code == 400, response.text
    with client.Session() as session:
        assert session.query(CleanTaskRun).count() == 0
        assert session.query(UploadFileRecord).count() == 1
    assert not list(Path(settings.UPLOAD_DIR).glob('补充-*'))


def test_synchronous_compatibility_mode_uses_strict_batch_matching(client, monkeypatch):
    monkeypatch.setattr(settings, 'CLEAN_BACKGROUND_ENABLED', False)
    with client.Session() as session: job_id, template, _ = _seed_task(session)
    calls = []
    original = clean.run_match
    def match(*a, **k):
        assert k['commit'] is False and k['strict_audit'] is True
        assert k['raw_data_ids'] is not None
        calls.append(1)
        return original(*a, **k)
    monkeypatch.setattr(clean, 'run_match', match)
    response = _submit(client, job_id, template)
    assert response.status_code == 200, response.text
    assert response.json()['data']['match_status'] == 'done' and len(calls) == 1
    with client.Session() as session:
        assert session.query(CleanTaskRun).count() == 0
        assert session.query(MatchResult).count() == 2


def test_synchronous_price_failure_does_not_report_success_or_commit_upload(client, monkeypatch):
    monkeypatch.setattr(settings, 'CLEAN_BACKGROUND_ENABLED', False)
    with client.Session() as session:
        job_id, template, _ = _seed_task(session)
        old = _outputs(session, job_id)
        model = ModelRecord(brand_code='TEST', model_code='MODEL', category_code='laptop')
        session.add(model); session.flush()
        session.add(ItemUrlMapping(platform='jd', item_id='new-1', model_id=model.id)); session.commit()
    def fail(*a, **k): raise RuntimeError('price audit failed')
    monkeypatch.setattr(matcher, 'audit_price', fail)
    response = _submit(client, job_id, template)
    assert response.status_code == 500 and 'price audit failed' in response.text
    with client.Session() as session:
        assert _outputs(session, job_id) == old
        assert session.query(RawDataRecord).count() == session.query(UploadFileRecord).count() == 1
        assert session.query(CleanJobItemRecord).count() == 1
    assert not list(Path(settings.UPLOAD_DIR).glob('补充-*'))


@pytest.mark.parametrize('missing', ['snapshot', 'source'])
def test_missing_supplement_range_fails_without_reprocessing_old_data(client, missing):
    with client.Session() as session:
        job_id, template, old_raw_id = _seed_task(session)
        old = _outputs(session, job_id)
    assert _submit(client, job_id, template).status_code == 200
    with client.Session() as session:
        model = CleanJobItemRecord if missing == 'snapshot' else RawDataRecord
        field = model.raw_data_id if missing == 'snapshot' else model.id
        session.query(model).filter(field != old_raw_id).delete(synchronize_session=False); session.commit()
        assert queue.execute_next_run(session)
        assert session.get(CleanJobRecord, job_id).status == 'failed'
        assert '未扩大清洗范围' in session.get(CleanJobRecord, job_id).error_msg
        assert _outputs(session, job_id) == old


def test_retry_still_refuses_manual_changes_inside_new_range(client):
    with client.Session() as session: job_id, template, _ = _seed_task(session)
    assert _submit(client, job_id, template).status_code == 200
    with client.Session() as session:
        def fail(*a, **k): raise RuntimeError('failed')
        assert queue.execute_next_run(session, executor=fail)
        new_id = session.query(RawDataRecord.id).filter_by(item_id='new-1').scalar()
        session.add(MatchResult(clean_job_id=job_id, raw_data_id=new_id, matched_by='manual', match_status='confirmed'))
        session.commit()
    assert client.post(f'/api/clean/tasks/{job_id}/retry').status_code == 409


def test_file_and_scope_survive_api_close_and_independent_worker_process(tmp_path, monkeypatch):
    import os
    import subprocess
    import sys
    from tests.test_clean_task_queue import _client
    from sqlalchemy.orm import Session
    url = f'sqlite:///{tmp_path}/supplement.db'
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        job_id, template, _ = _seed_task(session)
        old = _outputs(session, job_id)
        with _client(session) as api:
            response = _submit(api, job_id, template)
            assert response.status_code == 200, response.text
    code = '''from sqlalchemy.orm import Session
from app.models.database import engine
from app.services.clean_task_queue import clean_execution_lock, execute_next_run
with clean_execution_lock(engine) as connection:
    assert connection is not None
    with Session(bind=connection) as db:
        assert execute_next_run(db)
'''
    env = os.environ.copy()
    env.update(DATABASE_URL=url, ANALYTICS_DATABASE_URL=f'sqlite:///{tmp_path}/analytics.db',
               UPLOAD_DIR=settings.UPLOAD_DIR, EXPORT_DIR=str(tmp_path / 'exports'))
    run = subprocess.run([sys.executable, '-c', code], env=env, capture_output=True, text=True, timeout=30)
    assert run.returncode == 0, run.stderr
    with Session(engine) as session:
        assert session.get(CleanJobRecord, job_id).status == 'reviewing'
        assert session.query(CleanTaskRun).one().state == 'done'
        assert session.query(MatchResult).count() == 2
        for key, previous in old.items():
            assert _outputs(session, job_id)[key][:len(previous)] == previous
        upload = session.get(UploadFileRecord, response.json()['data']['file_id'])
        assert (Path(settings.UPLOAD_DIR) / upload.filename).is_file()
    engine.dispose()
