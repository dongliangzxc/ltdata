from collections import Counter

import pytest
from sqlalchemy import event

from app.models.schemas import ItemUrlMapping, MatchResult, MatchResultAttr, ModelRecord, RawDataRecord
from app.services.batch_review_confirm import confirm_review_batches
from tests.test_match_api import _seed_batch_confirm_rows, match_client
from app.models.schemas import CleanJobRecord


def _seed(db, count):
    db.autoflush = False
    job, _candidate, selected, *targets = _seed_batch_confirm_rows(db, row_count=count)
    return job.id, selected.id, [target.id for target in targets]


def test_500_confirmations_use_bounded_queries_and_commits(db):
    job_id, model_id, ids = _seed(db, 500)
    metrics = Counter()

    def execute(conn, cursor, statement, parameters, context, many):
        metrics["sql"] += 1

    def commit(session):
        metrics["commit"] += 1

    event.listen(db.bind, "before_cursor_execute", execute)
    event.listen(db, "after_commit", commit)
    try:
        ok, failures = confirm_review_batches(db, job_id, ids, model_id)
    finally:
        event.remove(db.bind, "before_cursor_execute", execute)
        event.remove(db, "after_commit", commit)
    assert ok == ids and failures == []
    assert metrics["sql"] <= 40
    assert metrics["commit"] == 5
    assert db.query(ItemUrlMapping).count() == 500
    assert db.query(MatchResult).filter_by(match_status="confirmed", model_id=model_id).count() == 500


def test_existing_mapping_is_overwritten_while_invalid_and_stale_rows_are_reported(db):
    job_id, model_id, ids = _seed(db, 5)
    targets = db.query(MatchResult).order_by(MatchResult.id).all()
    old_model_id = targets[0].model_id
    targets[0].review_note = "old note"
    targets[0].dispute_reason = "old reason"
    targets[1].match_status = "excluded"
    targets[2].brand_identified = 0
    raw = db.get(RawDataRecord, targets[3].raw_data_id)
    db.add(ItemUrlMapping(platform=raw.platform, item_id=raw.item_id, model_id=old_model_id))
    for target in targets:
        db.add(MatchResultAttr(match_result_id=target.id, attr_name="old", attr_value="keep if failed"))
    db.commit()

    ok, failures = confirm_review_batches(db, job_id, ids, model_id)
    assert ok == [ids[0], ids[3], ids[4]]
    assert [f["id"] for f in failures] == ids[1:3]
    assert [f["reason"] for f in failures[:2]] == ["状态已变更", "目标型号无效"]
    first = db.get(MatchResult, ids[0])
    assert first.prev_model_id == old_model_id and first.prev_match_status == "pending"
    assert first.prev_review_note == "old note" and first.prev_dispute_reason == "old reason"
    assert first.review_note is None and first.dispute_reason is None
    assert first.match_source == "manual" and first.matched_by == "manual"
    assert {a.match_result_id for a in db.query(MatchResultAttr)} == set(ids[1:3])
    assert db.query(ItemUrlMapping).filter_by(item_id=raw.item_id).one().model_id == model_id


def test_duplicate_ids_report_stale_after_first_success(db):
    job_id, model_id, ids = _seed(db, 2)
    ok, failures = confirm_review_batches(db, job_id, [ids[1], ids[0], ids[1]], model_id)
    assert ok == [ids[1], ids[0]]
    assert failures == [{"id": ids[1], "item_name": "批量商品1", "reason": "状态已变更"}]


def test_same_url_only_inserts_once_and_last_input_values_win(db):
    job_id, model_id, ids = _seed(db, 2)
    targets = db.query(MatchResult).order_by(MatchResult.id).all()
    first, second = [db.get(RawDataRecord, row.raw_data_id) for row in targets]
    second.item_id = first.item_id
    second.item_url = "https://example.test/last"
    second.price = 123
    db.commit()
    ok, failures = confirm_review_batches(db, job_id, ids, model_id)
    assert ok == ids and not failures
    mapping = db.query(ItemUrlMapping).one()
    assert mapping.item_url == "https://example.test/last" and float(mapping.price) == 123
    assert mapping.model_id == model_id and mapping.source == "match_confirm"


