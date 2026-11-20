import os

# Refuse application imports unless both global database engines are isolated.
for key in ('DATABASE_URL', 'ANALYTICS_DATABASE_URL'):
    if not os.environ.get(key, '').startswith('sqlite:'):
        raise SystemExit(f'{key} must explicitly point to an isolated SQLite database')
for key in ('UPLOAD_DIR', 'EXPORT_DIR'):
    if not os.environ.get(key):
        raise SystemExit(f'{key} must explicitly point to a disposable directory')

import asyncio
import io
import inspect
import json
import time
from collections import Counter
from types import SimpleNamespace

import pandas as pd
from fastapi import UploadFile
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.concurrency import run_in_threadpool

from app.models.schemas import Base, Category, AttrRule, MatchResultAttr, MatchResult, ModelRecord
from app.api.match_api import _run_batch_confirm, _run_batch_ignore, _run_batch_exclude
from app.api.metadata import preview_metadata
from app.services.attribute_matcher import run_attribute_matching
from tests.test_match_api import _seed_batch_confirm_rows


def database():
    engine = create_engine('sqlite:///:memory:', poolclass=StaticPool,
                           connect_args={'check_same_thread': False})
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, autoflush=False)()


def counter(engine, session):
    result = Counter()
    def execute(conn, cursor, statement, params, context, many):
        result['sql_calls'] += 1
        result[statement.lstrip().split()[0].lower()] += 1
        if 'FROM categories' in statement:
            result['category_selects'] += 1
        if statement.lstrip().startswith('INSERT INTO match_result_attrs'):
            result['attribute_insert_calls'] += 1
    def commit(session):
        result['commits'] += 1
    event.listen(engine, 'before_cursor_execute', execute)
    event.listen(session, 'after_commit', commit)
    return result


output = {'environment': 'isolated SQLite; production autoflush=False and expire_on_commit=True'}
for count in [10, 100, 500]:
    for name, action in [('batch_confirm', _run_batch_confirm), ('batch_ignore', _run_batch_ignore),
                         ('batch_exclude', _run_batch_exclude)]:
        engine, db = database()
        job, candidate, selected, *targets = _seed_batch_confirm_rows(db, row_count=count)
        job_id = job.id
        # Endpoints fetch the selected model and target list immediately before the helper.
        selected = db.query(ModelRecord).filter(ModelRecord.id == selected.id).first()
        targets = db.query(MatchResult).filter(MatchResult.clean_job_id == job_id).all()
        metrics = counter(engine, db)
        started = time.perf_counter()
        if name == 'batch_confirm':
            result = action(db, job_id, targets, selected)
        elif name == 'batch_exclude':
            result = action(db, job_id, targets, 'probe')
        else:
            result = action(db, targets, 'probe')
        elapsed = time.perf_counter() - started
        assert result['success'] == count and result['failed'] == 0, result
        output[f'{name}_{count}'] = {**metrics, 'elapsed_seconds': round(elapsed, 4),
                                    'success': result['success']}
        db.close()
        engine.dispose()

engine, db = database()
job, candidate, selected, *targets = _seed_batch_confirm_rows(db, row_count=1000)
db.add(AttrRule(keyword='批量', match_type='contains', attr_name='类型', attr_value='probe'))
db.commit()
ids = [target.id for target in targets]
metrics = counter(engine, db)
started = time.perf_counter()
result = run_attribute_matching(db, ids)
elapsed = time.perf_counter() - started
observed = dict(metrics)
assert db.query(MatchResultAttr).count() == 1000
output['attribute_matching_1000'] = {**observed, **result, 'elapsed_seconds': round(elapsed, 4)}
db.close()
engine.dispose()

async def preview_probe(count):
    engine, db = database()
    db.add(Category(code='probe', name='probe'))
    db.commit()
    buf = io.BytesIO()
    pd.DataFrame([{'品类码': 'probe', '属性字段名称': f'属性{i}', '字段类型': '文本型'}
                  for i in range(count)]).to_excel(buf, index=False, sheet_name='元数据')
    file = UploadFile(file=io.BytesIO(buf.getvalue()), filename='probe.xlsx')
    metrics = counter(engine, db)
    delays = []
    stop = False
    async def heartbeat():
        while not stop:
            start = time.perf_counter()
            await asyncio.sleep(.01)
            delays.append(time.perf_counter() - start)
    task = asyncio.create_task(heartbeat())
    await asyncio.sleep(0)
    started = time.perf_counter()
    args = dict(file=file, db=db, current_user=SimpleNamespace(is_admin=1))
    if inspect.iscoroutinefunction(preview_metadata):
        result = await preview_metadata(**args)
    else:
        # Same worker dispatch as a synchronous FastAPI endpoint.
        result = await run_in_threadpool(preview_metadata, **args)
    elapsed = time.perf_counter() - started
    await asyncio.sleep(.02)
    stop = True
    await task
    assert result['valid_rows'] == count
    output[f'metadata_preview_{count}'] = {**metrics, 'valid_rows': count,
        'elapsed_seconds': round(elapsed, 4), 'max_10ms_heartbeat_interval_seconds': round(max(delays), 4)}
    db.close()
    engine.dispose()

asyncio.run(preview_probe(1000))
asyncio.run(preview_probe(10000))
print(json.dumps(output, ensure_ascii=False, indent=2))
