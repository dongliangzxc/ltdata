"""Incremental append contracts: bounded work, old outputs, atomic retry and restart."""
import os
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import Session

from app.api import clean
from app.core.config import settings
from app.models.database import Base
from app.models.schemas import (
    Category, CleanedDataRecord, CleanJobItemRecord, CleanJobRecord, CleanTaskRun,
    DispatchBatch, DispatchItem, FilteredItem, InterventionRule, ItemUrlMapping,
    MatchResult, MatchResultAttr, MatchResultCandidate, MatchResultExtraValue,
    ModelRecord, PublishJob, RawDataRecord, UploadFileRecord,
)
from app.services import clean_task_queue as queue, matcher
from tests.test_clean_task_queue import _client, _pending, _submit


@pytest.fixture(autouse=True)
def background(monkeypatch):
    monkeypatch.setattr(settings, 'CLEAN_BACKGROUND_ENABLED', True)
    def audit(db, ids, commit=True, progress_cb=None):
        if progress_cb:
            progress_cb(len(ids), len(ids))
        return {'audited': len(ids)}
    monkeypatch.setattr(matcher, 'audit_price', audit)


def _add(db, specs, category='headphone'):
    upload = UploadFileRecord(filename='increment.xlsx', platform='jd', status='done')
    db.add(upload)
    db.flush()
    batch = DispatchBatch(file_id=upload.id, status='done')
    db.add(batch)
    db.flush()
    rows = [RawDataRecord(file_id=upload.id, platform='jd', month=202603,
                          item_id=item_id, item_name=name, shop_name='官方店',
                          item_url=f'https://item.jd.com/{item_id}.html' if item_id else None)
            for item_id, name in specs]
    db.add_all(rows)
    db.flush()
    ids = [row.id for row in rows]
    db.add_all([DispatchItem(batch_id=batch.id, raw_data_id=raw_id, category_code=category) for raw_id in ids])
    db.commit()
    return ids


def _base(db, *, rules=None):
    raw_id = _pending(db, item_id='1000')
    client = _client(db)
    job_id = _submit(client, **({'rules': rules} if rules is not None else {}))
    assert queue.execute_next_run(db)
    db.expire_all()
    assert db.get(CleanJobRecord, job_id).status == 'reviewing'
    return client, job_id, raw_id


def _outputs(db, job_id, raw_id=None):
    result = {}
    for model in (CleanedDataRecord, FilteredItem, MatchResult):
        query = db.query(model).filter_by(clean_job_id=job_id)
        if raw_id is not None:
            query = query.filter_by(raw_data_id=raw_id)
        result[model.__name__] = [tuple(getattr(row, column.name) for column in model.__table__.columns)
                                  for row in query.order_by(model.id)]
    return result


def _append(client):
    response = client.post('/api/clean/tasks/upsert-monthly', json={
        'category_code': 'headphone', 'platform': 'jd', 'month': 202603,
    })
    assert response.status_code == 200, response.text
    return response.json()