def test_null_mapping_is_filled_but_missing_url_does_not_create_mapping(db):
    job_id, model_id, ids = _seed(db, 2)
    targets = db.query(MatchResult).order_by(MatchResult.id).all()
    first, second = [db.get(RawDataRecord, row.raw_data_id) for row in targets]
    db.add(ItemUrlMapping(platform=first.platform, item_id=first.item_id, model_id=None))
    second.item_url = None
    db.commit()
    ok, failures = confirm_review_batches(db, job_id, ids, model_id)
    assert ok == ids and not failures
    assert db.query(ItemUrlMapping).one().model_id == model_id


def test_current_state_is_reloaded_instead_of_overwriting_stale_targets(db):
    job_id, model_id, ids = _seed(db, 2)
    cached = db.get(MatchResult, ids[0])
    db.query(MatchResult).filter_by(id=ids[0]).update({"match_status": "ignored"}, synchronize_session=False)
    assert cached.match_status == "pending"
    ok, failures = confirm_review_batches(db, job_id, ids, model_id)
    assert ok == [ids[1]] and failures[0]["reason"] == "状态已变更"
    assert db.get(MatchResult, ids[0]).match_status == "ignored"


@pytest.mark.parametrize("failure_stage", ["write", "commit"])
def test_bad_row_rolls_back_its_changes_and_other_rows_still_confirm(db, monkeypatch, failure_stage):
    job_id, model_id, ids = _seed(db, 5)
    bad_id = ids[2]
    raw_id = db.get(MatchResult, bad_id).raw_data_id
    bad_item_id = db.get(RawDataRecord, raw_id).item_id
    db.add(MatchResultAttr(match_result_id=bad_id, attr_name="old", attr_value="preserved"))
    db.commit()

    def fail_write(conn, cursor, statement, parameters, context, many):
        if statement.startswith("INSERT INTO item_url_mappings") and bad_item_id in str(parameters):
            raise RuntimeError("synthetic write failure")

    original_commit = db.commit

    def fail_commit():
        if db.query(MatchResult.match_status).filter_by(id=bad_id).scalar() == "confirmed":
            raise RuntimeError("synthetic commit failure")
        original_commit()

    if failure_stage == "write":
        event.listen(db.bind, "before_cursor_execute", fail_write)
    else:
        monkeypatch.setattr(db, "commit", fail_commit)
    try:
        ok, failures = confirm_review_batches(db, job_id, ids, model_id)
    finally:
        if failure_stage == "write":
            event.remove(db.bind, "before_cursor_execute", fail_write)
    assert ok == [ids[0], ids[1], ids[3], ids[4]]
    assert failures == [{"id": bad_id, "item_name": "批量商品2", "reason": "系统错误"}]
    assert db.get(MatchResult, bad_id).match_status == "pending"
    assert db.query(ItemUrlMapping).count() == 4
    assert db.query(MatchResultAttr).one().attr_value == "preserved"


def test_request_does_not_confirm_ids_from_a_different_job(db):
    job_id, model_id, ids = _seed(db, 1)
    ok, failures = confirm_review_batches(db, job_id + 1, ids, model_id)
    assert not ok and failures[0]["reason"] == "状态已变更"
    assert db.get(MatchResult, ids[0]).match_status == "pending"


def test_later_failed_chunk_keeps_previously_committed_successes(db, monkeypatch):
    job_id, model_id, ids = _seed(db, 101)
    bad_id = ids[-1]
    original_commit = db.commit

    def fail_commit():
        if db.query(MatchResult.match_status).filter_by(id=bad_id).scalar() == "confirmed":
            raise RuntimeError("failed final chunk")
        original_commit()

    monkeypatch.setattr(db, "commit", fail_commit)
    ok, failures = confirm_review_batches(db, job_id, ids, model_id)
    assert ok == ids[:-1] and failures[0]["id"] == bad_id
    assert db.query(MatchResult).filter_by(match_status="confirmed").count() == 100
    assert db.get(MatchResult, bad_id).match_status == "pending"


def test_api_helper_runs_attribute_and_price_hooks_only_for_successful_ids(db, monkeypatch):
    from app.api.match_api import _run_batch_confirm
    job_id, model_id, ids = _seed(db, 2)
    db.query(MatchResult).filter_by(id=ids[1]).update({"brand_identified": 0})
    db.commit()
    calls = []
    monkeypatch.setattr("app.services.attribute_matcher.run_attribute_matching",
                        lambda session, match_ids: calls.append(("attrs", match_ids)))
    monkeypatch.setattr("app.api.match_api.audit_price",
                        lambda session, match_ids: calls.append(("price", match_ids)))
    result = _run_batch_confirm(db, job_id, db.query(MatchResult).order_by(MatchResult.id).all(),
                                db.get(ModelRecord, model_id))
    assert result["success"] == 1 and result["failed"] == 1
    assert calls == [("attrs", [ids[0]]), ("price", [ids[0]])]


