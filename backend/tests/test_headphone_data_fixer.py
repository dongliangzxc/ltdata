"""
headphone_data_fixer.py 单元测试。
"""
import pytest
from app.services.headphone_data_fixer import fix_brands, seed_metadata_specs
from app.models.schemas import ModelRecord, MetadataSpec, Category


def test_fix_brands_splits_slash(db):
    """brand_code 含斜杠的应被拆分，brand_name 被填入"""
    db.add(ModelRecord(brand_code="EDIFIER/漫步者", model_code="W820NB", category_code="headphone"))
    db.commit()

    stats = fix_brands(db)

    rec = db.query(ModelRecord).filter_by(model_code="W820NB").first()
    assert rec.brand_code == "EDIFIER"
    assert rec.brand_name == "漫步者"
    assert stats["brand_fixed"] == 1


def test_fix_brands_fills_name_no_slash(db):
    """brand_code 无斜杠且 brand_name 为 None 时，用 brand_code 填充 brand_name"""
    db.add(ModelRecord(brand_code="JBL", model_code="TUNE520BT", category_code="headphone", brand_name=None))
    db.commit()

    stats = fix_brands(db)

    rec = db.query(ModelRecord).filter_by(model_code="TUNE520BT").first()
    assert rec.brand_code == "JBL"
    assert rec.brand_name == "JBL"
    assert stats["brand_name_filled"] == 1


def test_fix_brands_skips_already_correct(db):
    """brand_code 无斜杠且 brand_name 已有值的，跳过不修改"""
    db.add(ModelRecord(brand_code="JBL", model_code="TUNE520BT", category_code="headphone", brand_name="JBL"))
    db.commit()

    stats = fix_brands(db)

    assert stats["skipped"] == 1
    assert stats["brand_fixed"] == 0
    assert stats["brand_name_filled"] == 0


def test_fix_brands_multiple_records(db):
    """多条记录混合场景"""
    db.add(ModelRecord(brand_code="Sony/索尼",   model_code="M1", category_code="headphone"))
    db.add(ModelRecord(brand_code="JBL",         model_code="M2", category_code="headphone", brand_name=None))
    db.add(ModelRecord(brand_code="JBL",         model_code="M3", category_code="headphone", brand_name="JBL"))
    db.commit()

    stats = fix_brands(db)

    m1 = db.query(ModelRecord).filter_by(model_code="M1").first()
    assert m1.brand_code == "Sony" and m1.brand_name == "索尼"

    m2 = db.query(ModelRecord).filter_by(model_code="M2").first()
    assert m2.brand_name == "JBL"

    assert stats["brand_fixed"] == 1
    assert stats["brand_name_filled"] == 1
    assert stats["skipped"] == 1


def test_seed_metadata_specs_inserts_17(db):
    """headphone 的 17 条 metadata_specs 应被正确写入"""
    db.add(Category(code="headphone", name="耳机"))
    db.commit()

    count = seed_metadata_specs(db, "headphone")

    assert count == 17
    specs = db.query(MetadataSpec).filter_by(category_code="headphone").all()
    assert len(specs) == 17
    bt = next(s for s in specs if s.spec_name == "bluetooth_version")
    assert bt.spec_type == "number"
    assert bt.decimal_places == 1


def test_seed_metadata_specs_idempotent(db):
    """重复执行不重复插入"""
    db.add(Category(code="headphone", name="耳机"))
    db.commit()

    seed_metadata_specs(db, "headphone")
    count2 = seed_metadata_specs(db, "headphone")

    assert count2 == 0
    assert db.query(MetadataSpec).filter_by(category_code="headphone").count() == 17
