"""Bounded confirmation transactions with row-level failure isolation."""
import logging
from datetime import datetime

from sqlalchemy import and_

from app.models.schemas import ItemUrlMapping, MatchResult, MatchResultAttr, ModelRecord, RawDataRecord
from app.services.url_mapping_importer import import_key


logger = logging.getLogger(__name__)
BATCH_SIZE = 100
ALLOWED_STATUSES = {"text_only", "pending"}
INVALID_CODES = {None, "", "-", "--"}
_PREVIOUS_FIELDS = (
    "match_status", "model_id", "matched_by", "match_source",
    "dispute_reason", "review_note", "reviewed_at",
)


def _confirm_chunk(db, clean_job_id, entries, model_id):
    """Lock and re-read current state before bulk writes, in this transaction."""
    records = {
        row.id: dict(row._mapping)
        for row in db.query(*MatchResult.__table__.c)
        .filter(MatchResult.clean_job_id == clean_job_id,
                MatchResult.id.in_([entry[1] for entry in entries]))
        .order_by(MatchResult.id).with_for_update().all()
    }
    model = db.query(ModelRecord.id, ModelRecord.brand_code, ModelRecord.model_code, ModelRecord.category_code).filter(
        ModelRecord.id == model_id,
    ).first()
    raw_ids = {row["raw_data_id"] for row in records.values() if row["raw_data_id"] is not None}
    raw_by_id = {
        row.id: row for row in db.query(
            RawDataRecord.id, RawDataRecord.item_name, RawDataRecord.platform,
            RawDataRecord.item_id, RawDataRecord.item_url, RawDataRecord.price,
        ).filter(RawDataRecord.id.in_(raw_ids)).order_by(RawDataRecord.id).with_for_update().all()
    } if raw_ids else {}
    # Let the database compare keys using its actual collation, rather than
    # indexing existing URLs by Python's case-sensitive string equality.
    mappings = {
        row.raw_id: row for row in db.query(
            RawDataRecord.id.label("raw_id"), ItemUrlMapping.id,
        ).select_from(ItemUrlMapping)
        .join(RawDataRecord, and_(ItemUrlMapping.platform == RawDataRecord.platform,
                                 ItemUrlMapping.item_id == RawDataRecord.item_id))
        .filter(RawDataRecord.id.in_(raw_ids))
        .order_by(ItemUrlMapping.id, RawDataRecord.id).with_for_update().all()
    } if raw_ids else {}

    now = datetime.utcnow()
    updates, url_updates, url_inserts, outcomes = [], {}, {}, []
    for position, match_id in entries:
        row = records.get(match_id)
        raw = raw_by_id.get(row["raw_data_id"]) if row else None
        reason = None
        if not row or row["match_status"] not in ALLOWED_STATUSES:
            reason = "状态已变更"
        elif (not model or row["brand_identified"] == 0
              or model.brand_code in INVALID_CODES or model.model_code in INVALID_CODES):
            reason = "目标型号无效"
        if reason:
            outcomes.append((position, match_id, raw.item_name if raw else None, reason))
            continue

        update = {"id": match_id, **{f"prev_{name}": row[name] for name in _PREVIOUS_FIELDS},
                  "model_id": model_id, "match_status": "confirmed", "matched_by": "manual",
                  "match_source": "manual", "dispute_reason": None, "review_note": None,
                  "reviewed_at": now, "updated_at": now}
        updates.append(update)
        # Duplicate IDs in a request retain the old first-success/next-stale behavior.
        row["match_status"] = "confirmed"
        if raw and raw.item_url and raw.platform and raw.item_id:
            payload = dict(item_url=raw.item_url, model_id=model_id, brand_code=model.brand_code,
                           category_code=model.category_code, price=raw.price,
                           source="match_confirm", updated_at=now)
            existing = mappings.get(raw.id)
            if existing:
                url_updates[existing.id] = {"id": existing.id, **payload}
            else:
                key = import_key(db, raw.platform, raw.item_id)
                url_inserts[key] = dict(platform=raw.platform, item_id=raw.item_id, **payload)
        outcomes.append((position, match_id, raw.item_name if raw else None, None))

    if updates:
        db.bulk_update_mappings(MatchResult, updates)
        if url_updates:
            db.bulk_update_mappings(ItemUrlMapping, list(url_updates.values()))
        if url_inserts:
            db.execute(ItemUrlMapping.__table__.insert(), list(url_inserts.values()))
        db.query(MatchResultAttr).filter(
            MatchResultAttr.match_result_id.in_([row["id"] for row in updates]),
        ).delete(synchronize_session=False)
        db.commit()
    return outcomes


def confirm_review_batches(db, clean_job_id, target_ids, model_id):
    """Healthy batches commit once; failed batches split until bad rows are isolated."""
    outcomes = []

    def process(entries):
        try:
            outcomes.extend(_confirm_chunk(db, clean_job_id, entries, model_id))
        except Exception:
            db.rollback()
            if len(entries) == 1:
                logger.exception("Batch confirmation failed for match_id=%s", entries[0][1])
                try:
                    name = db.query(RawDataRecord.item_name).join(
                        MatchResult, MatchResult.raw_data_id == RawDataRecord.id,
                    ).filter(MatchResult.id == entries[0][1]).scalar()
                except Exception:
                    db.rollback()
                    name = None
                outcomes.append((entries[0][0], entries[0][1], name, "系统错误"))
            else:
                logger.warning("Retrying failed confirmation batch of %s rows in smaller groups", len(entries))
                middle = len(entries) // 2
                process(entries[:middle])
                process(entries[middle:])

    entries = list(enumerate(target_ids))
    for start in range(0, len(entries), BATCH_SIZE):
        process(entries[start:start + BATCH_SIZE])
    outcomes.sort()
    return (
        [match_id for _, match_id, _, reason in outcomes if reason is None],
        [{"id": match_id, "item_name": name, "reason": reason}
         for _, match_id, name, reason in outcomes if reason is not None],
    )
