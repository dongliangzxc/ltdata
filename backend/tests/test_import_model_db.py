"""Tests for model_db_importer cleaning utilities."""
import pytest
from app.services.model_db_importer import (
    is_dirty_model, is_dirty_brand, normalize_platform,
    extract_item_id, has_attributes, ATTR_COL_MAP,
)

ATTR_COLS = list(ATTR_COL_MAP.keys())


# ── is_dirty_model ──────────────────────────────────────────────
def test_dirty_model_none():
    assert is_dirty_model(None) is True

def test_dirty_model_pure_numeric():
    assert is_dirty_model("12345") is True

def test_dirty_model_id_colon():
    assert is_dirty_model("id:10113747293132") is True

def test_dirty_model_id_equals():
    assert is_dirty_model("id=697603607103") is True

def test_dirty_model_too_short():
    assert is_dirty_model("G2") is True  # len == 2, 边界值

def test_dirty_model_ok():
    assert is_dirty_model("G2 无线版") is False
    assert is_dirty_model("WH-1000XM5") is False


# ── is_dirty_brand ──────────────────────────────────────────────
def test_dirty_brand_none():
    assert is_dirty_brand(None) is True

def test_dirty_brand_too_short():
    assert is_dirty_brand("R") is True

def test_dirty_brand_shop_name():
    # 9 个中文字符，超过阈值 8
    assert is_dirty_brand("华恒智能数码科技经营部") is True

def test_dirty_brand_exactly_eight_chinese():
    # 恰好 8 个中文字符，应该通过
    assert is_dirty_brand("华恒智能数码科技") is False

def test_dirty_brand_ok():
    assert is_dirty_brand("EDIFIER/漫步者") is False
    assert is_dirty_brand("SONY") is False


# ── normalize_platform ──────────────────────────────────────────
def test_normalize_jd_upper():
    assert normalize_platform("JD") == "jd"

def test_normalize_jd_lower():
    assert normalize_platform("jd") == "jd"

def test_normalize_taobao_cn():
    assert normalize_platform("淘宝") == "taobao"

def test_normalize_tmall_cn():
    assert normalize_platform("天猫") == "tmall"

def test_normalize_unknown():
    assert normalize_platform("Suning") == "suning"


# ── extract_item_id ─────────────────────────────────────────────
def test_extract_jd():
    url = "https://item.jd.com/10172208842988.html"
    assert extract_item_id(url, "jd") == "10172208842988"

def test_extract_taobao_query_param():
    url = "https://item.taobao.com/item.htm?id=123456789"
    assert extract_item_id(url, "taobao") == "123456789"

def test_extract_tmall_query_param():
    url = "https://detail.tmall.com/item.htm?id=987654321&xx=1"
    assert extract_item_id(url, "tmall") == "987654321"

def test_extract_fail_jd_no_match():
    assert extract_item_id("https://item.jd.com/xxx.html", "jd") is None

def test_extract_empty_url():
    assert extract_item_id("", "jd") is None

def test_extract_none_url():
    assert extract_item_id(None, "jd") is None


# ── has_attributes ──────────────────────────────────────────────
def test_has_attributes_true():
    row = {"佩戴类型": "Headband", "ANC": "NULL"}
    assert has_attributes(row, ATTR_COLS) is True

def test_has_attributes_all_null_string():
    row = {col: "NULL" for col in ATTR_COLS}
    assert has_attributes(row, ATTR_COLS) is False

def test_has_attributes_all_none():
    row = {col: None for col in ATTR_COLS}
    assert has_attributes(row, ATTR_COLS) is False

def test_has_attributes_all_empty_string():
    row = {col: "" for col in ATTR_COLS}
    assert has_attributes(row, ATTR_COLS) is False


# ── import_model_db 集成测试（SQLite 内存 DB）──────────────────
import os
import openpyxl
from app.models.schemas import ModelRecord, ModelSpec, ItemUrlMapping


