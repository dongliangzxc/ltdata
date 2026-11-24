"""Permanent category-independent entry: append new dispatch and repair only genuine gaps."""
from datetime import datetime

import pytest

from app.api import clean
from app.core.config import settings
from app.models.schemas import (
    CleanDuplicateRecord, CleanedDataRecord, CleanJobItemRecord, CleanJobRecord,
    CleanTaskRun, FilteredItem, MatchResult, MatchResultAttr, MatchResultExtraValue, MatchTransferLog, PublishJob,
)
from app.services import clean_task_queue as queue, matcher
from tests.test_clean_task_queue import _client, _pending, _submit, _assert_original_results_unchanged


@pytest.fixture(autouse=True)
def background(monkeypatch):
    monkeypatch.setattr(settings, 'CLEAN_BACKGROUND_ENABLED', True)
    monkeypatch.setattr(matcher, 'audit_price', lambda *a, **k: {})


def _gap(db, category='projector'):
    old_raw = _pending(db, category=category, item_id='1000')
    gap_raw = _pending(db, category=category, item_id='2000')
    client = _client(db)
    job_id = _submit(client, category=category)
    assert queue.execute_next_run(db)
    old = db.query(MatchResult).filter_by(clean_job_id=job_id, raw_data_id=old_raw).one()
    old.match_status, old.matched_by, old.review_note = 'confirmed', 'manual', '保留人工确认'
    old.reviewed_at, old.sales_coefficient = datetime(2026, 1, 1), .75
    attr = MatchResultAttr(match_result_id=old.id, attr_name='类型', attr_value='保留')
    extra = MatchResultExtraValue(match_result_id=old.id, field_key='智能', field_value='是', source='manual')
    published = PublishJob(clean_job_id=job_id, status='done', published_count=1)
    db.add_all([attr, extra, published])
    missing = db.query(MatchResult).filter_by(clean_job_id=job_id, raw_data_id=gap_raw).one()
    db.delete(missing)
    db.commit()
    records = [old, attr, extra, published, *db.query(CleanedDataRecord).filter_by(clean_job_id=job_id)]
    before = [(type(x), x.id, {c.name:getattr(x,c.name) for c in x.__table__.columns}) for x in records]
    return client, job_id, gap_raw, before


@pytest.mark.parametrize('category', ['projector', 'router', 'headphone'])
@pytest.mark.parametrize('status', ['reviewing', 'done', 'published'])
def test_completion_repairs_all_categories_and_preserves_manual_and_published_outputs(db, monkeypatch, category, status):
    client, job_id, gap_raw, before = _gap(db, category)
    db.get(CleanJobRecord, job_id).status = status
    db.commit()
    path = f'/api/clean/tasks/{job_id}/completion'
    assert client.get(path).json() == {'job_id':job_id, 'new_items':0, 'missing_results':1}
    assert db.query(CleanTaskRun).one().state == 'done', 'checking is read-only'
    response = client.post(path)
    assert response.status_code == 200, response.text
    assert response.json()['match_status'] == 'queued'
    monkeypatch.setattr(clean, 'run_clean', lambda *a, **k:pytest.fail('existing cleaned fields must remain intact'))
    original, scopes = clean.run_match, []
    def match(*a, **k):
        scopes.append(k['raw_data_ids'])
        assert k['commit'] is False and k['strict_audit'] is True
        return original(*a, **k)
    monkeypatch.setattr(clean, 'run_match', match)
    assert queue.execute_next_run(db)
    assert scopes == [[gap_raw]]
    _assert_original_results_unchanged(db, before)
    assert db.query(MatchResult).filter_by(clean_job_id=job_id, raw_data_id=gap_raw).count() == 1
    assert client.post(path).json()['match_status'] == 'unchanged'
    assert not queue.execute_next_run(db)


def test_completion_combines_new_dispatch_with_existing_gap_and_ignores_later_dispatch(db):
    client, job_id, gap_raw, before = _gap(db)
    new_raw = _pending(db, category='projector', item_id='3000')
    path = f'/api/clean/tasks/{job_id}/completion'
    assert client.get(path).json() == {'job_id':job_id, 'new_items':1, 'missing_results':1}
    result = client.post(path)
    assert result.status_code == 200, result.text
    run = db.query(CleanTaskRun).one()
    assert (run.mode, run.input_count) == ('completion', 2)
    later = _pending(db, category='projector', item_id='4000')
    assert queue.execute_next_run(db)
    _assert_original_results_unchanged(db, before)
    assert {x.raw_data_id for x in db.query(MatchResult).filter_by(clean_job_id=job_id)} == {before[0][2]['raw_data_id'],gap_raw,new_raw}
    assert not db.query(CleanJobItemRecord).filter_by(clean_job_id=job_id,raw_data_id=later).first()
    assert client.get(path).json()['new_items'] == 1


@pytest.mark.parametrize('kind', ['filtered', 'duplicate', 'disabled', 'no_cleaned'])
def test_completion_does_not_restore_intentionally_omitted_rows(db, kind):
    client, job_id, gap_raw, before = _gap(db)
    if kind == 'filtered':
        db.add(FilteredItem(clean_job_id=job_id,raw_data_id=gap_raw,is_recovered=0))
    elif kind == 'duplicate':
        db.add(CleanDuplicateRecord(clean_job_id=job_id,raw_data_id=gap_raw,dedup_basis='item',dedup_key=['2000']))
    elif kind == 'disabled':
        db.add(MatchResult(clean_job_id=job_id,raw_data_id=gap_raw,match_status='pending',is_disabled=1))
    else:
        db.query(CleanedDataRecord).filter_by(clean_job_id=job_id,raw_data_id=gap_raw).delete()
    db.commit()
    path = f'/api/clean/tasks/{job_id}/completion'
    assert client.get(path).json()['missing_results'] == 0
    assert client.post(path).json()['match_status'] == 'unchanged'
    assert not queue.execute_next_run(db)