def test_append_persists_only_new_scope_and_batches_matching_context_once(db, monkeypatch):
    client, job_id, old_raw = _base(db)
    old = _outputs(db, job_id)
    new_ids = _add(db, [(str(10000+i), f'新增商品{i}') for i in range(1005)])
    submitted = _append(client)
    assert (submitted['match_status'], submitted['snapshot_count']) == ('queued', 1005)
    run = db.query(CleanTaskRun).filter_by(clean_job_id=job_id).one()
    assert (run.mode, run.input_count, run.total) == ('incremental', 1005, 1005)
    assert _outputs(db, job_id) == old
    scopes, contexts = [], []
    original, load = clean.run_clean, matcher._load_match_context
    def cleaning(*args, **kwargs):
        assert kwargs['commit'] is False
        scopes.extend(raw_id for raw_id, in db.execute(kwargs['raw_data_ids']))
        return original(*args, **kwargs)
    def context(*args, **kwargs):
        contexts.append(1)
        return load(*args, **kwargs)
    monkeypatch.setattr(clean, 'run_clean', cleaning)
    monkeypatch.setattr(matcher, '_load_match_context', context)
    monkeypatch.setattr(clean, '_clear_clean_job_outputs', lambda *a: pytest.fail('append cleared entire task'))
    assert queue.execute_next_run(db)
    db.expire_all()
    assert set(scopes) == set(new_ids) and old_raw not in scopes
    assert len(contexts) == 1
    assert _outputs(db, job_id, old_raw) == old
    job = db.get(CleanJobRecord, job_id)
    assert (job.status, job.row_in, job.row_out, job.row_filtered) == ('reviewing', 1006, 1006, 0)
    progress = client.get(f'/api/clean/jobs/progress?ids={job_id}').json()[0]
    listed = client.get('/api/clean/jobs', params={'category_code': 'headphone'}).json()[0]
    assert (progress['execution_mode'], progress['execution_input_count'], progress['progress_total']) == ('incremental', 1005, 1005)
    assert listed['execution_mode'] == 'incremental' and listed['row_out'] == 1006
    assert listed['updated_at'] == progress['updated_at'], 'timestamps must use the same timezone for frontend freshness checks'


@pytest.mark.parametrize('dedup,expected', [(True, 4), (False, 6)])
def test_incremental_filtering_cross_batch_dedup_and_missing_ids(db, dedup, expected):
    client, job_id, old_raw = _base(db, rules={'dedup': dedup})
    db.add(InterventionRule(category_code='headphone', name='过滤测试', action='filter',
                            conditions={'item_name_contains_any': ['blocked']}, is_active=1))
    db.commit()
    new = _add(db, [('1000','旧商品重复'), (None,'空ID甲'), (None,'空ID乙'),
                    ('2000','新增甲'), ('2000','新增重复'), ('3000','blocked')])
    _append(client)
    assert queue.execute_next_run(db)
    job = db.get(CleanJobRecord, job_id)
    assert (job.row_in, job.row_out, job.row_filtered) == (7, expected, 1)
    retained = {row.raw_data_id for row in db.query(CleanedDataRecord).filter_by(clean_job_id=job_id)}
    assert {old_raw, new[1], new[2], new[3]} <= retained
    assert (new[0] in retained) is (not dedup)
    assert (new[4] in retained) is (not dedup)
    assert db.query(FilteredItem).filter_by(clean_job_id=job_id).one().raw_data_id == new[5]


@pytest.mark.parametrize('kind', ['duplicate', 'filtered'])
def test_empty_cleaned_increment_does_not_rematch_old_data(db, monkeypatch, kind):
    client, job_id, old_raw = _base(db)
    old = _outputs(db, job_id)
    if kind == 'filtered':
        db.add(InterventionRule(category_code='headphone', name='过滤', action='filter',
                                conditions={'item_name_contains_any':['blocked']}, is_active=1))
        db.commit()
    _add(db, [('1000' if kind == 'duplicate' else '2000', 'blocked')])
    _append(client)
    monkeypatch.setattr(matcher, '_load_match_context', lambda *a, **k: pytest.fail('no new cleaned rows must not load match context'))
    assert queue.execute_next_run(db)
    assert db.get(CleanJobRecord, job_id).status == 'reviewing'
    assert _outputs(db, job_id, old_raw) == old
    assert db.query(CleanedDataRecord).filter_by(clean_job_id=job_id).count() == 1


def test_no_new_data_does_not_enqueue_or_change_old_run(db):
    client, job_id, _ = _base(db)
    run = db.query(CleanTaskRun).filter_by(clean_job_id=job_id).one()
    before = (run.state, run.worker_token, run.queued_at, run.finished_at, _outputs(db, job_id))
    result = _append(client)
    assert (result['match_status'], result['snapshot_count']) == ('unchanged', 0)
    db.refresh(run)
    assert (run.state, run.worker_token, run.queued_at, run.finished_at, _outputs(db, job_id)) == before
    assert not queue.execute_next_run(db)


