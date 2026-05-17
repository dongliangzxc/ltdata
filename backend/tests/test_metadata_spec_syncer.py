"""
metadata_spec_syncer.py 单元测试。
"""
import pytest
from app.services.metadata_spec_syncer import sync_spec_values
from app.models.schemas import Category, MetadataSpec, ModelRecord, ModelSpec


def _add_model(db, category_code: str, model_code: str) -> ModelRecord:
    m = ModelRecord(brand_code="BRAND", model_code=model_code, category_code=category_code)
    db.add(m)
    db.flush()
    return m


def _add_spec(db, model: ModelRecord, spec_name: str, spec_value: str) -> None:
    db.add(ModelSpec(model_id=model.id, spec_name=spec_name, spec_value=spec_value))


def _add_meta(db, category_code: str, spec_name: str, spec_values: str | None = None) -> None:
    db.add(MetadataSpec(
        category_code=category_code,
        spec_name=spec_name,
        spec_type="text",
        required=0,
        single_select=1,
        spec_values=spec_values,
    ))


def test_sync_populates_spec_values(db):
    """基本场景：spec_values 从 model_specs 的 distinct 值填充"""
    _add_meta(db, "headphone", "anc")
    m = _add_model(db, "headphone", "MODEL-A")
    _add_spec(db, m, "anc", "YES")
    _add_spec(db, m, "anc", "YES")   # YES 出现 2 次，频率高于 NO(1 次)，排在首位
    m2 = _add_model(db, "headphone", "MODEL-B")
    _add_spec(db, m2, "anc", "NO")
    db.commit()

    stats = sync_spec_values(db, "headphone")

    spec = db.query(MetadataSpec).filter_by(category_code="headphone", spec_name="anc").first()
    assert spec.spec_values == "YES,NO"
    assert stats["updated"] == 1
    assert stats["skipped"] == 0


def test_sync_orders_by_frequency_descending(db):
    """出现次数多的值排在前面"""
    _add_meta(db, "headphone", "wearing_type")
    for code in ["A", "B", "C"]:
        m = _add_model(db, "headphone", f"M{code}")
        _add_spec(db, m, "wearing_type", "TWS")
    m4 = _add_model(db, "headphone", "M4")
    _add_spec(db, m4, "wearing_type", "Headband")
    db.commit()

    sync_spec_values(db, "headphone")

    spec = db.query(MetadataSpec).filter_by(category_code="headphone", spec_name="wearing_type").first()
    values = spec.spec_values.split(",")
    assert values[0] == "TWS"
    assert values[1] == "Headband"


def test_sync_skips_null_and_empty_values(db):
    """NULL 和空字符串不计入 spec_values"""
    _add_meta(db, "headphone", "anc")
    m = _add_model(db, "headphone", "MODEL-A")
    db.add(ModelSpec(model_id=m.id, spec_name="anc", spec_value=None))
    db.add(ModelSpec(model_id=m.id, spec_name="anc", spec_value=""))
    db.add(ModelSpec(model_id=m.id, spec_name="anc", spec_value="YES"))
    db.commit()

    sync_spec_values(db, "headphone")

    spec = db.query(MetadataSpec).filter_by(category_code="headphone", spec_name="anc").first()
    assert spec.spec_values == "YES"


def test_sync_idempotent(db):
    """相同值重复执行，skipped 计数正确"""
    _add_meta(db, "headphone", "anc")
    m = _add_model(db, "headphone", "MODEL-A")
    _add_spec(db, m, "anc", "YES")
    db.commit()

    sync_spec_values(db, "headphone")
    stats2 = sync_spec_values(db, "headphone")

    assert stats2["skipped"] == 1
    assert stats2["updated"] == 0


def test_sync_all_categories(db):
    """category_code=None 处理所有品类"""
    _add_meta(db, "headphone", "anc")
    _add_meta(db, "SOUNDBAR", "power_type")
    m1 = _add_model(db, "headphone", "HP1")
    _add_spec(db, m1, "anc", "YES")
    m2 = _add_model(db, "SOUNDBAR", "SB1")
    _add_spec(db, m2, "power_type", "Wired")
    db.commit()

    stats = sync_spec_values(db, None)

    hp = db.query(MetadataSpec).filter_by(category_code="headphone", spec_name="anc").first()
    sb = db.query(MetadataSpec).filter_by(category_code="SOUNDBAR", spec_name="power_type").first()
    assert hp.spec_values == "YES"
    assert sb.spec_values == "Wired"
    assert stats["updated"] == 2


def test_sync_ignores_spec_names_not_in_metadata_specs(db):
    """model_specs 里有但 metadata_specs 没定义的 spec_name，不新建记录"""
    m = _add_model(db, "headphone", "MODEL-A")
    db.add(ModelSpec(model_id=m.id, spec_name="unknown_attr", spec_value="FOO"))
    db.commit()

    sync_spec_values(db, "headphone")

    count = db.query(MetadataSpec).filter_by(category_code="headphone").count()
    assert count == 0


def test_sync_value_with_comma_is_stored_as_is(db):
    """spec_value 本身含逗号时，直接存入（已知限制：读取时需调用方自行处理）"""
    _add_meta(db, "headphone", "ai_features")
    m = _add_model(db, "headphone", "MODEL-A")
    _add_spec(db, m, "ai_features", "AI通话,AI降噪")
    db.commit()

    sync_spec_values(db, "headphone")

    spec = db.query(MetadataSpec).filter_by(category_code="headphone", spec_name="ai_features").first()
    # 含逗号的值直接存入，不做转义（已知限制）
    assert "AI通话,AI降噪" in spec.spec_values
