"""
S0.2 历史库匹配阶段单元测试
使用内存 SQLite，不依赖 MySQL。
"""
from app.models.schemas import (
    UploadFileRecord, RawDataRecord, CleanJobRecord, CleanedDataRecord,
    ModelRecord, MatchResult, HistoricalMapping, ItemUrlMapping,
)
from app.services.matcher import run_match


def _seed(db, *, platform="jd", item_id="12345", item_name="Sony HT-A7000 soundbar", item_url=None, month=202605, week=None):
    upload = UploadFileRecord(filename="t.xlsx", status="done", row_count=1)
    db.add(upload)
    db.flush()
    raw = RawDataRecord(
        file_id=upload.id,
        platform=platform,
        item_id=item_id,
        item_name=item_name,
        item_url=item_url,
        brand_raw="SONY",
        month=month,
        week=week,
    )
    db.add(raw)
    db.flush()
    job = CleanJobRecord(file_ids=[upload.id], rules={}, status="done", row_in=1, row_out=1)
    db.add(job)
    db.flush()
    cleaned = CleanedDataRecord(
        raw_data_id=raw.id,
        clean_job_id=job.id,
        platform=platform,
        item_id=item_id,
        item_name=item_name,
        item_url=item_url,
        brand_raw="SONY",
        month=month,
        week=week,
    )
    db.add(cleaned)
    db.flush()
    model = ModelRecord(
        brand_code="SONY",
        model_code=f"MODEL-{item_id}",
        model_name=f"Model {item_id}",
        category_code="soundbar",
    )
    db.add(model)
    db.flush()
    return job.id, model.id


def _add_history(db, *, platform="jd", item_id="12345", item_url=None, item_name="Sony HT-A7000 soundbar", year=2026, month_num=5, week=None, model_id=None, model_code="MODEL-12345"):
    row = HistoricalMapping(
        platform=platform,
        item_id=item_id,
        item_url=item_url,
        item_name=item_name,
        item_name_norm=" ".join(item_name.upper().split()),
        year=year,
        month_num=month_num,
        week=week,
        month=f"{year:04d}-{month_num:02d}",
        model_text=model_code,
        model_id=model_id,
        model_code=model_code,
        category_code="soundbar",
        match_key_type="item_id" if item_id else "item_url" if item_url else "item_name",
        raw_payload={"标题": item_name},
        import_batch="batch1",
    )
    db.add(row)
    return row


def test_s02_matches_by_platform_item_id_same_month(db):
    job_id, model_id = _seed(db, platform="jd", item_id="99999", month=202605)
    _add_history(db, platform="jd", item_id="99999", year=2026, month_num=5, model_id=model_id, model_code="MODEL-99999")
    db.commit()

    run_match(db, job_id)

    mr = db.query(MatchResult).filter(MatchResult.clean_job_id == job_id).first()
    assert mr is not None
    assert mr.match_source == "historical"
    assert mr.match_status == "matched"
    assert mr.model_id == model_id
    assert mr.brand_identified == 1


def test_s02_does_not_match_same_item_different_month(db):
    job_id, model_id = _seed(db, platform="jd", item_id="99999", item_name="unknown brand no text hit", month=202606)
    _add_history(db, platform="jd", item_id="99999", year=2026, month_num=5, model_id=model_id, model_code="MODEL-99999")
    db.commit()

    run_match(db, job_id)

    mr = db.query(MatchResult).filter(MatchResult.clean_job_id == job_id).first()
    assert mr is not None
    assert mr.match_source != "historical"


def test_s02_matches_by_parsed_url_item_id(db):
    job_id, model_id = _seed(
        db,
        platform="tmall",
        item_id=None,
        item_url="https://detail.tmall.com/item.htm?id=909868962326",
        item_name="history parsed url item",
        month=202605,
    )
    _add_history(db, platform="tmall", item_id="909868962326", year=2026, month_num=5, model_id=model_id, model_code="MODEL-12345")
    db.commit()

    run_match(db, job_id)

    mr = db.query(MatchResult).filter(MatchResult.clean_job_id == job_id).first()
    assert mr.match_source == "historical"
    assert mr.model_id == model_id


def test_s02_matches_by_item_url_when_no_item_id(db):
    url = "https://example.com/not-supported-url"
    job_id, model_id = _seed(db, platform="other", item_id=None, item_url=url, item_name="history url item", month=202605)
    _add_history(db, platform="other", item_id=None, item_url=url, item_name="different title", year=2026, month_num=5, model_id=model_id, model_code="MODEL-12345")
    db.commit()

    run_match(db, job_id)

    mr = db.query(MatchResult).filter(MatchResult.clean_job_id == job_id).first()
    assert mr.match_source == "historical"
    assert mr.model_id == model_id


def test_s02_matches_by_normalized_item_name_when_no_url_key(db):
    job_id, model_id = _seed(db, platform="jd", item_id=None, item_url=None, item_name="Sony   HT-A7000 Soundbar", month=202605)
    _add_history(db, platform="jd", item_id=None, item_url=None, item_name="SONY HT-A7000 SOUNDBAR", year=2026, month_num=5, model_id=model_id, model_code="MODEL-12345")
    db.commit()

    run_match(db, job_id)

    mr = db.query(MatchResult).filter(MatchResult.clean_job_id == job_id).first()
    assert mr.match_source == "historical"
    assert mr.model_id == model_id


