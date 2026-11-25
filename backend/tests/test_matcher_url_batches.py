"""Task-scoped URL reads preserve matching decisions and reuse bounded caches."""

import pytest
from sqlalchemy import event

from app.models.schemas import (
    CleanedDataRecord, CleanJobRecord, ItemUrlMapping, MatchResult,
    ModelRecord, RawDataRecord, UploadFileRecord,
)
from app.services import matcher, rawdata_cache


@pytest.fixture
def mapping_reads(db):
    statements = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        # Track the expensive cached mapping columns separately from the live
        # status reads (covered by the enable/disable regression tests).
        if (statement.lstrip().upper().startswith("SELECT") and "FROM item_url_mappings" in statement
                and "item_url_mappings.is_enabled" not in statement):
            statements.append((statement, parameters))

    engine = db.get_bind()
    event.listen(engine, "before_cursor_execute", capture)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", capture)


@pytest.fixture
def enabled_cache(monkeypatch):
    monkeypatch.setattr(rawdata_cache, "_enabled", True)
    rawdata_cache.invalidate_rawdata_cache()
    try:
        yield
    finally:
        rawdata_cache.invalidate_rawdata_cache()


def _model(db, *, category="headphone", brand="SONY", code="WH-1000XM5", status="active"):
    model = ModelRecord(category_code=category, brand_code=brand, brand_name=brand,
                        model_code=code, status=status)
    db.add(model)
    db.flush()
    return model


def _job(db, *, item_url, ignored=False):
    upload = UploadFileRecord(filename="url-batches.xlsx", status="done")
    db.add(upload)
    db.flush()
    # Deliberately different from the URL key: S0 must still use the parsed URL.
    raw = RawDataRecord(file_id=upload.id, platform="wrong", item_id="wrong",
                        item_url=item_url, item_name="unknown", brand_raw="unknown")
    job = CleanJobRecord(file_ids=[upload.id], category_code="headphone", status="done")
    db.add_all([raw, job])
    db.flush()
    db.add(CleanedDataRecord(raw_data_id=raw.id, clean_job_id=job.id, platform="wrong",
                             item_id="wrong", item_url=item_url,
                             item_name=raw.item_name, brand_raw=raw.brand_raw))
    result = MatchResult(raw_data_id=raw.id, clean_job_id=job.id,
                         match_status="ignored" if ignored else "pending", matched_by="manual")
    db.add(result)
    db.flush()
    ids = job.id, result.id
    db.commit()
    return ids


def test_scoped_maps_match_full_map_decisions_without_unrelated_rows(db, mapping_reads):
    good = _model(db)
    foreign = _model(db, category="camera", brand="DJI", code="Osmo-6")
    inactive = _model(db, code="inactive", status="inactive")
    placeholder = _model(db, brand="其他", code=None)
    brand_only = _model(db, code=None)
    db.add_all([
        ItemUrlMapping(platform="jd", item_id="direct", model_id=good.id, brand_code="SONY"),
        ItemUrlMapping(platform="jd", item_id="foreign", model_id=foreign.id, brand_code="DJI",
                       category_code="camera"),
        ItemUrlMapping(platform="jd", item_id="inactive", model_id=inactive.id, brand_code="SONY"),
        ItemUrlMapping(platform="jd", item_id="placeholder", model_id=placeholder.id, brand_code="其他"),
        ItemUrlMapping(platform="jd", item_id="brand", model_id=None, brand_code="SONY"),
        ItemUrlMapping(platform="jd", item_id="brand-only", model_id=brand_only.id, brand_code="SONY"),
        ItemUrlMapping(platform="jd", item_id="unrelated", model_id=good.id),
        ItemUrlMapping(platform="tmall", item_id="direct", model_id=foreign.id),
    ])
    db.commit()
    keys = {("jd", item_id) for item_id in
            ["direct", "foreign", "inactive", "placeholder", "brand", "brand-only", "missing"]}
    # Reference is the previous full-table algorithm, restricted only at comparison time.
    reusable = {good.id, brand_only.id}
    full_url, full_brand = {}, {}
    for row in db.query(ItemUrlMapping).all():
        if row.model_id and row.model_id in reusable:
            full_url[(row.platform, row.item_id)] = row.model_id
        elif row.brand_code:
            full_brand[(row.platform, row.item_id)] = row.brand_code
    mapping_reads.clear()

    ctx = matcher._load_match_context(db, "headphone", keys)

    assert ctx.url_map == {key: value for key, value in full_url.items() if key in keys}
    assert ctx.url_brand_map == {key: value for key, value in full_brand.items() if key in keys}
    assert ("jd", "foreign") in ctx.url_brand_map
    assert len(mapping_reads) == 1
    sql, params = mapping_reads[0]
    assert "WHERE item_url_mappings.platform =" in sql and "item_url_mappings.item_id IN" in sql
    assert "category_code" not in sql
    assert set(params) == {"jd", *(item_id for platform, item_id in keys)}


def test_large_requests_deduplicate_keys_and_read_in_platform_batches(db, mapping_reads):
    db.bulk_insert_mappings(ItemUrlMapping, [
        dict(platform="jd", item_id=str(i), brand_code="SONY") for i in range(1005)
    ] + [dict(platform="tmall", item_id="1", brand_code="APPLE"),
         dict(platform="taobao", item_id="unrelated", brand_code="OTHER")])
    db.commit()
    keys = [("jd", str(i)) for i in range(1005)] + [("tmall", "1")]

    url_map, brand_map = matcher._build_url_maps(db, set(), reversed(keys * 2))

    assert url_map == {}
    assert len(brand_map) == 1006
    assert brand_map[("jd", "1")] == "SONY"
    assert brand_map[("tmall", "1")] == "APPLE"
    assert len(mapping_reads) == 3
    assert sorted(len(params) - 1 for sql, params in mapping_reads) == [1, 5, 1000]
    assert all("WHERE" in sql and "item_url_mappings.item_id IN" in sql for sql, params in mapping_reads)


