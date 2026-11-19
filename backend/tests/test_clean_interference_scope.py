"""Category-scoped reads preserve interference matching and cache contracts."""
from sqlalchemy import event
from sqlalchemy.orm import Session
import pytest

from app.models.schemas import InterferenceLink, RawDataRecord, FilteredItem, CleanedDataRecord
from app.services import data_cleaner as cleaner, rawdata_cache
from tests.test_data_cleaner_batches import _seed


@pytest.fixture
def reads(db):
    statements = []
    def capture(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith('SELECT') and 'FROM interference_links' in statement:
            statements.append((statement, parameters))
    engine = db.get_bind()
    event.listen(engine, 'before_cursor_execute', capture)
    try:
        yield statements
    finally:
        event.remove(engine, 'before_cursor_execute', capture)


@pytest.fixture
def enabled_cache(monkeypatch):
    monkeypatch.setattr(rawdata_cache, '_enabled', True)
    rawdata_cache.invalidate_rawdata_cache()
    try:
        yield
    finally:
        rawdata_cache.invalidate_rawdata_cache()


def test_cold_read_is_filtered_in_database_and_does_not_load_foreign_orm_rows(db, reads):
    db.bulk_insert_mappings(InterferenceLink, [
        dict(category_code='camera', url=f'https://camera.example/{i}') for i in range(1200)
    ] + [dict(category_code='headphone', url=' HTTPS://ITEM.JD.COM/123.HTML '),
         dict(category_code='headphone', url='   ')])
    db.commit()
    assert cleaner._load_interference_links(db, 'headphone') == {
        'headphone': {'https://item.jd.com/123.html': ' HTTPS://ITEM.JD.COM/123.HTML '},
    }
    assert len(reads) == 1
    statement, parameters = reads[0]
    assert 'WHERE interference_links.category_code =' in statement
    assert parameters == ('headphone',)
    assert not any(isinstance(row, InterferenceLink) for row in db.identity_map.values())


@pytest.mark.parametrize('category', [None, ''])
def test_no_category_does_not_read_or_fall_back_to_global_scope(db, reads, category):
    db.add(InterferenceLink(category_code='headphone', url='blocked'))
    db.commit()
    assert cleaner._load_interference_links(db, category) == {}
    assert reads == []


def test_cache_is_separate_per_category_and_reuses_both_nonempty_and_empty_results(db, reads, enabled_cache):
    db.add_all([InterferenceLink(category_code='headphone', url='hp-block'),
                InterferenceLink(category_code='camera', url='camera-block')])
    db.commit()
    for _ in range(2):
        assert cleaner._load_interference_links(db, 'headphone') == {'headphone': {'hp-block': 'hp-block'}}
        assert cleaner._load_interference_links(db, 'camera') == {'camera': {'camera-block': 'camera-block'}}
        assert cleaner._load_interference_links(db, 'empty') == {}
    assert len(reads) == 3
    assert [params for _, params in reads] == [('headphone',), ('camera',), ('empty',)]


def test_scoped_cache_expires_with_existing_ttl(db, reads, enabled_cache, monkeypatch):
    now = [0.0]
    monkeypatch.setattr(rawdata_cache.time, 'monotonic', lambda: now[0])
    assert cleaner._load_interference_links(db, 'headphone') == {}
    db.add(InterferenceLink(category_code='headphone', url='new-link')); db.commit()
    now[0] = cleaner._RULES_CACHE_TTL - 1
    assert cleaner._load_interference_links(db, 'headphone') == {}
    assert len(reads) == 1
    now[0] = cleaner._RULES_CACHE_TTL + 1
    assert cleaner._load_interference_links(db, 'headphone') == {'headphone': {'new-link': 'new-link'}}
    assert len(reads) == 2


def test_existing_invalidation_refreshes_scoped_and_negative_cache_after_writes(db, reads, enabled_cache):
    assert cleaner._load_interference_links(db, 'headphone') == {}
    db.add(InterferenceLink(category_code='headphone', url='added')); db.commit()
    rawdata_cache.invalidate_rawdata_cache()
    assert cleaner._load_interference_links(db, 'headphone') == {'headphone': {'added': 'added'}}
    db.query(InterferenceLink).filter_by(category_code='headphone').update({'url': 'changed'}); db.commit()
    rawdata_cache.invalidate_rawdata_cache()
    assert cleaner._load_interference_links(db, 'headphone') == {'headphone': {'changed': 'changed'}}
    db.query(InterferenceLink).filter_by(category_code='headphone').delete(); db.commit()
    rawdata_cache.invalidate_rawdata_cache()
    assert cleaner._load_interference_links(db, 'headphone') == {}
    assert len(reads) == 4


def test_cached_values_work_after_loading_session_closes(db, reads, enabled_cache):
    db.add(InterferenceLink(category_code='headphone', url='blocked')); db.commit()
    value = cleaner._load_interference_links(db, 'headphone')
    bind = db.get_bind(); db.close()
    with Session(bind) as next_session:
        assert cleaner._load_interference_links(next_session, 'headphone') == value
    assert value == {'headphone': {'blocked': 'blocked'}}
    assert len(reads) == 1


def test_scoped_reads_preserve_legacy_normalization_substring_and_first_hit(db):
    library = [('camera', 'https://foreign.example/blocked'),
               ('headphone', 'short'),
               ('headphone', 'https://example.com/short/1234567890'),
               ('headphone', ' HTTPS://EXAMPLE.COM/Straße '),
               ('headphone', ' needle '),
               ('headphone', 'NEEDLE'),
               ('headphone', '   ')]
    db.add_all([InterferenceLink(category_code=category, url=url) for category, url in library]); db.commit()
    legacy = {}
    for category, url in library:
        key = url.casefold().strip()
        if key: legacy.setdefault(category, {})[key] = url
    scoped = cleaner._load_interference_links(db, 'headphone')
    assert scoped == {'headphone': legacy['headphone']}
    index = cleaner._build_interference_link_index(scoped, 'headphone')
    urls = [None, '', 'https://foreign.example/blocked',
            'HTTPS://EXAMPLE.COM/short/1234567890?tracking=1',
            'https://example.com/STRASSE?x=1', 'prefix NEEDLE suffix', 'nothing']
    for url in urls:
        expected = next((original for key, original in legacy['headphone'].items()
                         if key in (url or '').casefold().strip()), None)
        assert cleaner._matches_interference_links(RawDataRecord(item_url=url), index) == expected


def test_cleaning_passes_current_category_and_uses_it_across_batches(db, reads, monkeypatch):
    file_id, _, job_id = _seed(db, 4)
    db.query(RawDataRecord).filter_by(id=1).update({'item_url': 'https://hp.example/blocked?x=1'})
    db.query(RawDataRecord).filter_by(id=2).update({'item_url': 'https://camera.example/blocked'})
    db.query(RawDataRecord).filter_by(id=3).update({'item_url': 'HTTPS://HP.EXAMPLE/BLOCKED'})
    db.add_all([InterferenceLink(category_code='headphone', url='https://hp.example/blocked'),
                InterferenceLink(category_code='camera', url='https://camera.example/blocked')]); db.commit()
    monkeypatch.setattr(cleaner, '_CLEAN_BATCH_SIZE', 2)
    assert cleaner.run_clean(db, job_id, [file_id], {}, dispatch_category_code='headphone') == 2
    assert {r.raw_data_id for r in db.query(CleanedDataRecord)} == {2, 4}
    filtered = db.query(FilteredItem).all()
    assert {r.raw_data_id for r in filtered} == {1, 3}
    assert all(r.matched_reason == '命中干扰链接库：https://hp.example/blocked' for r in filtered)
    assert len(reads) == 1 and reads[0][1] == ('headphone',)


def test_cleaning_without_dispatch_category_skips_interference_query(db, reads):
    file_id, _, job_id = _seed(db, 1)
    db.query(RawDataRecord).update({'item_url': 'blocked'})
    db.add(InterferenceLink(category_code='headphone', url='blocked')); db.commit()
    assert cleaner.run_clean(db, job_id, [file_id], {}) == 1
    assert db.query(FilteredItem).count() == 0
    assert reads == []
