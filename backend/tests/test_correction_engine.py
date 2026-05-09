"""测试修正规则引擎"""
import pytest
from app.models.schemas import (
    CorrectionRule, CleanedDataRecord, UploadFileRecord, CleanJobRecord, RawDataRecord,
)
from app.services.correction_engine import apply_correction_rules


def _setup(db):
    """创建最小测试数据：file + raw + clean_job + cleaned_data"""
    file_rec = UploadFileRecord(filename="t.xlsx", platform="jd", month_range="202602", row_count=1, status="done")
    db.add(file_rec); db.flush()
    raw = RawDataRecord(
        file_id=file_rec.id, platform="jd", month=202602,
        item_name="测试商品", brand_raw="SONY", shop_name="店",
        item_id="eng001", sales_qty=100, sales_amount=10000,
        category_lv1="音箱",
    )
    db.add(raw); db.flush()
    job = CleanJobRecord(file_ids=[file_rec.id], rules={}, status="done", row_in=1, row_out=1)
    db.add(job); db.flush()
    cd = CleanedDataRecord(
        raw_data_id=raw.id, clean_job_id=job.id,
        platform="jd", month=202602, item_id="eng001",
        item_name="测试商品", brand_raw="SONY", shop_name="店",
        sales_qty=100, sales_amount=10000,
        corrected_sales_qty=100, corrected_sales_amount=10000,
    )
    db.add(cd); db.flush()
    return job.id, cd


def test_multiply_rule(db):
    """系数规则：corrected_sales_amount = 10000 * 0.9 = 9000"""
    job_id, cd = _setup(db)
    rule = CorrectionRule(
        name="音箱系数", target="sales_amount", rule_type="multiply",
        value=0.9, priority=1, is_active=1,
    )
    db.add(rule); db.flush()
    apply_correction_rules(db, job_id)
    db.refresh(cd)
    assert float(cd.corrected_sales_amount) == 9000.0
    assert cd.corrected_sales_qty == 100  # 未变


def test_offset_rule(db):
    """加减规则：corrected_sales_qty = 100 - 10 = 90"""
    job_id, cd = _setup(db)
    rule = CorrectionRule(
        name="销量减10", target="sales_qty", rule_type="offset",
        value=-10, priority=1, is_active=1,
    )
    db.add(rule); db.flush()
    apply_correction_rules(db, job_id)
    db.refresh(cd)
    assert cd.corrected_sales_qty == 90


def test_cascade_rules(db):
    """链式叠加：先 ×0.9 再 -500，priority 升序"""
    job_id, cd = _setup(db)
    db.add(CorrectionRule(name="r1", target="sales_amount", rule_type="multiply", value=0.9, priority=1, is_active=1))
    db.add(CorrectionRule(name="r2", target="sales_amount", rule_type="offset",   value=-500, priority=2, is_active=1))
    db.flush()
    apply_correction_rules(db, job_id)
    db.refresh(cd)
    # 10000 * 0.9 = 9000; 9000 - 500 = 8500
    assert float(cd.corrected_sales_amount) == 8500.0


def test_inactive_rule_ignored(db):
    """is_active=0 的规则不生效"""
    job_id, cd = _setup(db)
    rule = CorrectionRule(
        name="停用规则", target="sales_amount", rule_type="multiply",
        value=0.5, priority=1, is_active=0,
    )
    db.add(rule); db.flush()
    apply_correction_rules(db, job_id)
    db.refresh(cd)
    assert float(cd.corrected_sales_amount) == 10000.0  # 未变


def test_negative_result_clamped_to_zero(db):
    """结果为负数时截断为 0"""
    job_id, cd = _setup(db)
    rule = CorrectionRule(
        name="超减", target="sales_qty", rule_type="offset",
        value=-9999, priority=1, is_active=1,
    )
    db.add(rule); db.flush()
    apply_correction_rules(db, job_id)
    db.refresh(cd)
    assert cd.corrected_sales_qty == 0
