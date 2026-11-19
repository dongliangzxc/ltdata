"""Bulk product imports retain values, spec targeting and atomic rollback."""
import pytest
from sqlalchemy import event

from app.models.schemas import BrandRecord, Category, ModelRecord, ModelSpec
from app.services import model_import_batches as batches


def row(code="M1", **overrides):
    return dict(brand_code="BRAND", model_code=code, category_code="camera", series=None,
                brand_name="上传品牌名", model_name="型号名", url=None, launch_year=None,
                launch_month=None, launch_week=None, launch_price=None, **overrides)


def test_repeated_rows_preserve_empty_values_brand_names_status_and_null_series_id(db):
    db.add(Category(code="camera", name="摄像头"))
    brand = BrandRecord(brand_code="BRAND", brand_name="人工品牌名", original_brand_name="原品牌名", status="inactive")
    model = ModelRecord(brand_code="BRAND", model_code="M1", category_code="camera",
                        model_name="旧名", launch_price=99, url="old", status="inactive", operator="analyst")
    db.add_all([brand, model])
    db.commit()
    original_id = model.id
    rows = [row(), {**row(), "model_name": "新名"}, {**row(), "model_name": None}]
    assert batches.save_model_import_rows(db, "camera", rows)[:2] == (0, 3)
    db.commit()
    db.expire_all()
    saved = db.query(ModelRecord).one()
    assert saved.id == original_id and saved.series is None
    assert saved.model_name == "新名" and saved.url == "old" and float(saved.launch_price) == 99
    assert saved.status == "inactive" and saved.operator == "analyst"
    assert brand.brand_name == "人工品牌名" and brand.original_brand_name == "原品牌名" and brand.status == "inactive"


def test_large_import_uses_bounded_statements_without_orm_spec_objects(db, monkeypatch):
    db.add(Category(code="camera", name="摄像头"))
    db.commit()
    monkeypatch.setattr(batches, "BATCH_SIZE", 100)
    statements = []

    def capture(conn, cursor, sql, params, context, executemany):
        statements.append(sql)

    event.listen(db.get_bind(), "before_cursor_execute", capture)
    try:
        rows = [row(str(i)) for i in range(301)]
        inserted, updated, full, _ = batches.save_model_import_rows(db, "camera", rows + rows[:5])
        specs = [{"model_id": model_id, "spec_name": f"属性{i}", "spec_value": str(i)}
                 for model_id in full.values() for i in range(4)]
        assert batches.replace_model_import_specs(db, full.values(), specs) == 1204
        db.commit()
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", capture)
    assert (inserted, updated) == (301, 5)
    assert len(statements) < 35, len(statements)
    assert not any(isinstance(obj, ModelSpec) for obj in db.identity_map.values())
    assert db.query(ModelRecord).count() == 301 and db.query(ModelSpec).count() == 1204


def test_specs_replace_only_successfully_targeted_models_and_can_reference_spec_only_models(db):
    db.add(Category(code="camera", name="摄像头"))
    db.add(Category(code="other", name="其它"))
    one = ModelRecord(brand_code="BRAND", model_code="M1", category_code="camera")
    two = ModelRecord(brand_code="BRAND", model_code="M2", category_code="camera")
    foreign = ModelRecord(brand_code="BRAND", model_code="M1", category_code="other")
    db.add_all([one, two, foreign])
    db.flush()
    db.add_all([ModelSpec(model_id=m.id, spec_name="old", spec_value="keep") for m in [one, two, foreign]])
    db.commit()
    _, _, full, fallback = batches.save_model_import_rows(db, "camera", [row()], {("BRAND", "M2")})
    assert set(full.values()) == {one.id, two.id}
    assert all(foreign.id not in ids for ids in fallback.values())
    batches.replace_model_import_specs(db, {two.id}, [dict(model_id=two.id, spec_name="new", spec_value="fresh")])
    db.commit()
    specs = {(s.model_id, s.spec_name, s.spec_value) for s in db.query(ModelSpec)}
    assert specs == {(one.id, "old", "keep"), (two.id, "new", "fresh"), (foreign.id, "old", "keep")}


def test_failure_in_later_spec_batch_rolls_back_brands_models_and_old_spec_deletion(db, monkeypatch):
    db.add(Category(code="camera", name="摄像头"))
    old = ModelRecord(brand_code="BRAND", model_code="M1", category_code="camera")
    db.add(old)
    db.flush()
    old_id = old.id
    db.add(ModelSpec(model_id=old_id, spec_name="old", spec_value="keep"))
    db.commit()
    monkeypatch.setattr(batches, "BATCH_SIZE", 1)
    execute = db.execute
    inserts = 0

    def fail(statement, *args, **kwargs):
        nonlocal inserts
        if getattr(statement, "is_insert", False) and statement.table.name == "model_specs":
            inserts += 1
            if inserts == 2:
                raise RuntimeError("spec batch failed")
        return execute(statement, *args, **kwargs)

    monkeypatch.setattr(db, "execute", fail)
    try:
        batches.save_model_import_rows(db, "camera", [row(), row("M2")])
        with pytest.raises(RuntimeError, match="spec batch failed"):
            batches.replace_model_import_specs(db, {old_id}, [
                dict(model_id=old_id, spec_name="one", spec_value="x"),
                dict(model_id=old_id, spec_name="two", spec_value="y"),
            ])
    finally:
        db.rollback()
    assert db.query(BrandRecord).count() == 0 and db.query(ModelRecord).count() == 1
    assert [(s.spec_name, s.spec_value) for s in db.query(ModelSpec)] == [("old", "keep")]


def test_new_models_fold_case_width_and_accents_before_insert(db):
    rows = [row("Ｍ108"), {**row("m108"), "model_name": "last"}, row("café"), row("CAFE")]
    inserted, updated, _, _ = batches.save_model_import_rows(db, "camera", rows)
    db.commit()
    assert (inserted, updated) == (2, 2)
    assert db.query(ModelRecord).count() == 2
    assert db.query(ModelRecord).filter_by(model_code="Ｍ108").one().model_name == "last"


def test_placeholder_brand_codes_do_not_create_brand_master_rows(db):
    rows = [{**row(str(i)), "brand_code": code} for i, code in enumerate(["-", "--", "BRAND"])]
    assert batches.save_model_import_rows(db, "camera", rows)[:2] == (3, 0)
    db.commit()
    assert [brand.brand_code for brand in db.query(BrandRecord)] == ["BRAND"]
    assert db.query(ModelRecord).count() == 3
