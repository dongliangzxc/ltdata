"""Bounded cleaning batches preserve rule priority, snapshot order and rollback."""

from copy import deepcopy

import pytest

from app.models.schemas import (
    CleanJobItemRecord, CleanJobRecord, CleanedDataRecord, DispatchBatch,
    DispatchItem, FilteredItem, InterferenceLink, InterventionRule,
    RawDataRecord, UploadFileRecord,
)
from app.services import data_cleaner


def _seed(db, count, *, snapshots=True):
    upload = UploadFileRecord(filename="batch-clean.xlsx", platform="jd", status="done")
    db.add(upload)
    db.flush()
    batch = DispatchBatch(file_id=upload.id, status="done")
    job = CleanJobRecord(file_ids=[upload.id], category_code="headphone", status="created",
                         rules={"dedup": True}, row_in=0, row_out=0, row_filtered=0)
    db.add_all([batch, job])
    db.flush()
    db.bulk_insert_mappings(RawDataRecord, [
        dict(id=i, file_id=upload.id, platform="jd", month=202603, item_id=f"sku-{i}",
             item_name=f"商品{i}", brand_raw="SONY", shop_name="官方店", sales_qty=10,
             sales_amount=100, price=10)
        for i in range(1, count + 1)
    ])
    db.bulk_insert_mappings(DispatchItem, [
        dict(batch_id=batch.id, raw_data_id=i, category_code="headphone")
        for i in range(1, count + 1)
    ])
    if snapshots:
        db.bulk_insert_mappings(CleanJobItemRecord, [
            dict(clean_job_id=job.id, raw_data_id=i, category_code="headphone", platform="jd")
            for i in range(count, 0, -1)
        ])
    ids = upload.id, batch.id, job.id
    db.commit()
    return ids


def test_clean_batches_preserve_priority_dedup_order_and_totals(db, monkeypatch):
    file_id, _, job_id = _seed(db, 9)
    db.query(RawDataRecord).filter(RawDataRecord.id.in_([1, 9])).update({"item_id": "duplicate"})
    db.query(RawDataRecord).filter_by(id=6).update({"item_name": "配件"})
    db.query(RawDataRecord).filter_by(id=5).update({"item_name": "特例配件"})
    db.query(RawDataRecord).filter_by(id=4).update({"item_name": "特例商品", "item_url": "https://item.jd.com/blocked.html"})
    db.add_all([
        InterventionRule(name="特例放行", category_code="headphone", action="allow", priority=1,
                         conditions={"item_name_contains_any": ["特例"]}),
        InterventionRule(name="配件过滤", category_code="headphone", action="filter", priority=2,
                         conditions={"item_name_contains_any": ["配件"]}),
        InterferenceLink(category_code="headphone", url="https://item.jd.com/blocked.html"),
    ])
    db.commit()
    monkeypatch.setattr(data_cleaner, "_CLEAN_BATCH_SIZE", 3)
    writes = []
    loaded_raw_counts = []
    original_insert = db.bulk_insert_mappings

    def record_insert(model, mappings, **kwargs):
        if model in (CleanedDataRecord, FilteredItem):
            writes.append((model, len(mappings)))
            loaded_raw_counts.append(sum(isinstance(obj, RawDataRecord) for obj in db.identity_map.values()))
        return original_insert(model, mappings, **kwargs)

    monkeypatch.setattr(db, "bulk_insert_mappings", record_insert)
    count = data_cleaner.run_clean(db, job_id, [file_id], {"dedup": True}, dispatch_category_code="headphone")

    assert count == 6
    assert all(size <= 3 for _, size in writes)
    assert [size for model, size in writes if model is CleanedDataRecord] == [3, 1, 2]
    assert max(loaded_raw_counts) <= 6
    cleaned = db.query(CleanedDataRecord).order_by(CleanedDataRecord.id).all()
    assert [row.raw_data_id for row in cleaned] == [9, 8, 7, 5, 3, 2]
    assert all(row.brand_std == "SONY" and float(row.calc_price) == 10 for row in cleaned)
    filtered = db.query(FilteredItem).order_by(FilteredItem.id).all()
    assert [row.raw_data_id for row in filtered] == [6, 4]
    assert filtered[0].matched_reason == "命中规则「配件过滤」：商品名称包含 [配件]"
    job = db.get(CleanJobRecord, job_id)
    assert (job.row_in, job.row_out, job.row_filtered) == (9, 6, 2)


def test_clean_prepares_rule_values_once_for_all_batches(db, monkeypatch):
    file_id, _, job_id = _seed(db, 9)
    monkeypatch.setattr(data_cleaner, "_CLEAN_BATCH_SIZE", 3)

    class CountingKeyword:
        calls = 0

        def __str__(self):
            self.calls += 1
            return "商品"

    keyword = CountingKeyword()
    monkeypatch.setattr(data_cleaner, "_load_intervention_rules", lambda *args: [
        {"id": 123, "name": "商品过滤", "action": "filter", "conditions": {"item_name_contains_any": [keyword]}},
    ])

    assert data_cleaner.run_clean(db, job_id, [file_id], {}, dispatch_category_code="headphone") == 0
    assert db.query(FilteredItem).count() == 9
    assert keyword.calls == 2  # One normalization and one human-readable rule summary.
    assert all(row.matched_reason == "命中规则「商品过滤」：商品名称包含 [商品]" for row in db.query(FilteredItem))


