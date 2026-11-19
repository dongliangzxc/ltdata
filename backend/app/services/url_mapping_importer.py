"""Bounded URL import reads and atomic database upserts (one transaction per file)."""
from datetime import datetime
import unicodedata

from sqlalchemy import func, tuple_
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.models.schemas import BrandCategory, BrandRecord, ItemUrlMapping, ModelRecord


BATCH_SIZE = 300


def _insert_missing(db, model, rows, unique_columns):
    """Ignore concurrent creation of shared master data without overwriting it."""
    table = model.__table__
    mysql = db.get_bind().dialect.name == "mysql"
    for start in range(0, len(rows), BATCH_SIZE):
        stmt = (mysql_insert if mysql else sqlite_insert)(table).values(rows[start:start + BATCH_SIZE])
        if mysql:
            key = unique_columns[0]
            stmt = stmt.on_duplicate_key_update(**{key: table.c[key]})
        else:
            stmt = stmt.on_conflict_do_nothing(index_elements=unique_columns)
        db.execute(stmt)


def import_key(db, *values):
    # Production uses a case/accent-insensitive MySQL collation. Match its keys
    # in the file cache too, including IDs that differ only by letter case.
    if db.get_bind().dialect.name == "mysql":
        return tuple("".join(c for c in unicodedata.normalize("NFKD", value)
                             if not unicodedata.combining(c)).casefold().rstrip()
                     for value in values)
    return values


class ImportModelLookup:
    """Load only the brand/code or brand/series pairs referenced by this file."""

    def __init__(self, db, rows, category_code, has_series):
        self.db = db
        self.category_code = category_code
        self.has_series = has_series
        self.by_code = {}
        self.by_category_code = {}
        self.by_series = {}
        self.by_category_series = {}
        self.by_series_code = {}
        self.by_category_series_code = {}
        code_keys, series_keys = set(), set()
        for row in rows:
            if has_series and row["series"]:
                series_keys.add((row["brand_code"], row["series"]))
            elif row["model_code"] not in ("", "-", "—", "--", "未知"):
                code_keys.add((row["brand_code"], row["model_code"]))
        models = {}
        for keys, column in ((code_keys, ModelRecord.model_code), (series_keys, ModelRecord.series)):
            keys = sorted(keys)
            for start in range(0, len(keys), BATCH_SIZE):
                for model in db.query(ModelRecord).filter(
                    tuple_(ModelRecord.brand_code, column).in_(keys[start:start + BATCH_SIZE])
                ).all():
                    models[model.id] = model
        for model_id in sorted(models):
            self.add(models[model_id])

    def add(self, model):
        brand, code = import_key(self.db, model.brand_code or "", model.model_code or "")
        category = import_key(self.db, model.category_code or "")[0]
        self.by_code.setdefault((brand, code), model)
        self.by_category_code.setdefault((brand, code, category), model)
        if model.series:
            series = import_key(self.db, model.series)[0]
            self.by_series.setdefault((brand, series), model)
            self.by_category_series.setdefault((brand, series, category), model)
            self.by_series_code.setdefault((brand, series, code), model)
            self.by_category_series_code.setdefault((brand, series, code, category), model)

    def find(self, brand, code, series):
        brand, code, series, category = import_key(
            self.db, brand, code, series or "", self.category_code or "",
        )
        if self.has_series and series:
            if code in ("", "—", "--", "未知"):
                code = "-"
            return (
                self.by_category_series_code.get((brand, series, code, category))
                or self.by_category_series.get((brand, series, category))
                or self.by_series_code.get((brand, series, code))
                or self.by_series.get((brand, series))
            )
        return self.by_category_code.get((brand, code, category)) or self.by_code.get((brand, code))

    def create_missing(self, rows):
        """Create missing brands, category links and models in batches too."""
        planned = []
        for row in rows:
            brand, code = row["brand_code"], row["model_code"]
            series = (row["series"] or None) if self.has_series else None
            if not self.category_code or brand.upper() in {"", "-", "—", "--", "UNKNOWN", "未知"}:
                continue
            if not series and code in ("", "-", "—", "--", "未知"):
                continue
            if self.find(brand, code, series):
                continue
            if series and code in ("", "—", "--", "未知"):
                code = "-"
            model = ModelRecord(brand_code=brand, model_code=code,
                                category_code=self.category_code, series=series)
            planned.append(model)
            # Index the planned model immediately: repeated rows/series create
            # exactly one model even with Session(autoflush=False).
            self.add(model)
        if not planned:
            return self

        db = self.db
        brands = sorted({model.brand_code for model in planned})
        brand_names = {}
        for start in range(0, len(brands), BATCH_SIZE):
            for brand in db.query(BrandRecord).filter(BrandRecord.brand_code.in_(brands[start:start + BATCH_SIZE])):
                brand_names[import_key(db, brand.brand_code)[0]] = brand.brand_name
        missing_brands = [dict(brand_code=brand, brand_name=brand) for brand in brands
                          if import_key(db, brand)[0] not in brand_names]
        _insert_missing(db, BrandRecord, missing_brands, ["brand_code"])
        _insert_missing(db, BrandCategory,
                        [dict(brand_code=brand, category_code=self.category_code) for brand in brands],
                        ["brand_code", "category_code"])
        _insert_missing(db, ModelRecord, [dict(
            brand_code=model.brand_code, model_code=model.model_code,
            model_name=model.model_code, category_code=self.category_code,
            series=model.series, status="active",
            brand_name=brand_names.get(import_key(db, model.brand_code)[0], model.brand_code),
        ) for model in planned], ["brand_code", "category_code", "series", "model_code"])
        # Reload generated IDs in bounded queries, rather than one flush/SELECT
        # per new model. All writes still belong to the caller's transaction.
        return ImportModelLookup(db, rows, self.category_code, self.has_series)


