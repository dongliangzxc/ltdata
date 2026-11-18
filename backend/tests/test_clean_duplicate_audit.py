"""Duplicate traceability follows actual cleaning order and transaction boundaries."""
from pathlib import Path
from types import SimpleNamespace
import json

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, inspect, text

from app.api import clean, rules_api, upload
from app.core.config import settings
from app.models.schemas import (Category, CleanDuplicateRecord, CleanedDataRecord, CleanJobItemRecord,
    CleanJobRecord, FilteredItem, InterferenceLink, InterventionRule, RawDataRecord, UploadFileRecord)
from app.services import data_cleaner, clean_task_queue as queue
from app.services.clean_accounting import clean_accounting
from tests.test_data_cleaner_batches import _seed
from tests.test_incremental_clean_task import _base, _add, _append
from tests.test_clean_task_queue import _client


@pytest.fixture(autouse=True)
def background(monkeypatch):
    monkeypatch.setattr(settings,'CLEAN_BACKGROUND_ENABLED',True)


def _details(db,job_id,**params):
    response=_client(db).get(f'/api/clean/jobs/{job_id}/matched',params={'group':'duplicates',**params})
    assert response.status_code==200,response.text
    return response.json()


def _duplicates(db,job_id):
    return [(r.id,r.raw_data_id,r.kept_raw_data_id,r.dedup_key,r.created_at)
            for r in db.query(CleanDuplicateRecord).filter_by(clean_job_id=job_id).order_by(CleanDuplicateRecord.id)]


def test_duplicate_records_follow_snapshot_order_across_batches_without_per_row_inserts(db,monkeypatch):
    file_id,_,job_id=_seed(db,7)
    db.query(RawDataRecord).filter(RawDataRecord.id.in_([1,4,7])).update({'item_id':'duplicate'})
    db.commit(); monkeypatch.setattr(data_cleaner,'_CLEAN_BATCH_SIZE',2)
    sizes=[]; insert=db.bulk_insert_mappings
    def record(model,mappings,**kwargs):
        if model is CleanDuplicateRecord: sizes.append(len(mappings))
        return insert(model,mappings,**kwargs)
    monkeypatch.setattr(db,'bulk_insert_mappings',record)
    assert data_cleaner.run_clean(db,job_id,[file_id],{})==5
    rows=db.query(CleanDuplicateRecord).filter_by(clean_job_id=job_id).all()
    assert {r.raw_data_id:r.kept_raw_data_id for r in rows}=={4:7,1:7}
    assert all(r.dedup_key=={'item_id':'duplicate','month':202603,'shop_name':'官方店'} for r in rows)
    assert all(r.dedup_basis=='item_id_month_shop' for r in rows)
    assert sum(sizes)==2 and max(sizes)<=2
    job=db.get(CleanJobRecord,job_id)
    assert (job.row_in,job.row_out,job.row_filtered,job.row_duplicated)==(7,5,0,2)
    job.status='reviewing'; db.commit()
    details=_details(db,job_id)
    assert details['accounting']==dict(input_count=7,retained_count=5,filtered_count=0,duplicate_count=2,audit_complete=True,difference=0,status='balanced')


@pytest.mark.parametrize('missing',[None,'','   '])
def test_missing_product_ids_remain_distinct_and_are_not_reported_as_duplicates(db,missing):
    file_id,_,job_id=_seed(db,2)
    db.query(RawDataRecord).update({'item_id':missing}); db.commit()
    assert data_cleaner.run_clean(db,job_id,[file_id],{})==2
    assert db.query(CleanDuplicateRecord).count()==0
    assert db.get(CleanJobRecord,job_id).row_duplicated==0


def test_disabled_dedup_keeps_both_rows_and_records_zero_duplicates(db):
    file_id,_,job_id=_seed(db,2)
    db.query(RawDataRecord).update({'item_id':'same'}); db.commit()
    assert data_cleaner.run_clean(db,job_id,[file_id],{'dedup':False})==2
    assert db.query(CleanDuplicateRecord).count()==0
    assert db.get(CleanJobRecord,job_id).row_duplicated==0