def test_queued_scope_does_not_take_later_pending_data(db):
    client, job_id, old_raw = _base(db)
    first = _add(db, [('2000','第一批')])
    _append(client)
    later = _add(db, [('3000','稍后新增')])
    assert queue.execute_next_run(db)
    assert {r.raw_data_id for r in db.query(CleanedDataRecord).filter_by(clean_job_id=job_id)} == {old_raw, *first}
    assert _append(client)['snapshot_count'] == 1
    assert queue.execute_next_run(db)
    assert db.query(CleanedDataRecord).filter_by(clean_job_id=job_id, raw_data_id=later[0]).count() == 1


@pytest.mark.parametrize('stage', ['clean', 'match', 'attributes', 'price', 'commit'])
def test_failure_rolls_back_all_new_outputs_and_retry_keeps_original_scope(db, monkeypatch, stage):
    client, job_id, old_raw = _base(db)
    old = _outputs(db, job_id)
    new_raw = _add(db, [('2000','新品 MODEL')])[0]
    model = ModelRecord(brand_code='TEST', model_code='MODEL', category_code='headphone')
    db.add(model)
    db.flush()
    db.add(ItemUrlMapping(platform='jd', item_id='2000', model_id=model.id))
    db.commit()
    _append(client)
    run = db.query(CleanTaskRun).filter_by(clean_job_id=job_id).one()
    scope = (run.mode, run.snapshot_start_id, run.snapshot_end_id, run.input_count)
    commits = []
    def fail_commit(session):
        if any(isinstance(row, CleanTaskRun) and row.state == 'done' for row in session.dirty) and not commits:
            commits.append(1)
            raise RuntimeError('模拟最终提交失败')
    with monkeypatch.context() as patch:
        if stage == 'commit':
            event.listen(db, 'before_commit', fail_commit)
        else:
            module, name = {'clean':(clean,'run_clean'), 'match':(clean,'run_match'),
                             'attributes':(matcher,'run_attribute_matching'), 'price':(matcher,'audit_price')}[stage]
            original = getattr(module, name)
            def fail(*args, **kwargs):
                assert kwargs.get('commit') is False
                value = original(*args, **kwargs)
                db.flush()
                raise RuntimeError('模拟增量失败')
            patch.setattr(module, name, fail)
        try:
            assert queue.execute_next_run(db)
        finally:
            if stage == 'commit': event.remove(db, 'before_commit', fail_commit)
    db.expire_all()
    assert db.get(CleanJobRecord, job_id).status == 'failed'
    assert _outputs(db, job_id) == old
    assert db.query(CleanJobItemRecord).filter_by(clean_job_id=job_id).count() == 2
    assert client.post(f'/api/clean/tasks/{job_id}/retry').status_code == 200
    db.refresh(run)
    assert (run.mode, run.snapshot_start_id, run.snapshot_end_id, run.input_count) == scope
    assert queue.execute_next_run(db)
    db.expire_all()
    assert db.get(CleanJobRecord, job_id).status == 'reviewing'
    assert _outputs(db, job_id, old_raw) == old
    assert db.query(MatchResult).filter_by(clean_job_id=job_id,raw_data_id=new_raw).count() == 1
    assert client.post(f'/api/clean/tasks/{job_id}/retry').status_code == 409
    assert _append(client)['match_status'] == 'unchanged'


@pytest.mark.parametrize('damage', ['missing', 'count', 'bounds'])
def test_invalid_incremental_scope_fails_without_falling_back_to_whole_task(db, monkeypatch, damage):
    client, job_id, _ = _base(db)
    old = _outputs(db, job_id)
    raw_id = _add(db,[('2000','新增')])[0]
    _append(client)
    run = db.query(CleanTaskRun).filter_by(clean_job_id=job_id).one()
    if damage == 'missing': db.query(CleanJobItemRecord).filter_by(raw_data_id=raw_id).delete()
    elif damage == 'count': run.input_count += 1
    else: run.snapshot_start_id = None
    db.commit()
    monkeypatch.setattr(clean,'run_clean',lambda *a,**k: pytest.fail('invalid scope must fail before cleaning'))
    assert queue.execute_next_run(db)
    assert db.get(CleanJobRecord,job_id).status == 'failed'
    assert _outputs(db,job_id) == old