@pytest.mark.parametrize('with_new', [False, True])
def test_completion_failure_is_atomic_and_retries_protect_old_manual_and_publication(db, monkeypatch, with_new):
    client, job_id, gap_raw, before = _gap(db)
    if with_new:
        _pending(db,category='projector',item_id='3000')
    assert client.post(f'/api/clean/tasks/{job_id}/completion').status_code == 200
    original = clean.run_match
    def fail(*a, **k):
        original(*a, **k)
        raise RuntimeError('模拟补齐失败')
    with monkeypatch.context() as patch:
        patch.setattr(clean, 'run_match', fail)
        assert queue.execute_next_run(db)
    _assert_original_results_unchanged(db, before)
    assert db.get(CleanJobRecord,job_id).status == 'failed'
    assert not db.query(MatchResult).filter_by(clean_job_id=job_id,raw_data_id=gap_raw).first()
    assert client.post(f'/api/clean/tasks/{job_id}/retry').status_code == 200
    assert queue.execute_next_run(db)
    _assert_original_results_unchanged(db,before)
    assert db.query(MatchResult).filter_by(clean_job_id=job_id,raw_data_id=gap_raw).count() == 1


def test_completion_is_scoped_permission_checked_and_busy_tasks_are_blocked(db):
    client, job_id, gap_raw, before = _gap(db)
    denied = _client(db,category_permissions=['headphone'])
    for method in [denied.get,denied.post]:
        assert method(f'/api/clean/tasks/{job_id}/completion').status_code == 404
    assert client.post(f'/api/clean/tasks/{job_id}/completion').status_code == 200
    assert client.post(f'/api/clean/tasks/{job_id}/completion').status_code == 409
    _assert_original_results_unchanged(db,before)


def _transfer_gap(db):
    client, job_id, gap_raw, before = _gap(db)
    target = CleanJobRecord(category_code='bt_speaker',platform='jd',status='reviewing',source_scope={'months':[202603]})
    db.add(target)
    db.flush()
    result = MatchResult(clean_job_id=target.id,raw_data_id=gap_raw,match_status='text_only')
    db.add(result)
    db.flush()
    departure = MatchTransferLog(match_result_id=result.id,raw_data_id=gap_raw,from_clean_job_id=job_id,
                                 to_clean_job_id=target.id,transferred_at=datetime(2026,11,23,1,57,13))
    db.add(departure)
    db.commit()
    return client,job_id,gap_raw,before,target,result


@pytest.mark.parametrize('target_result_retained',[True,False])
def test_transferred_item_is_never_recreated_in_source_task(db,target_result_retained):
    client,job_id,gap_raw,before,target,result = _transfer_gap(db)
    if not target_result_retained:
        db.delete(result)
        db.commit()
    path=f'/api/clean/tasks/{job_id}/completion'
    assert client.get(path).json()['missing_results']==0
    assert client.post(path).json()['match_status']=='unchanged'
    assert not queue.execute_next_run(db)
    assert db.query(MatchResult).filter_by(clean_job_id=job_id,raw_data_id=gap_raw).count()==0
    _assert_original_results_unchanged(db,before)


def test_statistics_count_transfer_as_source_completion_without_inflating_matches(db):
    from app.api.stats_api import _progress_stats
    client,job_id,gap_raw,before,target,result = _transfer_gap(db)
    db.query(MatchResult).filter_by(clean_job_id=job_id).update({'updated_at':datetime(2026,11,1)})
    db.commit()
    progress=_progress_stats(db)
    source=next(x for x in progress['categories'] if x['category_code']=='projector')
    month=progress['months'][0]
    assert source['dispatched']==source['processed']==2
    assert source['matched']==1 and source['transferred_out']==1
    assert source['pending']==0
    assert source['last_processed_at']==source['completed_at']=='2026-11-23 09:57:13'
    for row in [month,progress]:
        assert row['transferred_out']==1
        assert row['task_no_result']==0
        assert row['processed']==row['matched']+row['excluded_ignored']+row['system_filtered']+row['transferred_out']


def test_transfer_return_and_subsequent_departure_follow_latest_ownership(db):
    from app.api.stats_api import _progress_stats
    from app.services.clean_task_completion import missing_match_raw_ids
    client,job_id,gap_raw,before,target,result = _transfer_gap(db)
    returned=MatchTransferLog(match_result_id=result.id,raw_data_id=gap_raw,
                             from_clean_job_id=target.id,to_clean_job_id=job_id)
    db.add(returned)
    db.delete(result)  # A genuine gap after returning belongs to the source again.
    db.commit()
    assert missing_match_raw_ids(db,job_id).count()==1
    assert _progress_stats(db)['transferred_out']==0
    db.add(MatchTransferLog(match_result_id=123,raw_data_id=gap_raw,from_clean_job_id=job_id,to_clean_job_id=target.id))
    db.commit()
    assert missing_match_raw_ids(db,job_id).count()==0
    assert _progress_stats(db)['transferred_out']==1
