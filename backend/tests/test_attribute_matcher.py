"""
attribute_matcher.py 单元测试
使用内存 SQLite，不依赖 MySQL。
"""
from app.models.schemas import (
    UploadFileRecord, RawDataRecord, CleanJobRecord, CleanedDataRecord,
    ModelRecord, MatchResult, AttrRule, MatchResultAttr,
)
from app.services.attribute_matcher import run_attribute_matching


_seed_counter = 0


def _seed_match_result(db, *, item_name, brand_raw="SONY", category_name="soundbar"):
    global _seed_counter
    _seed_counter += 1
    upload = UploadFileRecord(filename="t.xlsx", status="done", row_count=1)
    db.add(upload)
    db.flush()
    raw = RawDataRecord(file_id=upload.id, item_name=item_name, brand_raw=brand_raw)
    db.add(raw)
    db.flush()
    job = CleanJobRecord(file_ids=[upload.id], rules={}, status="done", row_in=1, row_out=1)
    db.add(job)
    db.flush()
    model = ModelRecord(brand_code="SONY", model_code=f"HT-A7000-{_seed_counter}", category_name=category_name)
    db.add(model)
    db.flush()
    mr = MatchResult(
        clean_job_id=job.id,
        raw_data_id=raw.id,
        model_id=model.id,
        match_status="matched",
        matched_by="auto",
    )
    db.add(mr)
    db.flush()
    return mr.id, model.id


def test_contains_rule_matches(db):
    """全局 contains 规则命中商品名称，写入 match_result_attrs"""
    mr_id, _ = _seed_match_result(db, item_name="Sony HT-A7000 2.1声道 回音壁")
    rule = AttrRule(keyword="2.1声道", match_type="contains", attr_name="声道", attr_value="2.1声道", category_code=None)
    db.add(rule)
    db.flush()

    result = run_attribute_matching(db, [mr_id])

    assert result["matched_attrs"] == 1
    attrs = db.query(MatchResultAttr).filter(MatchResultAttr.match_result_id == mr_id).all()
    assert len(attrs) == 1
    assert attrs[0].attr_name == "声道"
    assert attrs[0].attr_value == "2.1声道"


def test_exact_rule_requires_full_match(db):
    """exact 规则只在 item_name 完全等于 keyword 时命中"""
    mr_id, _ = _seed_match_result(db, item_name="HT-A7000")
    rule = AttrRule(keyword="HT-A7000", match_type="exact", attr_name="型号全名", attr_value="HT-A7000", category_code=None)
    db.add(rule)
    db.flush()

    result = run_attribute_matching(db, [mr_id])
    assert result["matched_attrs"] == 1

    # 名称不完全相等时不命中
    mr_id2, _ = _seed_match_result(db, item_name="Sony HT-A7000 回音壁")
    result2 = run_attribute_matching(db, [mr_id2])
    assert result2["matched_attrs"] == 0


def test_inactive_rule_ignored(db):
    """is_active=0 的规则不参与匹配"""
    mr_id, _ = _seed_match_result(db, item_name="Sony 65英寸 平板")
    rule = AttrRule(keyword="65英寸", match_type="contains", attr_name="尺寸", attr_value="65英寸",
                    category_code=None, is_active=0)
    db.add(rule)
    db.flush()

    result = run_attribute_matching(db, [mr_id])
    assert result["matched_attrs"] == 0


def test_multiple_rules_produce_multiple_attrs(db):
    """多条规则可以给同一商品打多个属性"""
    mr_id, _ = _seed_match_result(db, item_name="Sony 65英寸 OLED 智能平板")
    db.add(AttrRule(keyword="65英寸", match_type="contains", attr_name="尺寸", attr_value="65英寸", category_code=None))
    db.add(AttrRule(keyword="OLED", match_type="contains", attr_name="屏幕类型", attr_value="OLED", category_code=None))
    db.flush()

    result = run_attribute_matching(db, [mr_id])
    assert result["matched_attrs"] == 2
    attrs = {a.attr_name: a.attr_value for a in db.query(MatchResultAttr).filter(MatchResultAttr.match_result_id == mr_id).all()}
    assert attrs["尺寸"] == "65英寸"
    assert attrs["屏幕类型"] == "OLED"


def test_category_rule_overrides_global(db):
    """品类规则覆盖同一 attr_name 的全局规则"""
    mr_id, _ = _seed_match_result(db, item_name="Sony 65英寸 旗舰款", category_name="智能平板")
    # 全局规则
    db.add(AttrRule(keyword="65英寸", match_type="contains", attr_name="尺寸", attr_value="65寸(全局)",
                    category_code=None, priority=100))
    # 品类规则（同优先级）
    db.add(AttrRule(keyword="65英寸", match_type="contains", attr_name="尺寸", attr_value="65英寸(品类)",
                    category_code="智能平板", priority=100))
    db.flush()

    run_attribute_matching(db, [mr_id])
    attrs = db.query(MatchResultAttr).filter(MatchResultAttr.match_result_id == mr_id).all()
    assert len(attrs) == 1
    assert attrs[0].attr_value == "65英寸(品类)"


def test_category_rule_ignored_for_other_category(db):
    """其他品类的规则对本品类不生效"""
    mr_id, _ = _seed_match_result(db, item_name="Sony 65英寸 旗舰款", category_name="soundbar")
    db.add(AttrRule(keyword="65英寸", match_type="contains", attr_name="尺寸", attr_value="65英寸",
                    category_code="智能平板"))  # 只对智能平板生效
    db.flush()

    result = run_attribute_matching(db, [mr_id])
    assert result["matched_attrs"] == 0


def test_upsert_updates_existing_attr(db):
    """重跑时同一 attr_name 已有记录则更新，不重复插入"""
    mr_id, _ = _seed_match_result(db, item_name="Sony 65英寸 旗舰款")
    rule = AttrRule(keyword="65英寸", match_type="contains", attr_name="尺寸", attr_value="65英寸", category_code=None)
    db.add(rule)
    db.flush()

    # 第一次跑
    run_attribute_matching(db, [mr_id])
    # 第二次跑（模拟规则重跑）
    run_attribute_matching(db, [mr_id])

    count = db.query(MatchResultAttr).filter(MatchResultAttr.match_result_id == mr_id).count()
    assert count == 1  # 不重复


def test_empty_ids_returns_zero(db):
    """空 match_result_ids 直接返回 0，不报错"""
    result = run_attribute_matching(db, [])
    assert result["matched_attrs"] == 0
    assert result["items_processed"] == 0