def test_append_cannot_change_config_and_explicit_reclean_stays_full(db):
    client, job_id, _ = _base(db)
    old = _outputs(db,job_id)
    _add(db,[('2000','新增')])
    response=client.post('/api/clean/tasks/upsert-monthly',json={'category_code':'headphone','platform':'jd','month':202603,'rules':{'dedup':False}})
    assert response.status_code == 400 and '配置' in response.json()['detail']
    assert _outputs(db,job_id)==old
    assert db.query(CleanJobItemRecord).filter_by(clean_job_id=job_id).count()==1
    response=client.post('/api/clean/tasks/upsert-monthly',json={'category_code':'headphone','platform':'jd','month':202603,'rules':{'dedup':False},'force_reclean':True})
    assert response.status_code==200,response.text
    run=db.query(CleanTaskRun).filter_by(clean_job_id=job_id).one()
    assert (run.mode,run.input_count,run.snapshot_start_id,run.snapshot_end_id)==('full',2,None,None)
    assert queue.execute_next_run(db)
    assert db.get(CleanJobRecord,job_id).row_out==2


@pytest.mark.parametrize('kind',['review','extra','attrs','published'])
def test_reviewed_append_preserves_results_but_reclean_still_requires_rebuild(db,kind):
    client,job_id,old_raw=_base(db)
    result=db.query(MatchResult).filter_by(clean_job_id=job_id).one()
    if kind=='review': result.match_status='confirmed'; result.matched_by='manual'
    elif kind=='extra': db.add(MatchResultExtraValue(match_result_id=result.id,field_key='智能',field_value='是',source='manual'))
    elif kind=='attrs': db.add(MatchResultAttr(match_result_id=result.id,attr_name='连接',attr_value='蓝牙'))
    else: db.add(PublishJob(clean_job_id=job_id,status='done'))
    db.commit(); before=_outputs(db,job_id)
    protected = {m: [tuple(getattr(r,c.name) for c in m.__table__.columns) for r in db.query(m).order_by(m.id)]
                 for m in (MatchResultAttr, MatchResultExtraValue, PublishJob)}
    new_raw=_add(db,[('2000','新增')])[0]
    response=client.post('/api/clean/tasks/upsert-monthly',json={
        'category_code':'headphone','platform':'jd','month':202603,'force_reclean':True,
    })
    assert response.status_code==400,response.text
    assert _outputs(db,job_id)==before
    assert db.query(CleanTaskRun).filter_by(clean_job_id=job_id).one().state=='done'
    response=client.post('/api/clean/tasks/upsert-monthly',json={
        'category_code':'headphone','platform':'jd','month':202603,
    })
    assert response.status_code==200,response.text
    assert response.json()['snapshot_count']==1
    run=db.query(CleanTaskRun).filter_by(clean_job_id=job_id).one()
    assert (run.mode,run.input_count,run.state)==('incremental',1,'queued')
    assert _outputs(db,job_id)==before
    assert queue.execute_next_run(db)
    db.expire_all()
    assert _outputs(db,job_id,old_raw)==before
    assert db.query(MatchResult).filter_by(clean_job_id=job_id,raw_data_id=new_raw).count()==1
    for model,records in protected.items():
        assert [tuple(getattr(r,c.name) for c in model.__table__.columns)
                for r in db.query(model).order_by(model.id)]==records


