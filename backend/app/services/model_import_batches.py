"""Bounded reads and writes for product attributes, in the caller's transaction."""
from datetime import datetime
import unicodedata

from sqlalchemy import func, tuple_
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.models.schemas import BrandRecord, ModelRecord, ModelSpec

BATCH_SIZE = 300
MODEL_FIELDS = ("brand_name", "model_name", "url", "launch_year", "launch_month", "launch_week", "launch_price", "series")


def db_collation_key(value):
    value = unicodedata.normalize("NFKC", (value or "").strip()).casefold()
    value = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in value if not unicodedata.combining(ch))


def model_unique_key(brand_code, model_code, category_code, series=None):
    return tuple(db_collation_key(value) for value in (brand_code, model_code, category_code, series))


def _storage_key(row):
    # An import with no series historically matches SQL IS NULL, not ''.
    return model_unique_key(row["brand_code"], row["model_code"], row["category_code"], row["series"]) + (row["series"] is None,)


def load_model_import_rows(db, category_code, pairs):
    """Include spec-only references, without reading unrelated categories/models."""
    pairs = sorted(set(pairs))
    records = {}
    table = ModelRecord.__table__
    for start in range(0, len(pairs), BATCH_SIZE):
        rows = db.query(*table.c).filter(
            table.c.category_code == category_code,
            tuple_(table.c.brand_code, table.c.model_code).in_(pairs[start:start + BATCH_SIZE]),
        ).all()
        for row in rows:
            record = dict(row._mapping)
            records[record["id"]] = record
    return [records[key] for key in sorted(records)]


def _upsert(db, table, rows, conflict_columns, update_fields, preserve_nonempty=False):
    mysql = db.get_bind().dialect.name == "mysql"
    for start in range(0, len(rows), BATCH_SIZE):
        stmt = (mysql_insert if mysql else sqlite_insert)(table).values(rows[start:start + BATCH_SIZE])
        incoming = stmt.inserted if mysql else stmt.excluded
        updates = {}
        for name in update_fields:
            existing = func.nullif(table.c[name], "") if preserve_nonempty and name != "updated_at" else table.c[name]
            if preserve_nonempty and name != "updated_at":
                updates[name] = func.coalesce(existing, getattr(incoming, name))
            else:
                updates[name] = func.coalesce(getattr(incoming, name), existing)
        stmt = stmt.on_duplicate_key_update(**updates) if mysql else stmt.on_conflict_do_update(
            index_elements=conflict_columns, set_=updates,
        )
        db.execute(stmt)


def upsert_model_import_brands(db, rows):
    """Keep the first file spelling/name; fill empty master names only."""
    first = {}
    for row in rows:
        if not row["brand_code"] or set(row["brand_code"]) == {"-"}:
            continue
        first.setdefault(db_collation_key(row["brand_code"]), row)
    codes = [row["brand_code"] for row in first.values()]
    existing = {}
    for start in range(0, len(codes), BATCH_SIZE):
        for brand in db.query(BrandRecord.brand_code, BrandRecord.brand_name, BrandRecord.original_brand_name).filter(
            BrandRecord.brand_code.in_(codes[start:start + BATCH_SIZE]),
        ):
            existing[db_collation_key(brand.brand_code)] = brand
    writes = []
    for key, row in first.items():
        brand = existing.get(key)
        name = row["brand_name"]
        if brand is not None and (not name or (brand.brand_name and brand.original_brand_name)):
            continue
        writes.append(dict(brand_code=row["brand_code"], brand_name=name, original_brand_name=name,
                           status="active", updated_at=datetime.utcnow()))
    _upsert(db, BrandRecord.__table__, writes, ["brand_code"],
            ["brand_name", "original_brand_name", "updated_at"], preserve_nonempty=True)


def save_model_import_rows(db, category_code, rows, spec_pairs=()):
    """Merge repeated file rows before one upsert per distinct model.

    Existing IDs make NULL-series updates safe (MySQL permits repeated NULLs
    in a composite unique index). Empty optional cells preserve stored values.
    Counts retain the existing API's row-based update semantics.
    """
    pairs = {(row["brand_code"], row["model_code"]) for row in rows} | set(spec_pairs)
    records = load_model_import_rows(db, category_code, pairs)
    known = {}
    for record in records:
        known.setdefault(_storage_key(record), record)
    writes = {}
    inserted = updated = 0
    for row in rows:
        key = _storage_key(row)
        record = writes.get(key)
        if record is None:
            old = known.get(key)
            record = {"id": old["id"] if old else None,
                      "brand_code": old["brand_code"] if old else row["brand_code"],
                      "model_code": old["model_code"] if old else row["model_code"],
                      "category_code": category_code, "status": old["status"] if old else "active",
                      **{name: old[name] if old else row[name] for name in MODEL_FIELDS}}
            writes[key] = record
            if old is None:
                inserted += 1
            else:
                updated += 1
        else:
            updated += 1
        for name in MODEL_FIELDS:
            if row[name] is not None:
                record[name] = row[name]
    upsert_model_import_brands(db, rows)
    now = datetime.utcnow()
    _upsert(db, ModelRecord.__table__, [{**row, "updated_at": now} for row in writes.values()], ["id"],
            [*MODEL_FIELDS, "category_code", "updated_at"])
    # Read generated IDs in batches; also retain spec references to models
    # already in this category but absent from the model sheet.
    records = load_model_import_rows(db, category_code, pairs)
    full, fallback = {}, {}
    for record in records:
        key = model_unique_key(record["brand_code"], record["model_code"], record["category_code"], record["series"])
        full[key] = record["id"]
        fallback.setdefault(key[:3], []).append(record["id"])
    return inserted, updated, full, fallback


def replace_model_import_specs(db, affected_model_ids, rows):
    ids = sorted(affected_model_ids)
    for start in range(0, len(ids), BATCH_SIZE):
        db.query(ModelSpec).filter(ModelSpec.model_id.in_(ids[start:start + BATCH_SIZE])).delete(synchronize_session=False)
    for start in range(0, len(rows), BATCH_SIZE):
        db.execute(ModelSpec.__table__.insert(), rows[start:start + BATCH_SIZE])
    return len(rows)
