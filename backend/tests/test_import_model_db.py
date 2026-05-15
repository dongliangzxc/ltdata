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