def test_scoped_batch_match_preserves_old_manual_attributes_candidates_and_extra_fields(db,monkeypatch):
    _,job_id,old_raw=_base(db)
    old=db.query(MatchResult).filter_by(clean_job_id=job_id).one()
    old.match_status='confirmed'; old.matched_by='manual'; old.review_note='必须保留'
    model=ModelRecord(brand_code='TEST',model_code='MODEL',category_code='headphone')
    db.add(model); db.flush(); old.model_id=model.id
    db.add_all([MatchResultAttr(match_result_id=old.id,attr_name='连接',attr_value='旧属性'),
                MatchResultCandidate(match_result_id=old.id,model_id=model.id,score=99,rank=1),
                MatchResultExtraValue(match_result_id=old.id,field_key='智能',field_value='是',source='manual')])
    raw_id=_add(db,[('2000','新商品')])[0]
    db.add(CleanedDataRecord(clean_job_id=job_id,raw_data_id=raw_id,item_name='新商品',item_url='https://item.jd.com/2000.html'))
    db.add(ItemUrlMapping(platform='jd',item_id='2000',model_id=model.id)); db.commit()
    baseline=_outputs(db,job_id,old_raw); old_children={m:db.query(m).filter_by(match_result_id=old.id).count() for m in (MatchResultAttr,MatchResultCandidate,MatchResultExtraValue)}
    seen=[]
    def audit(db,ids,commit=True,**kwargs):
        assert commit is False; seen.extend(ids)
    monkeypatch.setattr(matcher,'audit_price',audit)
    result=matcher.run_match(db,job_id,raw_data_ids=[raw_id],commit=False)
    assert result['total']==1
    db.flush()
    assert _outputs(db,job_id,old_raw)==baseline
    assert old.id not in seen and len(seen)==1
    for m,count in old_children.items(): assert db.query(m).filter_by(match_result_id=old.id).count()==count
    db.rollback()
    assert not db.query(MatchResult).filter_by(clean_job_id=job_id,raw_data_id=raw_id).first()
    matcher.run_match(db,job_id,raw_data_ids=[],commit=False)
    assert _outputs(db,job_id,old_raw)==baseline


def test_scope_migration_defaults_existing_queue_to_full_and_preserves_it_on_downgrade(tmp_path,monkeypatch):
    from alembic import command
    from alembic.config import Config
    url=f'sqlite:///{tmp_path / "migration.db"}'
    engine=create_engine(url)
    with engine.begin() as c:
        c.execute(text('CREATE TABLE clean_jobs (id INTEGER PRIMARY KEY)'))
        c.execute(text('INSERT INTO clean_jobs(id) VALUES(1)'))
        c.execute(text('CREATE TABLE upload_files(id INTEGER PRIMARY KEY, filename VARCHAR(255) NOT NULL)'))
    monkeypatch.setattr(settings,'DATABASE_URL',url)
    config=Config(); config.set_main_option('script_location',str(Path(__file__).resolve().parents[1]/'alembic'))
    command.stamp(config,'p74a1b2c3d4e5'); command.upgrade(config,'p76a1b2c3d4e5')
    with engine.begin() as c:
        c.execute(text("INSERT INTO clean_task_runs(clean_job_id,state,stage,queued_at) VALUES(1,'queued','排队中',CURRENT_TIMESTAMP)"))
    command.upgrade(config,'head')
    with engine.connect() as c:
        assert c.execute(text('SELECT mode,input_count,snapshot_start_id,snapshot_end_id FROM clean_task_runs')).one()==('full',0,None,None)
    with engine.begin() as c:
        c.execute(text("UPDATE clean_task_runs SET mode='incremental',state='failed',snapshot_start_id=5,snapshot_end_id=8,input_count=4"))
    with pytest.raises(RuntimeError,match='未完成的增量任务'):
        command.downgrade(config,'p76a1b2c3d4e5')
    with engine.connect() as c:
        assert c.execute(text('SELECT mode,input_count,snapshot_start_id,snapshot_end_id FROM clean_task_runs')).one()==('incremental',4,5,8)
    with engine.begin() as c:
        c.execute(text("UPDATE clean_task_runs SET mode='full',state='queued'"))
    command.downgrade(config,'p76a1b2c3d4e5')
    assert 'mode' not in {c['name'] for c in inspect(engine).get_columns('clean_task_runs')}
    with engine.connect() as c: assert c.execute(text('SELECT state FROM clean_task_runs')).scalar()=='queued'


