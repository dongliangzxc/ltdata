"""Large mapping imports, duplicate/retry writes and transaction rollback."""
from types import SimpleNamespace

import pandas as pd
import pytest
from sqlalchemy import event
from sqlalchemy.dialects import mysql

from app.api import url_mapping_api as api
from app.models.schemas import BrandCategory, BrandRecord, Category, CategoryExtraField, ItemUrlMapping, ModelRecord
from app.services import url_mapping_importer as importer


@pytest.fixture
def confirm(db, tmp_path, monkeypatch):
    db.autoflush = False
    db.add(Category(code="camera", name="监控摄像头"))
    db.commit()
    (tmp_path / "tmp").mkdir()
    (tmp_path / "tmp" / "batch.csv").touch()
    monkeypatch.setattr(api, "UPLOAD_DIR", str(tmp_path))

    def run(rows, **extra):
        monkeypatch.setattr(api.pd, "read_csv", lambda *a, **kw: pd.DataFrame(rows))
        payload = api.UrlMappingConfirmPayload(
            temp_file_id="batch", mapping={}, category_code="camera", **extra,
        )
        return api.url_mapping_confirm(payload, db, SimpleNamespace(is_admin=1, category_permissions=[]))

    return run


def row(item_id="100058161923", **extra):
    return dict(platform="京东", item_url=f"https://item.jd.com/{item_id}.html",
                brand_code="小米", model_code="-", series="3云台版", price="170.76", **extra)


def test_duplicate_retry_preserves_price_and_omitted_dimensions(db, confirm):
    rows = [row(), {**row(), "price": "198"}, {**row(), "price": None}]
    first = confirm(rows, data_year=2026, data_month=10)
    assert (first["inserted"], first["updated"], first["errors"]) == (1, 2, [])
    second = confirm([{**row(), "price": None, "brand_code": "乔安"}])
    assert (second["inserted"], second["updated"]) == (0, 1)
    db.expire_all()
    saved = db.query(ItemUrlMapping).one()
    assert saved.brand_code == "乔安"
    assert float(saved.price) == 198
    assert (saved.data_year, saved.data_month) == (2026, 10)
    assert saved.category_code == "camera" and saved.source == "url_import"
    confirm([row()], data_year=None, data_month=None)
    db.expire_all()
    assert (saved.data_year, saved.data_month) == (None, None)


def test_url_written_after_count_is_updated_without_unique_error(db, confirm, monkeypatch):
    execute = db.execute
    injected = False

    def racing_write(statement, *args, **kwargs):
        nonlocal injected
        if getattr(statement, "is_insert", False) and statement.table.name == "item_url_mappings" and not injected:
            injected = True
            # Simulate another import winning the write after the SELECT saw
            # no record. An ORM INSERT would fail with the production 1062.
            execute(ItemUrlMapping.__table__.insert().values(
                platform="jd", item_id="100058161923", brand_code="旧品牌", price=99,
                data_year=2025, data_month=12,
            ))
        return execute(statement, *args, **kwargs)

    monkeypatch.setattr(db, "execute", racing_write)
    assert confirm([row()])["errors"] == []
    assert injected
    saved = db.query(ItemUrlMapping).one()
    assert saved.brand_code == "小米" and float(saved.price) == 170.76
    assert (saved.data_year, saved.data_month) == (2025, 12)


def test_large_series_import_uses_bounded_reads_and_writes(db, confirm, monkeypatch):
    db.add(CategoryExtraField(category_code="camera", field_key="series", field_label="产品系列"))
    db.commit()
    statements = []

    def capture(conn, cursor, sql, parameters, context, executemany):
        statements.append(sql)

    event.listen(db.get_bind(), "before_cursor_execute", capture)
    monkeypatch.setattr(importer, "BATCH_SIZE", 100)
    try:
        # Unique series exercises bulk model creation, repeated rows exercise
        # URL deduplication across what would have been batch boundaries.
        rows = [{**row(str(i)), "series": f"系列{i % 250}"} for i in range(1050)]
        result = confirm(rows + rows[:50])
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", capture)
    assert (result["inserted"], result["updated"], result["errors"]) == (1050, 50, [])
    assert db.query(ModelRecord).count() == 250
    assert db.query(BrandRecord).count() == db.query(BrandCategory).count() == 1
    assert db.query(ItemUrlMapping).count() == 1050
    assert len(statements) < 45, len(statements)
    saved = db.query(ItemUrlMapping).filter_by(item_id="1").one()
    assert saved.model.series == "系列1" and saved.model.model_code == "-"
    assert saved.model.model_name == "-" and saved.model.brand_name == "小米"