@pytest.mark.parametrize('source',['rule','link'])
def test_filtering_stays_before_dedup_and_is_not_counted_twice(db,source):
    file_id,_,job_id=_seed(db,2)
    db.query(RawDataRecord).update({'item_id':'same'})
    db.query(RawDataRecord).filter_by(id=2).update({'item_name':'blocked','item_url':'https://example.com/blocked'})
    if source=='rule': db.add(InterventionRule(category_code='headphone',name='filter',action='filter',conditions={'item_name_contains_any':['blocked']}))
    else: db.add(InterferenceLink(category_code='headphone',url='https://example.com/blocked'))
    db.commit()
    assert data_cleaner.run_clean(db,job_id,[file_id],{},dispatch_category_code='headphone')==1
    assert db.query(CleanDuplicateRecord).count()==0
    assert db.query(FilteredItem).one().raw_data_id==2
    assert db.query(CleanedDataRecord).one().raw_data_id==1


def test_same_source_and_repeated_duplicate_scope_are_idempotent(db):
    file_id,_,job_id=_seed(db,3)
    db.query(RawDataRecord).update({'item_id':'same'}); db.commit()
    data_cleaner.run_clean(db,job_id,[file_id],{})
    before=_duplicates(db,job_id)
    assert data_cleaner.run_clean(db,job_id,[file_id],{},raw_data_ids=[1,2,3],update_job_counts=False)==0
    assert _duplicates(db,job_id)==before
    assert db.query(CleanedDataRecord).count()==1
    assert db.get(CleanJobRecord,job_id).row_duplicated==2


def test_legacy_retained_row_without_source_is_explicitly_unknown(db):
    file_id,_,job_id=_seed(db,2)
    db.query(RawDataRecord).update({'item_id':'same'})
    db.add(CleanedDataRecord(clean_job_id=job_id,raw_data_id=None,item_id='same',month=202603,shop_name='官方店'))
    db.commit()
    assert data_cleaner.run_clean(db,job_id,[file_id],{},raw_data_ids=[1,2])==0
    rows=db.query(CleanDuplicateRecord).all()
    assert len(rows)==2 and all(r.kept_raw_data_id is None for r in rows)
    assert db.get(CleanJobRecord,job_id).row_duplicated is None
    details=_details(db,job_id)
    assert all(row['kept_item_name'] is None for row in details['items'])


def test_audit_writes_roll_back_together_with_all_batches(db,monkeypatch):
    file_id,_,job_id=_seed(db,6)
    db.query(RawDataRecord).filter(RawDataRecord.id.in_([5,6])).update({'item_id':'same'})
    db.commit(); monkeypatch.setattr(data_cleaner,'_CLEAN_BATCH_SIZE',2)
    insert=db.bulk_insert_mappings; calls=[]
    def fail(model,mappings,**kwargs):
        if model is CleanedDataRecord:
            calls.append(1)
            if len(calls)==2: raise RuntimeError('第二批失败')
        return insert(model,mappings,**kwargs)
    monkeypatch.setattr(db,'bulk_insert_mappings',fail)
    with pytest.raises(RuntimeError,match='第二批失败'): data_cleaner.run_clean(db,job_id,[file_id],{},commit=False)
    db.rollback()
    assert db.query(CleanDuplicateRecord).count()==db.query(CleanedDataRecord).count()==0
    assert db.get(CleanJobRecord,job_id).row_duplicated is None


