"""移动电源 10 月历史型号回填脚本的候选解析测试。"""
from app.models.schemas import HistoricalMapping, ModelRecord
from app.scripts.repair_power_bank_202610 import plan_history_links


def _model(db, *, brand, code, name=None, category="power_bank", status="active"):
    model = ModelRecord(
        brand_code=brand,
        model_code=code,
        model_name=name or code,
        brand_name=brand,
        category_code=category,
        status=status,
    )
    db.add(model)
    db.flush()
    return model


def _history(db, *, brand, code=None, name=None, category="power_bank", model_id=None, month="2026-10"):
    row = HistoricalMapping(
        platform="tmall",
        item_id=f"item-{brand}-{code or name}",
        item_name="充电宝",
        item_name_norm="充电宝",
        year=2026,
        month_num=10,
        month=month,
        category_code=category,
        brand_code_raw=brand,
        brand_raw=brand,
        model_code_raw=code,
        model_code=code,
        model_text=name or code,
        model_id=model_id,
        match_key_type="item_id",
        raw_payload={},
    )
    db.add(row)
    db.flush()
    return row


def test_plan_history_links_resolves_unique_model_in_category(db):
    model = _model(db, brand="ANKER", code="A1")
    linked = _history(db, brand="ANKER", code="A1")
    already = _history(db, brand="ANKER", code="A1", model_id=model.id)
    db.commit()

    plan = plan_history_links(db, category_code="power_bank", month="2026-10")

    assert plan["links"] == {linked.id: model.id}
    assert plan["reasons"]["already_linked"] == 1
    assert plan["reasons"]["unique_exact"] == 1


def test_plan_history_links_skips_other_category_models_and_rows(db):
    _model(db, brand="ANKER", code="A1", category="smartwatch")
    other_category_history = _history(db, brand="ANKER", code="A1", category="smartwatch")
    db.commit()

    plan = plan_history_links(db, category_code="power_bank", month="2026-10")

    assert plan["links"] == {}
    assert plan["rows_scanned"] == 0
    assert other_category_history.id not in plan["links"]


def test_plan_history_links_skips_ambiguous_and_missing_models(db):
    _model(db, brand="ANKER", code="A1", name="One")
    _model(db, brand="ANKER", code="A1", name="Two")
    ambiguous = _history(db, brand="ANKER", code="A1")
    missing = _history(db, brand="BASEUS", code="B9")
    db.commit()

    plan = plan_history_links(db, category_code="power_bank", month="2026-10")

    assert ambiguous.id not in plan["links"]
    assert missing.id not in plan["links"]
    assert plan["reasons"]["ambiguous_model"] == 1
    assert plan["reasons"]["model_not_in_current_library"] == 1


def test_plan_history_links_includes_null_category_history(db):
    model = _model(db, brand="ANKER", code="A1")
    null_category = _history(db, brand="ANKER", code="A1", category=None)
    db.commit()

    plan = plan_history_links(db, category_code="power_bank", month="2026-10")

    assert plan["links"] == {null_category.id: model.id}


def test_apply_history_links_updates_model_id(db):
    model = _model(db, brand="ANKER", code="A1")
    history = _history(db, brand="ANKER", code="A1")
    db.commit()

    from app.scripts.repair_power_bank_202610 import apply_history_links

    assert apply_history_links(db, {history.id: model.id}) == 1
    db.expire_all()
    assert db.get(HistoricalMapping, history.id).model_id == model.id


def test_plan_rebuild_only_targets_pending_text_only_and_skips_published(db):
    from app.models.schemas import CleanJobRecord, MatchResult
    from app.scripts.repair_power_bank_202610 import plan_rebuild

    job = CleanJobRecord(file_ids=[], rules={}, status="done", category_code="power_bank")
    db.add(job)
    db.flush()
    pending = MatchResult(clean_job_id=job.id, raw_data_id=101, match_status="pending")
    text_only = MatchResult(clean_job_id=job.id, raw_data_id=102, match_status="text_only")
    confirmed = MatchResult(clean_job_id=job.id, raw_data_id=103, match_status="confirmed")
    published = MatchResult(clean_job_id=job.id, raw_data_id=104, match_status="pending")
    db.add_all([pending, text_only, confirmed, published])
    db.commit()

    plan = plan_rebuild(db, [job.id], {published.id})

    assert plan["by_job"][job.id] == [101, 102]
    assert plan["rows"] == 2
    assert plan["skipped_published"] == 1


def test_plan_history_links_by_model_name_when_code_is_empty(db):
    model = ModelRecord(
        brand_code="ANKER", model_code=None, model_name="A1287",
        brand_name="ANKER", category_code="power_bank", status="active",
    )
    db.add(model)
    db.flush()
    history = _history(db, brand="ANKER", code=None, name="A1287")
    db.commit()

    plan = plan_history_links(db, category_code="power_bank", month="2026-10")

    assert plan["links"] == {history.id: model.id}


def test_plan_history_links_falls_back_to_brand_level_empty_model(db):
    model = _model(db, brand="图欧索", code=None, name="无型号")
    empty_history = _history(db, brand="图欧索")
    pending_history = _history(db, brand="图欧索", code="待补", name="待补")
    db.commit()

    plan = plan_history_links(db, category_code="power_bank", month="2026-10")

    assert plan["links"] == {
        empty_history.id: model.id,
        pending_history.id: model.id,
    }
    assert plan["reasons"]["brand_level_empty_model"] == 2


def test_plan_history_links_skips_brand_fallback_when_brand_has_other_models(db):
    _model(db, brand="图欧索", code=None, name="无型号")
    _model(db, brand="图欧索", code="A1")
    history = _history(db, brand="图欧索")
    db.commit()

    plan = plan_history_links(db, category_code="power_bank", month="2026-10")

    assert plan["links"] == {}
    assert plan["reasons"]["missing_model_identity"] == 1
