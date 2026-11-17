"""Missing product IDs cannot identify duplicates across different source rows."""

import pytest

from app.models.schemas import (
    CleanedDataRecord, CleanJobItemRecord, CleanJobRecord, FilteredItem,
    InterventionRule, RawDataRecord, UploadFileRecord,
)
from app.services import data_cleaner


def _seed(db, item_ids, *, snapshots=True, same_title=False):
    upload = UploadFileRecord(filename="missing-ids.xlsx", status="done")
    db.add(upload)
    db.flush()
    job = CleanJobRecord(file_ids=[upload.id], category_code="headphone", rules={"dedup": True},
                         status="created", row_in=0, row_out=0, row_filtered=0)
    db.add(job)
    db.flush()
    rows = [RawDataRecord(file_id=upload.id, platform="jd", month=202603,
                          item_id=item_id, item_name="相同标题" if same_title else f"商品{i}",
                          item_url="https://example.com/shared", shop_name="官方店")
            for i, item_id in enumerate(item_ids)]
    db.add_all(rows)
    db.flush()
    if snapshots:
        db.add_all([CleanJobItemRecord(clean_job_id=job.id, raw_data_id=row.id,
                                       category_code="headphone", platform="jd")
                    for row in reversed(rows)])
    ids = upload.id, job.id, [row.id for row in rows]
    db.commit()
    return ids


@pytest.mark.parametrize("item_id", [None, "", " \t ", "\u3000"])
@pytest.mark.parametrize("snapshots", [True, False])
def test_missing_ids_keep_distinct_records_across_batches(db, monkeypatch, item_id, snapshots):
    file_id, job_id, raw_ids = _seed(db, [item_id, item_id], snapshots=snapshots)
    monkeypatch.setattr(data_cleaner, "_CLEAN_BATCH_SIZE", 1)

    assert data_cleaner.run_clean(db, job_id, [file_id], {"dedup": True}) == 2

    output = db.query(CleanedDataRecord).order_by(CleanedDataRecord.id).all()
    assert [row.raw_data_id for row in output] == (list(reversed(raw_ids)) if snapshots else raw_ids)
    assert [row.item_id for row in output] == [item_id, item_id]
    job = db.get(CleanJobRecord, job_id)
    assert (job.row_in, job.row_out, job.row_filtered) == (2, 2, 0)


def test_missing_ids_do_not_use_title_or_url_to_merge_different_source_rows(db):
    file_id, job_id, raw_ids = _seed(db, [None, None], same_title=True)

    assert data_cleaner.run_clean(db, job_id, [file_id], {"dedup": True}) == 2
    assert {row.raw_data_id for row in db.query(CleanedDataRecord)} == set(raw_ids)


def test_nonempty_ids_keep_existing_comparison_and_first_snapshot_wins(db, monkeypatch):
    file_id, job_id, raw_ids = _seed(db, ["sku", "sku", " 0 ", "0", "0", "sku ", "sku"])
    monkeypatch.setattr(data_cleaner, "_CLEAN_BATCH_SIZE", 2)

    assert data_cleaner.run_clean(db, job_id, [file_id], {"dedup": True}) == 4
    assert [row.raw_data_id for row in db.query(CleanedDataRecord).order_by(CleanedDataRecord.id)] == [
        raw_ids[6], raw_ids[5], raw_ids[4], raw_ids[2],
    ]


def test_incremental_missing_ids_keep_new_rows_and_skip_already_cleaned_source_rows(db, monkeypatch):
    file_id, job_id, raw_ids = _seed(db, [None, "", "", "sku"])
    db.add_all([
        CleanedDataRecord(clean_job_id=job_id, raw_data_id=raw_ids[2], item_id="", month=202603,
                          shop_name="官方店"),
        CleanedDataRecord(clean_job_id=job_id, raw_data_id=raw_ids[3], item_id="sku", month=202603,
                          shop_name="官方店"),
    ])
    db.commit()
    monkeypatch.setattr(data_cleaner, "_CLEAN_BATCH_SIZE", 1)

    assert data_cleaner.run_clean(db, job_id, [file_id], {"dedup": True}, raw_data_ids=raw_ids) == 2
    assert [row.raw_data_id for row in db.query(CleanedDataRecord).order_by(CleanedDataRecord.id)] == [
        raw_ids[2], raw_ids[3], raw_ids[1], raw_ids[0],
    ]
    # Repeating the same supplemental range must not duplicate these source records.
    assert data_cleaner.run_clean(db, job_id, [file_id], {"dedup": True}, raw_data_ids=raw_ids) == 0
    assert db.query(CleanedDataRecord).count() == 4


def test_legacy_output_without_source_or_product_id_does_not_suppress_new_rows(db):
    file_id, job_id, raw_ids = _seed(db, [None, None])
    db.add(CleanedDataRecord(clean_job_id=job_id, raw_data_id=None, item_id=None,
                             month=202603, shop_name="官方店"))
    db.commit()

    assert data_cleaner.run_clean(db, job_id, [file_id], {"dedup": True}, raw_data_ids=raw_ids) == 2
    assert db.query(CleanedDataRecord).count() == 3


def test_missing_ids_still_apply_filter_rules_before_deduplication(db):
    file_id, job_id, raw_ids = _seed(db, [None, None])
    db.query(RawDataRecord).filter_by(id=raw_ids[0]).update({"item_name": "配件"})
    db.add(InterventionRule(name="配件过滤", category_code="headphone", priority=1, action="filter",
                            conditions={"item_name_contains_any": ["配件"]}))
    db.commit()

    assert data_cleaner.run_clean(db, job_id, [file_id], {"dedup": True},
                                   dispatch_category_code="headphone") == 1
    assert db.query(CleanedDataRecord).one().raw_data_id == raw_ids[1]
    assert db.query(FilteredItem).one().raw_data_id == raw_ids[0]
    job = db.get(CleanJobRecord, job_id)
    assert (job.row_in, job.row_out, job.row_filtered) == (2, 1, 1)


def test_disabled_dedup_still_allows_existing_source_records(db):
    file_id, job_id, raw_ids = _seed(db, [None])
    db.add(CleanedDataRecord(clean_job_id=job_id, raw_data_id=raw_ids[0], item_id=None,
                             month=202603, shop_name="官方店"))
    db.commit()

    assert data_cleaner.run_clean(db, job_id, [file_id], {"dedup": False}, raw_data_ids=raw_ids) == 1
    assert db.query(CleanedDataRecord).count() == 2