def test_killed_append_rolls_back_and_real_worker_retries_persisted_scope(tmp_path):
    database=tmp_path/'durable.db'
    bind=create_engine(f'sqlite:///{database}')
    Base.metadata.create_all(bind)
    ready=tmp_path/'uncommitted-ready'
    env=dict(os.environ,DATABASE_URL=f'sqlite:///{database}',
             ANALYTICS_DATABASE_URL=f'sqlite:///{tmp_path / "analytics.db"}',
             PYTHONPATH=str(Path(__file__).resolve().parents[1]),
             UPLOAD_DIR=str(tmp_path/'uploads'),EXPORT_DIR=str(tmp_path/'exports'))
    with Session(bind,expire_on_commit=False) as db:
        client,job_id,old_raw=_base(db)
        old=_outputs(db,job_id)
        new_raw=_add(db,[('2000','新增')])[0]
        _append(client)
        run=db.query(CleanTaskRun).filter_by(clean_job_id=job_id).one()
        bounds=(run.snapshot_start_id,run.snapshot_end_id,run.input_count)
    # This child completes every stage but dies before the single output commit.
    script='''import time
from pathlib import Path
from sqlalchemy.orm import Session
from app.models.database import engine
from app.services.clean_task_queue import clean_execution_lock, execute_next_run
from app.api.clean import _run_incremental_clean_and_match_for_job

def hold(db,job,**kwargs):
    _run_incremental_clean_and_match_for_job(db,job,**kwargs)
    Path(READY).write_text('flushed')
    time.sleep(60)

with clean_execution_lock(engine) as connection:
    assert connection is not None
    with Session(connection,expire_on_commit=False) as db:
        execute_next_run(db,executor=hold)
'''.replace('READY',repr(str(ready)))
    def until(predicate,timeout=15):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            if predicate(): return
            time.sleep(.05)
        pytest.fail('child worker timed out: '+log_path.read_text())
    log_path=tmp_path/'worker.log'
    with log_path.open('w') as log:
        child=subprocess.Popen([sys.executable,'-c',script],env=env,stdout=log,stderr=log)
        try:
            until(ready.exists)
            with Session(bind) as db:
                assert _outputs(db,job_id)==old,'uncommitted append must not leak to readers'
                assert db.query(CleanTaskRun).filter_by(clean_job_id=job_id).one().state=='running'
        finally:
            child.kill(); child.wait(timeout=10)
        worker=subprocess.Popen([sys.executable,'-m','app.workers.clean_worker'],env=env,stdout=log,stderr=log)
        def state(expected):
            with Session(bind) as db:
                return db.query(CleanTaskRun).filter_by(clean_job_id=job_id).one().state==expected
        try:
            until(lambda:state('failed'))
            with Session(bind,expire_on_commit=False) as db:
                assert _outputs(db,job_id)==old
                run=db.query(CleanTaskRun).filter_by(clean_job_id=job_id).one()
                assert run.stage=='已中断'
                assert (run.snapshot_start_id,run.snapshot_end_id,run.input_count)==bounds
                assert _client(db).post(f'/api/clean/tasks/{job_id}/retry').status_code==200
            until(lambda:state('done'))
        finally:
            worker.send_signal(signal.SIGTERM); worker.wait(timeout=10)
    assert worker.returncode==0,log_path.read_text()
    with Session(bind) as db:
        assert _outputs(db,job_id,old_raw)==old
        assert db.query(MatchResult).filter_by(clean_job_id=job_id,raw_data_id=new_raw).count()==1
        assert db.get(CleanJobRecord,job_id).row_out==2