def test_later_batch_failure_rolls_back_models_brands_and_all_mapping_batches(db, confirm, monkeypatch):
    monkeypatch.setattr(importer, "BATCH_SIZE", 2)
    execute = db.execute
    batches = 0

    def fail_second_batch(statement, *args, **kwargs):
        nonlocal batches
        if getattr(statement, "is_insert", False) and statement.table.name == "item_url_mappings":
            batches += 1
            if batches == 2:
                raise RuntimeError("injected batch failure")
        return execute(statement, *args, **kwargs)

    monkeypatch.setattr(db, "execute", fail_second_batch)
    with pytest.raises(RuntimeError, match="injected batch failure"):
        confirm([{**row(str(i)), "model_code": "NEW"} for i in range(3)])
    assert db.query(ItemUrlMapping).count() == 0
    assert db.query(ModelRecord).count() == 0
    assert db.query(BrandRecord).count() == 0
    assert db.query(BrandCategory).count() == 0


def test_series_priority_and_same_series_reuses_one_new_model(db, confirm):
    db.add(CategoryExtraField(category_code="camera", field_key="series", field_label="产品系列"))
    db.add_all([
        ModelRecord(brand_code="小米", model_code="A", category_code="other", series="现有"),
        ModelRecord(brand_code="小米", model_code="B", category_code="camera", series="现有"),
    ])
    db.commit()
    result = confirm([
        {**row("1"), "model_code": "A", "series": "现有"},
        {**row("2"), "model_code": "X", "series": "新系列"},
        {**row("3"), "model_code": "Y", "series": "新系列"},
    ])
    assert result["errors"] == []
    saved = db.query(ItemUrlMapping).order_by(ItemUrlMapping.item_id).all()
    assert saved[0].model.model_code == "B"  # same-category series beats foreign exact code
    assert saved[1].model_id == saved[2].model_id
    assert db.query(ModelRecord).count() == 3


def test_mysql_compiles_atomic_upsert_with_nonempty_price_and_dimension_rules():
    statements = []
    fake = SimpleNamespace(
        get_bind=lambda: SimpleNamespace(dialect=mysql.dialect()),
        query=lambda *args: SimpleNamespace(filter=lambda *a: SimpleNamespace(all=lambda: [])),
        execute=lambda stmt: statements.append(stmt),
    )
    values = dict(platform="jd", item_id="1", item_url="url", brand_code="小米", model_id=None,
                  category_code="camera", price=None, source="url_import", data_year=None, data_month=None)
    importer.upsert_url_import_rows(fake, [values], {"data_month"})
    sql = str(statements[0].compile(dialect=mysql.dialect())).split("ON DUPLICATE KEY UPDATE")[1]
    assert "coalesce(VALUES(price), item_url_mappings.price)" in sql
    assert "data_month = VALUES(data_month)" in sql
    assert "data_year =" not in sql and "item_url =" not in sql


def test_empty_category_does_not_clear_existing_mapping_category(db):
    db.add(ItemUrlMapping(platform="jd", item_id="1", category_code="camera"))
    db.commit()
    values = dict(platform="jd", item_id="1", item_url="url", brand_code="小米", model_id=None,
                  category_code="", price=None, source="url_import", data_year=None, data_month=None)
    assert importer.upsert_url_import_rows(db, [values], set()) == (0, 1)
    db.commit()
    db.expire_all()
    assert db.query(ItemUrlMapping).one().category_code == "camera"


def test_mysql_collation_deduplicates_case_and_accent_variants():
    statements = []
    fake = SimpleNamespace(
        get_bind=lambda: SimpleNamespace(dialect=mysql.dialect()),
        query=lambda *args: SimpleNamespace(filter=lambda *a: SimpleNamespace(all=lambda: [])),
        execute=lambda stmt: statements.append(stmt),
    )
    values = dict(platform="jd", item_id="SKU-café", item_url="url", brand_code="小米", model_id=None,
                  category_code="camera", price=99, source="url_import", data_year=None, data_month=None)
    assert importer.upsert_url_import_rows(fake, [values, {**values, "item_id": "sku-CAFE", "price": None}], set()) == (1, 1)
    parameters = statements[0].compile(dialect=mysql.dialect()).params
    assert parameters["item_id_m0"] == "sku-CAFE" and parameters["price_m0"] == 99
    assert "item_id_m1" not in parameters