def test_incremental_audit_uses_existing_retained_source_and_survives_retry(db,monkeypatch):
    client,job_id,original_raw=_base(db)
    first=_add(db,[('1000','旧重复')])[0]; _append(client); assert queue.execute_next_run(db)
    before=_duplicates(db,job_id); assert before[0][1:3]==(first,original_raw)
    new_ids=_add(db,[('1000','新重复'),('2000','新品')]); _append(client)
    match=clean.run_match
    with monkeypatch.context() as patch:
        def fail(*a,**kw):
            match(*a,**kw)
            assert db.query(CleanDuplicateRecord).count()==2
            raise RuntimeError('匹配后失败')
        patch.setattr(clean,'run_match',fail)
        assert queue.execute_next_run(db)
    assert db.get(CleanJobRecord,job_id).status=='failed'
    assert _duplicates(db,job_id)==before
    assert db.get(CleanJobRecord,job_id).row_duplicated==1
    assert _details(db,job_id)['accounting']['status']=='failed'
    assert client.post(f'/api/clean/tasks/{job_id}/retry').status_code==200
    assert queue.execute_next_run(db)
    assert {r.raw_data_id:r.kept_raw_data_id for r in db.query(CleanDuplicateRecord)}=={first:original_raw,new_ids[0]:original_raw}
    assert _duplicates(db,job_id)[0]==before[0]
    assert db.get(CleanJobRecord,job_id).row_duplicated==2
    assert _details(db,job_id)['accounting']['status']=='balanced'
    assert _append(client)['match_status']=='unchanged'
    assert db.query(CleanDuplicateRecord).count()==2


def test_incremental_does_not_claim_complete_history_for_existing_task(db):
    client,job_id,_=_base(db)
    db.get(CleanJobRecord,job_id).row_duplicated=None; db.commit()
    _add(db,[('1000','重复')]); _append(client); assert queue.execute_next_run(db)
    assert db.get(CleanJobRecord,job_id).row_duplicated is None
    accounting=_details(db,job_id)['accounting']
    assert accounting['status']=='legacy' and not accounting['audit_complete'] and accounting['difference'] is None
    assert accounting['duplicate_count']==1


def test_explicit_reclean_replaces_audit_and_disabled_dedup_clears_it(db):
    client,job_id,_=_base(db)
    _add(db,[('1000','重复')]); _append(client); assert queue.execute_next_run(db)
    assert db.query(CleanDuplicateRecord).count()==1
    for rules,expected_duplicates,expected_kept in [({'dedup':True},1,1),({'dedup':False},0,2)]:
        response=client.post('/api/clean/tasks/upsert-monthly',json={'category_code':'headphone','platform':'jd','month':202603,'force_reclean':True,'rules':rules})
        assert response.status_code==200,response.text
        assert queue.execute_next_run(db)
        assert db.query(CleanDuplicateRecord).count()==expected_duplicates
        job=db.get(CleanJobRecord,job_id)
        assert (job.row_duplicated,job.row_out)==(expected_duplicates,expected_kept)
        assert _details(db,job_id)['accounting']['status']=='balanced'


def test_accounting_uses_active_filtered_and_actual_retained_after_recovery(db):
    file_id,_,job_id=_seed(db,4)
    db.query(RawDataRecord).filter(RawDataRecord.id.in_([3,4])).update({'item_id':'same'})
    db.query(RawDataRecord).filter_by(id=1).update({'item_name':'blocked'})
    db.add(InterventionRule(category_code='headphone',name='filter',action='filter',conditions={'item_name_contains_any':['blocked']})); db.commit()
    data_cleaner.run_clean(db,job_id,[file_id],{},dispatch_category_code='headphone')
    db.get(CleanJobRecord,job_id).status='reviewing'; db.commit()
    assert _details(db,job_id)['accounting']['status']=='balanced'
    rules_api._recover_one(db.query(FilteredItem).one(),db); db.commit()
    accounting=_details(db,job_id)['accounting']
    assert (accounting['input_count'],accounting['retained_count'],accounting['filtered_count'],accounting['duplicate_count'],accounting['status'])==(4,3,0,1,'balanced')