def upsert_url_import_rows(db, rows, payload_fields):
    """Last file row wins; a blank price preserves the last known price.

    The unique constraint resolves conflicts at write time, including another
    transaction inserting a URL after our count query. Never commit here.

    Returns ``(inserted, updated, duplicates)``. ``updated`` only counts unique
    (platform, item_id) keys that already existed; rows duplicated inside the
    same file are reported separately so the UI does not show an inflated
    update count.
    """
    if not rows:
        return 0, 0, 0
    table = ItemUrlMapping.__table__
    unique_rows = {}
    duplicate_count = 0
    for row in rows:
        key = import_key(db, row["platform"], row["item_id"])
        previous = unique_rows.get(key)
        if previous is not None:
            duplicate_count += 1
            if row["price"] is None:
                row["price"] = previous["price"]
            # Existing mappings have always retained the first stored URL.
            row["item_url"] = previous["item_url"]
        unique_rows[key] = row

    inserted, updated, duplicates = 0, 0, duplicate_count
    values = list(unique_rows.values())
    dialect = db.get_bind().dialect.name
    insert = mysql_insert if dialect == "mysql" else sqlite_insert
    for start in range(0, len(values), BATCH_SIZE):
        batch = values[start:start + BATCH_SIZE]
        keys = [(row["platform"], row["item_id"]) for row in batch]
        existing = db.query(ItemUrlMapping.platform, ItemUrlMapping.item_id).filter(
            tuple_(ItemUrlMapping.platform, ItemUrlMapping.item_id).in_(keys)
        ).all()
        updated += len(existing)
        inserted += len(batch) - len(existing)
        now = datetime.utcnow()
        stmt = insert(table).values([
            {**row, "created_at": now, "updated_at": now} for row in batch
        ])
        incoming = stmt.inserted if dialect == "mysql" else stmt.excluded
        updates = {name: getattr(incoming, name) for name in
                   ("model_id", "brand_code", "category_code", "source", "updated_at")}
        updates["category_code"] = func.coalesce(func.nullif(incoming.category_code, ""), table.c.category_code)
        updates["price"] = func.coalesce(incoming.price, table.c.price)
        for name in ("data_year", "data_month"):
            if name in payload_fields:
                updates[name] = getattr(incoming, name)
        if dialect == "mysql":
            stmt = stmt.on_duplicate_key_update(**updates)
        else:
            stmt = stmt.on_conflict_do_update(index_elements=["platform", "item_id"], set_=updates)
        db.execute(stmt)
    return inserted, updated, duplicates