def test_incremental_business_results_equal_full_reclean_with_unchanged_rules(db,tmp_path):
    import sqlite3
    client,job_id,_=_base(db)
    db.add(InterventionRule(category_code='headphone',name='过滤',action='filter',
                            conditions={'item_name_contains_any':['blocked']},is_active=1))
    db.commit()
    _add(db,[('1000','旧重复'),('4000','blocked old')])
    _append(client); assert queue.execute_next_run(db)
    _add(db,[('1000','跨批重复'),(None,'空ID甲'),(None,'空ID乙'),
             ('2000','新品'),('2000','同批重复'),('3000','blocked new')])
    _append(client); db.commit()
    # Identical persisted input, old outputs and queued snapshot; only mode differs.
    clone=tmp_path/'full.db'
    source=db.get_bind().raw_connection()
    try:
        with sqlite3.connect(clone) as destination:
            source.driver_connection.backup(destination)
    finally: source.close()
    with Session(create_engine(f'sqlite:///{clone}')) as full:
        run=full.query(CleanTaskRun).filter_by(clean_job_id=job_id).one()
        run.mode='full'; full.commit()
        assert queue.execute_next_run(full)
        expected={}
        for model in (CleanedDataRecord,FilteredItem,MatchResult):
            columns=[c.name for c in model.__table__.columns if c.name not in {'id','created_at','updated_at'}]
            expected[model]=sorted((tuple(getattr(row,name) for name in columns) for row in full.query(model).filter_by(clean_job_id=job_id)),key=repr)
    assert queue.execute_next_run(db)
    for model,values in expected.items():
        columns=[c.name for c in model.__table__.columns if c.name not in {'id','created_at','updated_at'}]
        actual=sorted((tuple(getattr(row,name) for name in columns) for row in db.query(model).filter_by(clean_job_id=job_id)),key=repr)
        assert actual==values,model.__name__


@pytest.mark.parametrize('force',[{}, {'force_reclean':True}, {'force_rebuild':True}])
def test_busy_increment_cannot_be_overwritten_by_append_or_rebuild(db,force):
    client,job_id,_=_base(db)
    old=_outputs(db,job_id)
    _add(db,[('2000','新增')]); _append(client)
    run=db.query(CleanTaskRun).filter_by(clean_job_id=job_id).one()
    scope=(run.snapshot_start_id,run.snapshot_end_id,run.input_count)
    response=client.post('/api/clean/tasks/upsert-monthly',json={'category_code':'headphone','platform':'jd','month':202603,**force})
    assert response.status_code==409
    db.refresh(run)
    assert (run.mode,run.state)==('incremental','queued')
    assert (run.snapshot_start_id,run.snapshot_end_id,run.input_count)==scope
    assert _outputs(db,job_id)==old


def test_enqueue_failure_rolls_back_append_snapshot_and_previous_queue_row(db,monkeypatch):
    client,job_id,_=_base(db)
    _add(db,[('2000','新增')])
    run=db.query(CleanTaskRun).filter_by(clean_job_id=job_id).one()
    before=(run.mode,run.state,run.worker_token,run.queued_at)
    enqueue=clean.enqueue_clean_job
    with monkeypatch.context() as patch:
        def fail(*args,**kwargs):
            enqueue(*args,**kwargs)
            raise RuntimeError('入队后回滚')
        patch.setattr(clean,'enqueue_clean_job',fail)
        response=client.post('/api/clean/tasks/upsert-monthly',json={'category_code':'headphone','platform':'jd','month':202603})
        assert response.status_code==500
    db.refresh(run)
    assert (run.mode,run.state,run.worker_token,run.queued_at)==before
    assert db.query(CleanJobItemRecord).filter_by(clean_job_id=job_id).count()==1
    assert db.get(CleanJobRecord,job_id).row_in==1
    assert _append(client)['snapshot_count']==1
    assert queue.execute_next_run(db)