def _make_excel(rows: list, tmp_path) -> str:
    """生成测试用 Excel 文件，列顺序与耳机数据库一致。"""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sheet2"
    headers = [
        "平台", "宝贝名称", "宝贝链接", "销量", "销售额", "ASP", "品牌", "型号",
        "佩戴类型", "In-ear Type", "开放式外观", "Power Type", "Bluetooth Version",
        "Sport", "Gaming", "HIFI", "ANC", "ENC", "Fast Charging", "IP Marking",
        "Health Monitoring", "Touch Screen Monitor", "骨传导", "AI", "AI+功能",
    ]
    ws.append(headers)
    for row in rows:
        ws.append(row)
    path = os.path.join(str(tmp_path), "test.xlsx")
    wb.save(path)
    return path


def _valid_row(platform="JD", brand="EDIFIER/漫步者", model="G2 无线版",
               url="https://item.jd.com/100001.html"):
    """构造一条完整有效行（25列）。"""
    return [
        platform, "商品名称", url, 10, 2500, 250, brand, model,
        "Headband", "Over Ear", "NULL", "Hybrid", "5.4",
        "NO", "YES", "NO", "NO", "YES", "NO", "NO", "NO", "NO", "NO", "YES", "AI降噪",
    ]


def _seed_category(db, code="headphone"):
    from app.models.schemas import Category
    cat = Category(code=code, name="耳机")
    db.add(cat)
    db.flush()


def test_import_creates_model_and_specs(db, tmp_path):
    from app.services.model_db_importer import import_model_db
    _seed_category(db)
    path = _make_excel([_valid_row()], tmp_path)

    stats = import_model_db(path, "headphone", db)

    assert stats["models_new"] == 1
    assert stats["urls_new"] == 1

    model = db.query(ModelRecord).filter_by(
        brand_code="EDIFIER/漫步者", model_code="G2 无线版"
    ).first()
    assert model is not None
    assert model.category_code == "headphone"

    spec_names = {s.spec_name for s in db.query(ModelSpec).filter_by(model_id=model.id).all()}
    assert "wearing_type" in spec_names
    assert "gaming" in spec_names
    assert "ai_features" in spec_names


def test_dirty_rows_are_skipped(db, tmp_path):
    from app.services.model_db_importer import import_model_db
    _seed_category(db)
    rows = [
        _valid_row(model="id:12345"),           # dirty model
        _valid_row(brand="华恒智能数码科技经营部"),  # dirty brand (9 Chinese chars)
        _valid_row(url=None),                   # no URL
    ]
    path = _make_excel(rows, tmp_path)
    stats = import_model_db(path, "headphone", db)

    assert stats["models_new"] == 0
    assert stats["skip_model"] >= 1
    assert stats["skip_brand"] >= 1
    assert stats["skip_url"] >= 1


def test_dry_run_writes_nothing(db, tmp_path):
    from app.services.model_db_importer import import_model_db
    _seed_category(db)
    path = _make_excel([_valid_row()], tmp_path)

    stats = import_model_db(path, "headphone", db, dry_run=True)

    assert stats["unique_models"] == 1
    assert db.query(ModelRecord).count() == 0


def test_invalid_category_raises(db, tmp_path):
    from app.services.model_db_importer import import_model_db
    path = _make_excel([_valid_row()], tmp_path)
    with pytest.raises(ValueError, match="Category 'nonexistent' not found"):
        import_model_db(path, "nonexistent", db)


def test_same_model_two_urls(db, tmp_path):
    from app.services.model_db_importer import import_model_db
    _seed_category(db)
    rows = [
        _valid_row(url="https://item.jd.com/100001.html"),
        _valid_row(url="https://item.jd.com/100002.html"),
    ]
    path = _make_excel(rows, tmp_path)
    stats = import_model_db(path, "headphone", db)

    assert stats["models_new"] == 1   # 同一型号只建一条
    assert stats["urls_new"] == 2     # 两条 URL 映射


def test_idempotent_rerun(db, tmp_path):
    from app.services.model_db_importer import import_model_db
    _seed_category(db)
    path = _make_excel([_valid_row()], tmp_path)

    import_model_db(path, "headphone", db)
    stats2 = import_model_db(path, "headphone", db)

    assert stats2["models_new"] == 0
    assert stats2["models_existing"] == 1
    assert db.query(ModelRecord).count() == 1   # 不重复创建
