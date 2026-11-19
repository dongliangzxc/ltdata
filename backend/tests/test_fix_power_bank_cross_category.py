"""跨品类历史记录修复脚本测试。"""
from app.models.schemas import HistoricalMapping, ModelRecord
from app.scripts.fix_power_bank_cross_category_history import apply_fixes, plan_fixes


def _model(db, *, brand, code, category, name=None):
    model = ModelRecord(
        brand_code=brand,
        brand_name=brand,
        model_code=code,
        model_name=name or code,
        category_code=category,
        status="active",
    )
    db.add(model)
    db.flush()
    return model


def _history(db, *, brand="多马士", category="smartwatch", model_id=None, model_code="待补",
             raw_name="移动电源", raw_code="移动电源", month="2026-10"):
    row = HistoricalMapping(
        platform="jd",
        item_id=f"item-{brand}-{category}-{model_id}-{raw_name}",
        item_name="充电宝",
        item_name_norm="充电宝",
        year=2026,
        month_num=10,
        month=month,
        category_code=category,
        category_name_raw=raw_name,
        category_code_raw=raw_code,
        brand_raw=brand,
        brand_code_raw=brand,
        model_text=model_code,
        model_code=model_code,
        model_id=model_id,
        match_key_type="item_id",
        raw_payload={},
    )
    db.add(row)
    db.flush()
    return row


def test_plan_fixes_finds_cross_category_power_bank_history(db):
    watch_model = _model(db, brand="多马士", code="待补", category="smartwatch")
    wrong = _history(db, brand="多马士", category="smartwatch", model_id=watch_model.id)
    correct = _history(db, brand="爱国者", category="power_bank", model_id=None)
    other = _history(db, brand="某手表", category="smartwatch", raw_name="手表", raw_code="smartwatch")
    db.commit()

    fixes = plan_fixes(db, target_category="power_bank", month="2026-10")

    assert [fix["history_id"] for fix in fixes] == [wrong.id]
    assert fixes[0]["from_category"] == "smartwatch"
    assert fixes[0]["keep_model_id"] is False
    assert fixes[0]["clear_model_code"] is True
    assert correct.id not in {fix["history_id"] for fix in fixes}
    assert other.id not in {fix["history_id"] for fix in fixes}


def test_apply_fixes_updates_category_and_clears_wrong_model(db):
    watch_model = _model(db, brand="多马士", code="待补", category="smartwatch")
    wrong = _history(db, brand="多马士", category="smartwatch", model_id=watch_model.id)
    db.commit()

    fixes = plan_fixes(db, target_category="power_bank", month="2026-10")
    assert apply_fixes(db, fixes, target_category="power_bank") == 1

    db.expire_all()
    updated = db.get(HistoricalMapping, wrong.id)
    assert updated.category_code == "power_bank"
    assert updated.model_id is None
    assert updated.model_code is None
    assert updated.model_text == "待补"
    assert updated.category_name_raw == "移动电源"


def test_plan_fixes_keeps_power_bank_model_link(db):
    power_model = _model(db, brand="ANKER", code="A1", category="power_bank")
    wrong_category = _history(db, brand="ANKER", category="smartwatch", model_id=power_model.id, model_code="A1")
    db.commit()

    fixes = plan_fixes(db, target_category="power_bank", month="2026-10")

    assert len(fixes) == 1
    assert fixes[0]["history_id"] == wrong_category.id
    assert fixes[0]["keep_model_id"] is True
    assert fixes[0]["clear_model_code"] is False

    apply_fixes(db, fixes, target_category="power_bank")
    db.expire_all()
    updated = db.get(HistoricalMapping, wrong_category.id)
    assert updated.category_code == "power_bank"
    assert updated.model_id == power_model.id
    assert updated.model_code == "A1"
