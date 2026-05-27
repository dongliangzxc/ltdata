"""
测试 data_cleaner.run_clean 的干扰词过滤和品牌写法标准化逻辑。
"""
import pytest
from app.models.schemas import (
    UploadFileRecord, RawDataRecord, CleanJobRecord,
    NoiseWord, BrandAlias, FilteredItem, CleanedDataRecord,
    DispatchBatch, DispatchItem,
)
from app.services.data_cleaner import run_clean


def _make_raw(db, file_id, item_name, brand_raw="SONY", shop_name="测试店铺"):
    r = RawDataRecord(
        file_id=file_id, platform="jd", month=202507,
        item_name=item_name, brand_raw=brand_raw, shop_name=shop_name,
        item_id=str(id(item_name)), sales_qty=10, price=500,
    )
    db.add(r)
    db.flush()
    return r


def _make_job(db, file_id):
    job = CleanJobRecord(file_ids=[file_id], rules={}, status="done", row_in=0, row_out=0)
    db.add(job)
    db.flush()
    return job


def _make_file(db):
    f = UploadFileRecord(filename="test.xlsx", platform="jd", month_range="202507", row_count=0)
    db.add(f)
    db.flush()
    return f


# ── 干扰词过滤 ──────────────────────────────────────────────

def test_noise_word_filters_matching_item(db):
    """命中干扰词的商品不进入 cleaned_data，进入 filtered_items"""
    f = _make_file(db)
    raw = _make_raw(db, f.id, "索尼HT-A7000 配件包装")
    db.add(NoiseWord(keyword="配件", match_field="item_name"))
    job = _make_job(db, f.id)
    db.commit()

    run_clean(db, job.id, [f.id], {"dedup": True})

    assert db.query(CleanedDataRecord).count() == 0
    fi = db.query(FilteredItem).first()
    assert fi is not None
    assert fi.raw_data_id == raw.id
    assert fi.matched_keyword == "配件"


def test_noise_word_inactive_does_not_filter(db):
    """禁用的干扰词不起作用"""
    f = _make_file(db)
    _make_raw(db, f.id, "索尼HT-A7000 配件包装")
    db.add(NoiseWord(keyword="配件", match_field="item_name", is_active=0))
    job = _make_job(db, f.id)
    db.commit()

    run_clean(db, job.id, [f.id], {"dedup": True})

    assert db.query(CleanedDataRecord).count() == 1
    assert db.query(FilteredItem).count() == 0


def test_noise_word_shop_name_field(db):
    """match_field=shop_name 时匹配店铺名称"""
    f = _make_file(db)
    _make_raw(db, f.id, "索尼HT-A7000", shop_name="官方旗舰店")
    db.add(NoiseWord(keyword="官方旗舰", match_field="shop_name"))
    job = _make_job(db, f.id)
    db.commit()

    run_clean(db, job.id, [f.id], {"dedup": True})

    assert db.query(CleanedDataRecord).count() == 0
    assert db.query(FilteredItem).count() == 1


def test_dispatch_category_clean_only_uses_global_and_same_category_noise_words(db):
    f = _make_file(db)
    raw = _make_raw(db, f.id, "投影仪测试商品")
    batch = DispatchBatch(file_id=f.id, status="done", total_rows=1, dispatched_rows=1, unmatched_rows=0)
    db.add(batch)
    db.flush()
    db.add(DispatchItem(batch_id=batch.id, raw_data_id=raw.id, category_code="projector"))
    db.add(NoiseWord(keyword="测试商品", match_field="item_name", category_code="tv"))
    job = CleanJobRecord(
        file_ids=[f.id],
        rules={},
        status="done",
        row_in=0,
        row_out=0,
        dispatch_batch_id=batch.id,
        dispatch_category_code="projector",
    )
    db.add(job)
    db.commit()

    run_clean(db, job.id, [f.id], {"dedup": True}, batch.id, "projector")

    assert db.query(CleanedDataRecord).count() == 1
    assert db.query(FilteredItem).count() == 0


def test_dispatch_category_clean_uses_same_category_noise_words(db):
    f = _make_file(db)
    raw = _make_raw(db, f.id, "投影仪测试商品")
    batch = DispatchBatch(file_id=f.id, status="done", total_rows=1, dispatched_rows=1, unmatched_rows=0)
    db.add(batch)
    db.flush()
    db.add(DispatchItem(batch_id=batch.id, raw_data_id=raw.id, category_code="projector"))
    db.add(NoiseWord(keyword="测试商品", match_field="item_name", category_code="projector"))
    job = CleanJobRecord(
        file_ids=[f.id],
        rules={},
        status="done",
        row_in=0,
        row_out=0,
        dispatch_batch_id=batch.id,
        dispatch_category_code="projector",
    )
    db.add(job)
    db.commit()

    run_clean(db, job.id, [f.id], {"dedup": True}, batch.id, "projector")

    assert db.query(CleanedDataRecord).count() == 0
    assert db.query(FilteredItem).filter_by(raw_data_id=raw.id).count() == 1