def test_duplicate_endpoint_filters_both_titles_price_and_pagination(db):
    file_id,_,job_id=_seed(db,4)
    db.query(RawDataRecord).update({'item_id':'same'})
    db.query(RawDataRecord).filter_by(id=1).update({'item_name':'重复甲','price':20})
    db.commit(); data_cleaner.run_clean(db,job_id,[file_id],{})
    assert _details(db,job_id,keyword='商品4')['total']==3
    hit=_details(db,job_id,keyword='重复甲',price_min=15,price_max=25)
    assert hit['total']==1 and hit['items'][0]['raw_data_id']==1 and hit['items'][0]['kept_raw_data_id']==4
    assert hit['items'][0]['kept_item_name']=='商品4'
    assert _details(db,job_id,keyword='重复甲',price_max=15)['total']==0
    first=_details(db,job_id,page_size=1,page=1); second=_details(db,job_id,page_size=1,page=2)
    assert first['counts']['duplicates']==3 and first['total']==3
    assert first['items'][0]['raw_data_id']!=second['items'][0]['raw_data_id']


def test_duplicate_details_respect_category_visibility_and_missing_job(db):
    file_id,_,job_id=_seed(db,2)
    db.add_all([Category(code='headphone',name='耳机'),Category(code='camera',name='相机')])
    db.query(RawDataRecord).update({'item_id':'same'}); db.commit(); data_cleaner.run_clean(db,job_id,[file_id],{})
    hidden=_client(db,category_permissions=['camera'])
    assert hidden.get(f'/api/clean/jobs/{job_id}/matched',params={'group':'duplicates'}).status_code==404
    assert _client(db).get('/api/clean/jobs/999999/matched',params={'group':'duplicates'}).status_code==404


def test_archiving_preserves_duplicate_audit_and_list_count(db):
    client,job_id,_=_base(db)
    _add(db,[('1000','重复')]); _append(client); queue.execute_next_run(db)
    before=_duplicates(db,job_id)
    assert client.delete(f'/api/clean/jobs/{job_id}').status_code==200
    assert _duplicates(db,job_id)==before
    assert _details(db,job_id)['accounting']['status']=='balanced'
    listed=client.get('/api/clean/jobs',params={'view':'archived','category_code':'headphone'}).json()
    assert listed[0]['row_duplicated']==1


@pytest.mark.parametrize('status,tracked,kept,filtered,duplicates,expected,difference',[
    ('reviewing',2,5,3,2,'balanced',0),('reviewing',None,5,3,0,'legacy',None),
    ('reviewing',2,4,3,2,'mismatch',1),('reviewing',2,6,3,2,'mismatch',-1),
    ('cleaning',2,5,3,2,'processing',0),('failed',2,5,3,2,'failed',0),
])
def test_accounting_never_labels_unknown_or_unfinished_data_balanced(status,tracked,kept,filtered,duplicates,expected,difference):
    result=clean_accounting(SimpleNamespace(status=status,row_duplicated=tracked,row_in=10),kept,filtered,duplicates)
    assert (result['status'],result['difference'])==(expected,difference)


@pytest.mark.parametrize('side',['duplicate','kept'])
@pytest.mark.parametrize('kind',['file','batch'])
def test_upload_delete_refuses_either_side_of_duplicate_reference(db,side,kind):
    a=UploadFileRecord(filename='a',batch_key='a'); b=UploadFileRecord(filename='b',batch_key='b'); db.add_all([a,b]); db.flush()
    kept=RawDataRecord(file_id=a.id,item_id='same'); duplicate=RawDataRecord(file_id=b.id,item_id='same')
    job=CleanJobRecord(file_ids=[a.id,b.id],rules={},status='done'); db.add_all([kept,duplicate,job]); db.flush()
    db.add(CleanDuplicateRecord(clean_job_id=job.id,raw_data_id=duplicate.id,kept_raw_data_id=kept.id,dedup_basis='item_id_month_shop',dedup_key={'item_id':'same'})); db.commit()
    target=a if side=='kept' else b
    with pytest.raises(HTTPException) as error:
        if kind=='file': upload.delete_upload_file(target.id,db=db)
        else: upload.delete_upload_batch(target.batch_key,db=db)
    assert error.value.status_code==400
    assert db.query(RawDataRecord).count()==2 and db.query(CleanDuplicateRecord).count()==1