def test_cached_batches_reuse_positive_and_negative_results_and_invalidate(db, mapping_reads, enabled_cache):
    db.add(ItemUrlMapping(platform="jd", item_id="found", brand_code="SONY"))
    db.commit()
    keys = [("jd", "found"), ("jd", "missing")]

    assert matcher._build_url_maps(db, set(), keys)[1] == {("jd", "found"): "SONY"}
    assert matcher._build_url_maps(db, set(), reversed(keys * 2))[1] == {("jd", "found"): "SONY"}
    # An entirely missing batch must also be cached, avoiding repeated empty reads.
    assert matcher._build_url_maps(db, set(), [("tmall", "missing")]) == ({}, {})
    assert matcher._build_url_maps(db, set(), [("tmall", "missing")]) == ({}, {})
    assert len(mapping_reads) == 2

    db.query(ItemUrlMapping).filter_by(platform="jd", item_id="found").update({"brand_code": "APPLE"})
    db.add(ItemUrlMapping(platform="jd", item_id="missing", brand_code="DJI"))
    db.commit()
    rawdata_cache.invalidate_rawdata_cache()
    assert matcher._build_url_maps(db, set(), keys)[1] == {
        ("jd", "found"): "APPLE", ("jd", "missing"): "DJI",
    }
    assert len(mapping_reads) == 3


def test_cached_rows_expire(db, mapping_reads, enabled_cache, monkeypatch):
    now = [0.0]
    monkeypatch.setattr(rawdata_cache.time, "monotonic", lambda: now[0])
    keys = [("jd", "new")]
    assert matcher._build_url_maps(db, set(), keys) == ({}, {})
    db.add(ItemUrlMapping(platform="jd", item_id="new", brand_code="SONY"))
    db.commit()
    now[0] = matcher.URL_MAP_CACHE_TTL - 1
    assert matcher._build_url_maps(db, set(), keys) == ({}, {})
    assert len(mapping_reads) == 1
    now[0] = matcher.URL_MAP_CACHE_TTL + 1
    assert matcher._build_url_maps(db, set(), keys)[1] == {("jd", "new"): "SONY"}
    assert len(mapping_reads) == 2


def test_cached_raw_rows_apply_current_category_and_model_status(db, mapping_reads, enabled_cache):
    model = _model(db)
    db.add(ItemUrlMapping(platform="jd", item_id="1", model_id=model.id, brand_code="SONY"))
    db.commit()
    keys = [("jd", "1")]
    assert matcher._load_match_context(db, "headphone", keys).url_map == {("jd", "1"): model.id}
    foreign = matcher._load_match_context(db, "camera", keys)
    assert foreign.url_map == {}
    assert foreign.url_brand_map == {("jd", "1"): "SONY"}
    model.status = "inactive"
    db.commit()
    inactive = matcher._load_match_context(db, "headphone", keys)
    assert inactive.url_map == {}
    assert inactive.url_brand_map == {("jd", "1"): "SONY"}
    assert len(mapping_reads) == 1


@pytest.mark.parametrize("single", [False, True])
def test_matching_entry_points_only_request_parsed_url_key(db, mapping_reads, single):
    model = _model(db)
    db.add_all([
        ItemUrlMapping(platform="jd", item_id="123", model_id=model.id),
        ItemUrlMapping(platform="jd", item_id="unrelated", brand_code="OTHER"),
    ])
    job_id, result_id = _job(db, item_url="https://item.jd.com/123.html")
    if single:
        result = matcher.run_match_for_result(db, result_id, commit=False)
    else:
        assert matcher.run_match(db, job_id, commit=False)["matched"] == 1
        result = db.query(MatchResult).filter_by(clean_job_id=job_id).one()
    assert (result.match_status, result.model_id, result.match_source) == ("url_matched", model.id, "s0")
    assert len(mapping_reads) == 1
    assert mapping_reads[0][1] == ("jd", "123")


@pytest.mark.parametrize("item_url", [None, "https://example.com/unknown"])
@pytest.mark.parametrize("single", [False, True])
def test_unparsable_urls_do_not_query_mapping_table(db, mapping_reads, item_url, single):
    job_id, result_id = _job(db, item_url=item_url)
    if single:
        result = matcher.run_match_for_result(db, result_id)
    else:
        matcher.run_match(db, job_id)
        result = db.query(MatchResult).filter_by(clean_job_id=job_id).one()
    assert result.match_status == "pending"
    assert mapping_reads == []


def test_empty_and_ignored_jobs_do_not_query_mapping_table(db, mapping_reads):
    job = CleanJobRecord(file_ids=[], category_code="headphone", status="done")
    db.add(job)
    db.commit()
    assert matcher.run_match(db, job.id)["total"] == 0
    ignored_job_id, _ = _job(db, item_url="https://item.jd.com/ignored.html", ignored=True)
    assert matcher.run_match(db, ignored_job_id)["ignored"] == 1
    assert db.query(MatchResult).filter_by(clean_job_id=ignored_job_id).one().match_status == "ignored"
    assert mapping_reads == []