# ── 品牌写法标准化 ──────────────────────────────────────────

def test_brand_alias_sets_brand_std(db):
    """brand_raw 命中 brand_aliases 时，brand_std 被覆盖为标准品牌码"""
    f = _make_file(db)
    _make_raw(db, f.id, "索尼HT-A7000", brand_raw="索尼")
    db.add(BrandAlias(alias_name="索尼", brand_code="SONY"))
    job = _make_job(db, f.id)
    db.commit()

    run_clean(db, job.id, [f.id], {"dedup": True})

    cleaned = db.query(CleanedDataRecord).first()
    assert cleaned is not None
    assert cleaned.brand_std == "SONY"


def test_brand_alias_case_insensitive(db):
    """品牌写法匹配不区分大小写"""
    f = _make_file(db)
    _make_raw(db, f.id, "博士SoundBar", brand_raw="bose")
    db.add(BrandAlias(alias_name="BOSE", brand_code="BOSE"))
    job = _make_job(db, f.id)
    db.commit()

    run_clean(db, job.id, [f.id], {"dedup": True})

    cleaned = db.query(CleanedDataRecord).first()
    assert cleaned.brand_std == "BOSE"


def test_no_alias_keeps_original_brand_std(db):
    """没有匹配的 brand_alias 时，brand_std 保持原有逻辑（brand_raw 填充）"""
    f = _make_file(db)
    _make_raw(db, f.id, "某品牌音箱", brand_raw="未知品牌")
    job = _make_job(db, f.id)
    db.commit()

    run_clean(db, job.id, [f.id], {"dedup": True})

    cleaned = db.query(CleanedDataRecord).first()
    assert cleaned.brand_std == "未知品牌"


# ── row_filtered 计数 ────────────────────────────────────────

def test_row_filtered_count_in_job(db):
    """CleanJobRecord.row_filtered 记录被过滤的行数"""
    f = _make_file(db)
    _make_raw(db, f.id, "配件A")
    _make_raw(db, f.id, "正常商品B")
    db.add(NoiseWord(keyword="配件", match_field="item_name"))
    job = _make_job(db, f.id)
    db.commit()

    run_clean(db, job.id, [f.id], {"dedup": True})

    db.refresh(job)
    assert job.row_filtered == 1
    assert job.row_out == 1


def test_clean_copies_category_lv0(db):
    """清洗后的记录应包含 category_lv0"""
    file_rec = _make_file(db)
    raw = RawDataRecord(
        file_id=file_rec.id, platform="jd", month=202602,
        item_name="测试商品", brand_raw="SONY", shop_name="官方店",
        item_id="lv0test", sales_qty=100, sales_amount=9900,
        category_lv0="手机通讯",
        category_lv1="手机",
    )
    db.add(raw)
    db.flush()
    job = _make_job(db, file_rec.id)
    run_clean(db, job.id, [file_rec.id], {})
    from app.models.schemas import CleanedDataRecord
    cleaned = db.query(CleanedDataRecord).filter_by(clean_job_id=job.id).first()
    assert cleaned is not None
    assert cleaned.category_lv0 == "手机通讯"


def test_clean_calc_price(db):
    """calc_price = sales_amount / sales_qty"""
    file_rec = _make_file(db)
    raw = RawDataRecord(
        file_id=file_rec.id, platform="jd", month=202602,
        item_name="价格测试", brand_raw="SONY", shop_name="官方店",
        item_id="calctest", sales_qty=10, sales_amount=1000,
    )
    db.add(raw)
    db.flush()
    job = _make_job(db, file_rec.id)
    run_clean(db, job.id, [file_rec.id], {})
    from app.models.schemas import CleanedDataRecord
    cleaned = db.query(CleanedDataRecord).filter_by(clean_job_id=job.id).first()
    assert float(cleaned.calc_price) == 100.0
    assert cleaned.corrected_sales_qty == 10
    assert float(cleaned.corrected_sales_amount) == 1000.0


def test_clean_calc_price_zero_qty(db):
    """sales_qty 为 0 时 calc_price 应为 None"""
    file_rec = _make_file(db)
    raw = RawDataRecord(
        file_id=file_rec.id, platform="jd", month=202602,
        item_name="零销量", brand_raw="SONY", shop_name="官方店",
        item_id="zeroqty", sales_qty=0, sales_amount=0,
    )
    db.add(raw)
    db.flush()
    job = _make_job(db, file_rec.id)
    run_clean(db, job.id, [file_rec.id], {})
    from app.models.schemas import CleanedDataRecord
    cleaned = db.query(CleanedDataRecord).filter_by(clean_job_id=job.id).first()
    assert cleaned.calc_price is None