def test_audit_migration_preserves_existing_unknown_history_and_indexes(tmp_path,monkeypatch):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy.schema import CreateTable
    from sqlalchemy.dialects.mysql import dialect
    ddl=str(CreateTable(CleanDuplicateRecord.__table__).compile(dialect=dialect()))
    assert 'uq_clean_duplicate_job_raw' in ddl and 'ON DELETE CASCADE' in ddl
    url=f'sqlite:///{tmp_path / "migration.db"}'; engine=create_engine(url)
    with engine.begin() as conn:
        conn.execute(text('CREATE TABLE clean_jobs(id INTEGER PRIMARY KEY)'))
        conn.execute(text('CREATE TABLE raw_data(id INTEGER PRIMARY KEY)'))
        conn.execute(text('INSERT INTO clean_jobs(id) VALUES(7)'))
    monkeypatch.setattr(settings,'DATABASE_URL',url)
    config=Config(); config.set_main_option('script_location',str(Path(__file__).resolve().parents[1]/'alembic'))
    command.stamp(config,'p74a1b2c3d4e5'); command.upgrade(config,'head')
    # Alembic uses a separate engine; reopen SQLite's cached schema connection.
    engine.dispose()
    indexes=inspect(engine).get_indexes('clean_duplicates')
    assert any(i['name']=='idx_clean_duplicates_job_id' for i in indexes),indexes
    with engine.connect() as conn:
        assert conn.execute(text('SELECT row_duplicated FROM clean_jobs WHERE id=7')).scalar() is None
        assert conn.execute(text('SELECT COUNT(*) FROM clean_duplicates')).scalar()==0
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO clean_task_runs(clean_job_id,state,stage,mode,input_count,queued_at) VALUES(7,'failed','失败','incremental',2,CURRENT_TIMESTAMP)"))
    with pytest.raises(RuntimeError,match='未完成的增量任务'):
        command.downgrade(config,'p77a1b2c3d4e5')
    assert 'clean_duplicates' in inspect(engine).get_table_names()
    with engine.begin() as conn:
        conn.execute(text("UPDATE clean_task_runs SET state='done'"))
    command.downgrade(config,'p77a1b2c3d4e5')
    engine.dispose()
    assert 'clean_duplicates' not in inspect(engine).get_table_names()
    assert 'row_duplicated' not in {c['name'] for c in inspect(engine).get_columns('clean_jobs')}
    with engine.connect() as conn: assert conn.execute(text('SELECT id FROM clean_jobs')).scalar()==7


def test_large_duplicate_input_records_in_bounded_bulk_batches(db,monkeypatch):
    file_id,_,job_id=_seed(db,2005)
    db.query(RawDataRecord).update({'item_id':'same'}); db.commit()
    sizes=[]; insert=db.bulk_insert_mappings
    def record(model,mappings,**kwargs):
        if model is CleanDuplicateRecord: sizes.append(len(mappings))
        return insert(model,mappings,**kwargs)
    monkeypatch.setattr(db,'bulk_insert_mappings',record)
    assert data_cleaner.run_clean(db,job_id,[file_id],{})==1
    assert sizes==[999,1000,5]
    assert db.query(CleanDuplicateRecord).filter_by(kept_raw_data_id=2005).count()==2004
    assert (db.get(CleanJobRecord,job_id).row_in,db.get(CleanJobRecord,job_id).row_duplicated)==(2005,2004)