def test_s02_matches_same_week_before_same_month(db):
    job_id, model_id = _seed(db, platform="jd", item_id="99999", month=202605, week="W21")
    older_model = ModelRecord(brand_code="SONY", model_code="MODEL-OLDER", model_name="Older", category_code="soundbar")
    db.add(older_model)
    db.flush()
    _add_history(db, platform="jd", item_id="99999", year=2026, month_num=5, week=None, model_id=older_model.id, model_code="MODEL-OLDER")
    _add_history(db, platform="jd", item_id="99999", year=2026, month_num=5, week="W21", model_id=model_id, model_code="MODEL-99999")
    db.commit()

    run_match(db, job_id)

    mr = db.query(MatchResult).filter(MatchResult.clean_job_id == job_id).first()
    assert mr.match_source == "historical"
    assert mr.model_id == model_id


def test_s02_prefers_item_id_month_fallback_before_item_url_week_hit(db):
    url = "https://example.com/conflicting-url"
    job_id, model_id = _seed(db, platform="jd", item_id="KEY-PRIORITY", item_url=url, month=202605, week="W21")
    url_model = ModelRecord(brand_code="SONY", model_code="MODEL-URL-WEEK", model_name="Url Week", category_code="soundbar")
    db.add(url_model)
    db.flush()
    _add_history(db, platform="jd", item_id="KEY-PRIORITY", item_url=None, year=2026, month_num=5, week=None, model_id=model_id, model_code="MODEL-KEY")
    _add_history(db, platform="jd", item_id=None, item_url=url, year=2026, month_num=5, week="W21", model_id=url_model.id, model_code="MODEL-URL-WEEK")
    db.commit()

    run_match(db, job_id)

    mr = db.query(MatchResult).filter(MatchResult.clean_job_id == job_id).first()
    assert mr.match_source == "historical"
    assert mr.model_id == model_id


def test_s02_no_match_when_not_in_table(db):
    """historical_mappings 为空时，S0.2 不命中，走后续阶段（pending）"""
    job_id, _ = _seed(db, platform="jd", item_id="88888", item_name="unknown brand XYZ no match")
    db.commit()

    run_match(db, job_id)

    mr = db.query(MatchResult).filter(MatchResult.clean_job_id == job_id).first()
    assert mr is not None
    assert mr.match_source != "historical"
    assert mr.match_status == "pending"


def test_s0_takes_precedence_over_s02(db):
    """同一商品既有 url_mapping(S0) 又有 historical_mapping(S0.2) → S0 优先"""
    job_id, model_id = _seed(
        db,
        platform="jd",
        item_id="77777",
        item_url="https://item.jd.com/77777.html",
        item_name="Sony HT-A3000 from url test",
        month=202605,
    )
    model2 = ModelRecord(brand_code="SONY", model_code="MODEL-URL", model_name="URL Model", category_code="soundbar")
    db.add(model2)
    db.flush()
    db.add(ItemUrlMapping(platform="jd", item_id="77777", model_id=model2.id))
    _add_history(db, platform="jd", item_id="77777", year=2026, month_num=5, model_id=model_id, model_code="MODEL-77777")
    db.commit()

    run_match(db, job_id)

    mr = db.query(MatchResult).filter(MatchResult.clean_job_id == job_id).first()
    assert mr.match_source == "s0"
    assert mr.model_id == model2.id


def test_s02_platform_case_insensitive(db):
    """historical_mappings 与 cleaned_data platform 大小写不一致也能命中"""
    job_id, model_id = _seed(db, platform="jd", item_id="66666", month=202605)
    _add_history(db, platform="JD", item_id="66666", year=2026, month_num=5, model_id=model_id, model_code="MODEL-66666")
    db.commit()

    run_match(db, job_id)

    mr = db.query(MatchResult).filter(MatchResult.clean_job_id == job_id).first()
    assert mr.match_source == "historical"


def test_s04_still_runs_when_item_not_in_historical(db):
    """
    item 完全不在历史库时，S4 正常执行（兜底行为不受影响）。
    使用 brand_raw=None 确保 S1/S2/S3 不识别品牌，让 S4 兜底触发。
    """
    long_model = ModelRecord(brand_code="XNCO", model_code="XM1000X", model_name="XM1000X", category_code="headphone")
    db.add(long_model)
    db.flush()

    upload = UploadFileRecord(filename="t.xlsx", status="done", row_count=1)
    db.add(upload)
    db.flush()
    raw = RawDataRecord(
        file_id=upload.id,
        platform="tmall",
        item_id="NEW-ITEM-999",
        item_name="新款XM1000X无线蓝牙耳机未知品牌",
        brand_raw=None,
        month=202605,
    )
    db.add(raw)
    db.flush()
    job = CleanJobRecord(file_ids=[upload.id], rules={}, status="done", row_in=1, row_out=1)
    db.add(job)
    db.flush()
    cleaned = CleanedDataRecord(
        raw_data_id=raw.id,
        clean_job_id=job.id,
        platform="tmall",
        item_id="NEW-ITEM-999",
        item_name="新款XM1000X无线蓝牙耳机未知品牌",
        brand_raw=None,
        month=202605,
    )
    db.add(cleaned)
    db.commit()

    run_match(db, job.id)

    mr = db.query(MatchResult).filter(MatchResult.clean_job_id == job.id).first()
    assert mr is not None
    assert mr.match_source == "s4"
    assert mr.model_id == long_model.id
