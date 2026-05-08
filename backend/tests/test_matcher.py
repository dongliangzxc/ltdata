"""
matcher.py 单元测试
使用内存 SQLite，不依赖 MySQL。

包含：
  - 核心回归测试（S1-S4 匹配逻辑）
  - S0.5 显式规则和 brand_identified 字段测试（TDD）
"""
from app.models.schemas import (
    UploadFileRecord, RawDataRecord, CleanJobRecord, CleanedDataRecord,
    ModelRecord, ModelAlias, MatchResult, MatchRule,
)
from app.services.matcher import run_match


def _seed(db, *, brand_code, model_code, brand_name=None, model_name=None, category_name="TEST"):
    """向 db 插入一条 ModelRecord，返回该记录。"""
    m = ModelRecord(
        brand_code=brand_code,
        model_code=model_code,
        brand_name=brand_name or brand_code,
        model_name=model_name or model_code,
        category_code=category_name,
    )
    db.add(m)
    db.flush()
    return m


def _seed_clean_row(db, *, brand_raw, item_name):
    """插入 UploadFileRecord + RawDataRecord + CleanJobRecord + CleanedDataRecord，返回 clean_job_id。"""
    # 创建 FK 父级记录
    upload = UploadFileRecord(filename="test.xlsx", status="done", row_count=1)
    db.add(upload)
    db.flush()
    raw = RawDataRecord(file_id=upload.id, item_name=item_name, brand_raw=brand_raw)
    db.add(raw)
    db.flush()

    job = CleanJobRecord(file_ids=[upload.id], rules={}, status="done", row_in=1, row_out=1)
    db.add(job)
    db.flush()
    row = CleanedDataRecord(
        raw_data_id=raw.id,
        clean_job_id=job.id,
        brand_raw=brand_raw,
        item_name=item_name,
    )
    db.add(row)
    db.flush()
    return job.id


def _setup_base(db):
    """创建最小可用的 model + cleaned_data"""
    model = ModelRecord(brand_code="SONY", model_code="HT-A7000", brand_name="Sony")
    db.add(model)
    f = UploadFileRecord(filename="t.xlsx", platform="jd", month_range="202507", row_count=1)
    db.add(f)
    db.flush()

    raw = RawDataRecord(
        file_id=f.id, platform="jd", month=202507,
        item_name="索尼 HT-A7000 回音壁", brand_raw="索尼",
        item_id="001", sales_qty=5, price=3999,
    )
    db.add(raw)
    db.flush()

    job = CleanJobRecord(file_ids=[f.id], rules={}, status="done", row_in=1, row_out=1)
    db.add(job)
    db.flush()

    cleaned = CleanedDataRecord(
        raw_data_id=raw.id, clean_job_id=job.id,
        platform="jd", month=202507,
        item_name="索尼 HT-A7000 回音壁", brand_raw="索尼",
        item_id="001", sales_qty=5, price=3999, brand_std="SONY",
    )
    db.add(cleaned)
    db.commit()
    return model, job


# ── 核心回归测试 ────────────────────────────────────────────────

def test_brand_matched_but_no_model_should_be_pending(db):
    """品牌识别到但所有型号都不在商品名中 → pending，不应跨品牌误匹配。"""
    # EDIFIER 品牌，型号 B1/B2/G7000，均不在商品名里
    _seed(db, brand_code="EDIFIER", model_code="B1")
    _seed(db, brand_code="EDIFIER", model_code="B2")
    _seed(db, brand_code="EDIFIER", model_code="G7000")
    # 另一品牌有 5 字符型号，不能被误匹配
    _seed(db, brand_code="OTHER", model_code="HALO1")

    item_name = "漫步者 EDIFIERHalo Soundbar桌面蓝牙音箱游戏电脑音响"
    clean_job_id = _seed_clean_row(db, brand_raw="漫步者", item_name=item_name)
    db.commit()

    run_match(db, clean_job_id)

    result = db.query(MatchResult).filter(MatchResult.clean_job_id == clean_job_id).first()
    assert result is not None
    assert result.match_status == "pending", (
        f"期望 pending，实际 {result.match_status}，model_id={result.model_id}"
    )
    assert result.model_id is None


def test_model_code_in_item_name_should_match(db):
    """model_code 出现在商品名中 → matched，match_source=s1。"""
    _seed(db, brand_code="EDIFIER", model_code="G7000", brand_name="漫步者")
    item_name = "漫步者 EDIFIER G7000 回音壁"
    clean_job_id = _seed_clean_row(db, brand_raw="漫步者", item_name=item_name)
    db.commit()

    run_match(db, clean_job_id)

    result = db.query(MatchResult).filter(MatchResult.clean_job_id == clean_job_id).first()
    assert result.match_status == "matched"
    assert result.match_source == "s1"
    assert result.model_id is not None


def test_s4_fires_when_no_brand_identified(db):
    """无品牌线索时，S4 长码兜底应生效。"""
    _seed(db, brand_code="UNKNOWN", model_code="HALO1X", brand_name="unknown_brand")
    # 商品名不含任何品牌，但含有 5+ 字符型号码
    item_name = "某款 HALO1X 蓝牙音箱"
    clean_job_id = _seed_clean_row(db, brand_raw=None, item_name=item_name)
    db.commit()

    run_match(db, clean_job_id)

    result = db.query(MatchResult).filter(MatchResult.clean_job_id == clean_job_id).first()
    assert result.match_status == "matched"
    assert result.match_source == "s4"