@pytest.mark.parametrize("mode", ["ids", "filter"])
@pytest.mark.parametrize("old_brand", ["新东方", "文曲星"])
def test_manual_batch_overrides_brand_or_category_mapping_without_changing_other_tasks(
    db, match_client, monkeypatch, mode, old_brand,
):
    monkeypatch.setattr("app.api.match_api.audit_price", lambda *_args, **_kwargs: None)
    job_id, model_id, ids = _seed(db, 1)
    target = db.get(MatchResult, ids[0])
    old_model_id = target.model_id
    old_model = db.get(ModelRecord, old_model_id)
    old_model.brand_code = old_brand
    old_model.model_code = None
    old_model.category_code = "dict_pen"
    chosen = db.get(ModelRecord, model_id)
    chosen.brand_code = "新东方"
    chosen.model_code = "XDF-T2"
    chosen.category_code = "word_card"
    db.get(CleanJobRecord, job_id).category_code = "word_card"
    raw = db.get(RawDataRecord, target.raw_data_id)
    mapping = ItemUrlMapping(platform=raw.platform, item_id=raw.item_id, item_url=raw.item_url,
                             model_id=old_model_id, brand_code=old_brand, category_code="dict_pen", source="manual")
    other_job = CleanJobRecord(status="reviewing", category_code="dict_pen", file_ids=[])
    db.add_all([mapping, other_job])
    db.flush()
    other = MatchResult(clean_job_id=other_job.id, raw_data_id=raw.id, model_id=old_model_id,
                        match_status="confirmed", matched_by="manual")
    db.add(other)
    db.commit()
    mapping_id, other_id = mapping.id, other.id
    payload = {"mode": mode, "model_id": model_id}
    payload.update({"ids": ids} if mode == "ids" else {"filter": {"tab": "pending"}})

    response = match_client.post(f"/api/match/{job_id}/batch-confirm", json=payload)

    assert response.status_code == 200, response.text
    assert response.json()["success"] == 1 and response.json()["failed"] == 0
    db.expire_all()
    updated = db.get(ItemUrlMapping, mapping_id)
    assert updated.model_id == model_id and updated.brand_code == "新东方"
    assert updated.category_code == "word_card" and updated.source == "match_confirm"
    assert db.query(ItemUrlMapping).count() == 1
    assert db.get(MatchResult, ids[0]).model_id == model_id
    assert db.get(MatchResult, ids[0]).prev_model_id == old_model_id
    assert db.get(MatchResult, other_id).model_id == old_model_id
    assert db.get(MatchResult, other_id).match_status == "confirmed"
    assert db.get(ModelRecord, old_model_id).category_code == "dict_pen"


def test_failed_confirmation_commit_preserves_the_previous_mapping(db, monkeypatch):
    job_id, model_id, ids = _seed(db, 3)
    bad_id = ids[1]
    target = db.get(MatchResult, bad_id)
    raw = db.get(RawDataRecord, target.raw_data_id)
    mapping = ItemUrlMapping(platform=raw.platform, item_id=raw.item_id, model_id=target.model_id,
                             brand_code="old brand", category_code="dict_pen", source="manual")
    db.add(mapping)
    db.commit()
    mapping_id, old_model_id = mapping.id, mapping.model_id
    original_commit = db.commit

    def fail_commit():
        if db.query(MatchResult.match_status).filter_by(id=bad_id).scalar() == "confirmed":
            raise RuntimeError("synthetic overwrite commit failure")
        original_commit()

    monkeypatch.setattr(db, "commit", fail_commit)
    ok, failures = confirm_review_batches(db, job_id, ids, model_id)
    assert ok == [ids[0], ids[2]] and failures[0]["id"] == bad_id
    db.expire_all()
    existing = db.get(ItemUrlMapping, mapping_id)
    assert existing.model_id == old_model_id and existing.brand_code == "old brand"
    assert existing.category_code == "dict_pen" and existing.source == "manual"
    assert db.get(MatchResult, bad_id).match_status == "pending"