def test_clean_rule_preparation_does_not_mutate_shared_rule_cache(db, monkeypatch):
    file_id, _, job_id = _seed(db, 3)
    rule = {"id": 123, "name": "缓存规则", "action": "filter", "conditions": {
        "brand_in": ["SONY"], "shop_name_in": [" 官方店 "],
        "item_name_contains_any": ["不会命中的词"],
        "reference_price": {"op": "between", "min": "10", "max": "500"},
    }}
    original = deepcopy(rule)
    monkeypatch.setattr(data_cleaner, "_load_intervention_rules", lambda *args: [rule])

    for _ in range(2):
        assert data_cleaner.run_clean(db, job_id, [file_id], {}, commit=False) == 3
        assert rule == original
        db.rollback()


@pytest.mark.parametrize("source", ["dispatch", "file"])
def test_clean_legacy_sources_are_batched_and_remain_scoped(db, monkeypatch, source):
    file_id, batch_id, job_id = _seed(db, 8, snapshots=False)
    other = UploadFileRecord(filename="outside.xlsx", status="done")
    db.add(other)
    db.flush()
    db.add(RawDataRecord(file_id=other.id, item_id="outside", item_name="不在范围"))
    db.commit()
    monkeypatch.setattr(data_cleaner, "_CLEAN_BATCH_SIZE", 3)
    sizes = []
    original_insert = db.bulk_insert_mappings

    def record_insert(model, mappings, **kwargs):
        if model is CleanedDataRecord:
            sizes.append(len(mappings))
        return original_insert(model, mappings, **kwargs)

    monkeypatch.setattr(db, "bulk_insert_mappings", record_insert)
    count = data_cleaner.run_clean(db, job_id, [file_id], {},
                                   batch_id if source == "dispatch" else None, "headphone")

    assert count == 8
    assert sizes == [3, 3, 2]
    assert {row.raw_data_id for row in db.query(CleanedDataRecord)} == set(range(1, 9))


def test_incremental_clean_batches_deduplicate_against_existing_and_new_rows(db, monkeypatch):
    file_id, _, job_id = _seed(db, 7)
    db.add(CleanedDataRecord(clean_job_id=job_id, raw_data_id=7, item_id="sku-7", month=202603, shop_name="官方店"))
    db.query(RawDataRecord).filter_by(id=6).update({"item_id": "sku-7"})
    db.query(RawDataRecord).filter(RawDataRecord.id.in_([1, 5])).update({"item_id": "new-duplicate"})
    db.commit()
    monkeypatch.setattr(data_cleaner, "_CLEAN_BATCH_SIZE", 2)

    count = data_cleaner.run_clean(db, job_id, [file_id], {}, raw_data_ids=[1, 2, 3, 4, 5, 6])

    assert count == 4
    assert [row.raw_data_id for row in db.query(CleanedDataRecord).order_by(CleanedDataRecord.id)] == [7, 5, 4, 3, 2]
    assert (db.get(CleanJobRecord, job_id).row_in, db.get(CleanJobRecord, job_id).row_out) == (6, 4)


def test_clean_batch_failure_can_roll_back_all_prior_writes(db, monkeypatch):
    file_id, _, job_id = _seed(db, 7)
    db.query(RawDataRecord).filter_by(id=7).update({"item_name": "配件"})
    db.add(InterventionRule(name="配件过滤", category_code="headphone", action="filter", priority=1,
                            conditions={"item_name_contains_any": ["配件"]}))
    db.commit()
    monkeypatch.setattr(data_cleaner, "_CLEAN_BATCH_SIZE", 3)
    original_insert = db.bulk_insert_mappings
    calls = 0

    def fail_second_batch(model, mappings, **kwargs):
        nonlocal calls
        if model is CleanedDataRecord:
            calls += 1
            if calls == 2:
                raise RuntimeError("second clean batch failed")
        return original_insert(model, mappings, **kwargs)

    monkeypatch.setattr(db, "bulk_insert_mappings", fail_second_batch)
    with pytest.raises(RuntimeError, match="second clean batch failed"):
        data_cleaner.run_clean(db, job_id, [file_id], {}, dispatch_category_code="headphone", commit=False)
    db.rollback()
    assert db.query(CleanedDataRecord).count() == 0
    assert db.query(FilteredItem).count() == 0
    assert db.get(CleanJobRecord, job_id).row_out == 0


def test_clean_batches_do_not_commit_when_caller_owns_transaction(db, monkeypatch):
    file_id, _, job_id = _seed(db, 7)
    monkeypatch.setattr(data_cleaner, "_CLEAN_BATCH_SIZE", 3)
    assert data_cleaner.run_clean(db, job_id, [file_id], {}, commit=False) == 7
    assert db.query(CleanedDataRecord).count() == 7
    db.rollback()
    assert db.query(CleanedDataRecord).count() == 0
    assert db.get(CleanJobRecord, job_id).row_out == 0


def test_clean_empty_source_finishes_with_zero_totals(db):
    file_id, _, job_id = _seed(db, 0)
    assert data_cleaner.run_clean(db, job_id, [file_id], {}) == 0
    job = db.get(CleanJobRecord, job_id)
    assert (job.row_in, job.row_out, job.row_filtered) == (0, 0, 0)