def test_match_source_s2(db):
    """brand_code 出现在 item_name 中（不在 brand_raw 中）→ match_source=s2。"""
    _seed(db, brand_code="PHILIPS", model_code="HTL3320", brand_name="飞利浦")
    # brand_raw 为空，item_name 含 brand_code "PHILIPS" 和型号 "HTL3320"
    item_name = "飞利浦 PHILIPS HTL3320 回音壁"
    clean_job_id = _seed_clean_row(db, brand_raw=None, item_name=item_name)
    db.commit()

    run_match(db, clean_job_id)

    result = db.query(MatchResult).filter(MatchResult.clean_job_id == clean_job_id).first()
    assert result.match_status == "matched"
    assert result.match_source == "s2"


def test_alias_match_within_brand(db):
    """别名出现在 item_name 中，应命中对应型号（品牌内匹配）。"""
    m = _seed(db, brand_code="EDIFIER", brand_name="漫步者", model_code="B2-PRO")
    alias = ModelAlias(model_id=m.id, alias_code="B2PRO")
    db.add(alias)

    item_name = "漫步者 EDIFIER B2PRO 回音壁蓝牙音箱"
    clean_job_id = _seed_clean_row(db, brand_raw="漫步者", item_name=item_name)
    db.commit()

    run_match(db, clean_job_id)

    result = db.query(MatchResult).filter(MatchResult.clean_job_id == clean_job_id).first()
    assert result.match_status == "matched", f"期望 matched，实际 {result.match_status}"
    assert result.model_id == m.id


def test_alias_not_cross_brand(db):
    """别名不跨品牌匹配：品牌B的商品不应命中品牌A的别名。"""
    m_a = _seed(db, brand_code="BRAND_A", brand_name="品牌A", model_code="X100")
    alias = ModelAlias(model_id=m_a.id, alias_code="X100ALIAS")
    db.add(alias)

    _seed(db, brand_code="BRAND_B", brand_name="品牌B", model_code="Y200")
    item_name = "品牌B BRAND_B X100ALIAS 音箱"
    clean_job_id = _seed_clean_row(db, brand_raw="品牌B", item_name=item_name)
    db.commit()

    run_match(db, clean_job_id)

    result = db.query(MatchResult).filter(MatchResult.clean_job_id == clean_job_id).first()
    assert result.match_status == "pending", f"期望 pending，实际 {result.match_status}"


# ── S0.5 显式规则 + brand_identified 测试 ───────────────────────

def test_s05_contains_rule_matches(db):
    """S0.5 contains 规则命中时 match_source 为 s0.5"""
    model, job = _setup_base(db)
    db.add(MatchRule(keyword="HT-A7000", match_type="contains", model_id=model.id, priority=10))
    db.commit()

    run_match(db, job.id)

    result = db.query(MatchResult).filter(MatchResult.clean_job_id == job.id).first()
    assert result is not None
    assert result.match_source == "s0.5"
    assert result.model_id == model.id
    assert result.match_status == "matched"


def test_s05_exact_rule_requires_full_match(db):
    """S0.5 exact 规则只在 item_name 完全等于关键词时命中"""
    model, job = _setup_base(db)
    # exact 规则，但 item_name 只是包含，不完全等于
    db.add(MatchRule(keyword="HT-A7000", match_type="exact", model_id=model.id, priority=10))
    db.commit()

    run_match(db, job.id)

    result = db.query(MatchResult).filter(MatchResult.clean_job_id == job.id).first()
    # 不应命中 exact 规则（item_name 是"索尼 HT-A7000 回音壁"，不等于"HT-A7000"）
    assert result.match_source != "s0.5"


def test_s05_inactive_rule_ignored(db):
    """禁用的规则不参与匹配"""
    model, job = _setup_base(db)
    db.add(MatchRule(keyword="HT-A7000", match_type="contains", model_id=model.id, priority=10, is_active=0))
    db.commit()

    run_match(db, job.id)

    result = db.query(MatchResult).filter(MatchResult.clean_job_id == job.id).first()
    assert result.match_source != "s0.5"


def test_brand_identified_false_when_brand_unknown(db):
    """品牌完全无法识别时 brand_identified=0"""
    model = ModelRecord(brand_code="SONY", model_code="HT-A7000", brand_name="Sony")
    db.add(model)
    f = UploadFileRecord(filename="t.xlsx", platform="jd", month_range="202507", row_count=1)
    db.add(f)
    db.flush()

    raw = RawDataRecord(
        file_id=f.id, platform="jd", month=202507,
        item_name="未知品牌音箱XY999", brand_raw="未知品牌",
        item_id="002", sales_qty=1, price=99,
    )
    db.add(raw)
    db.flush()

    job = CleanJobRecord(file_ids=[f.id], rules={}, status="done", row_in=1, row_out=1)
    db.add(job)
    db.flush()

    cleaned = CleanedDataRecord(
        raw_data_id=raw.id, clean_job_id=job.id,
        platform="jd", month=202507,
        item_name="未知品牌音箱XY999", brand_raw="未知品牌",
        item_id="002", sales_qty=1, price=99, brand_std="未知品牌",
    )
    db.add(cleaned)
    db.commit()

    run_match(db, job.id)

    result = db.query(MatchResult).filter(MatchResult.clean_job_id == job.id).first()
    assert result.brand_identified == 0
