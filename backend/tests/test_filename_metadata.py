"""Filename month/platform/country inference tests."""
from app.models.schemas import Category, Country
from app.services.filename_metadata import parse_filename_metadata


def _seed_countries(db):
    db.add_all([
        Country(code="CN", name_cn="中国", name_en="China", currency_code="CNY", region="domestic", is_active=1),
        Country(code="US", name_cn="美国", name_en="United States", currency_code="USD", region="overseas", is_active=1),
        Country(code="CA", name_cn="加拿大", name_en="Canada", currency_code="CAD", region="overseas", is_active=1),
        Country(code="MX", name_cn="墨西哥", name_en="Mexico", currency_code="MXN", region="overseas", is_active=1),
        Country(code="DE", name_cn="德国", name_en="Germany", currency_code="EUR", region="overseas", is_active=0),
        Category(code="action_cameras", name="运动相机"),
        Category(code="router", name="路由器"),
    ])
    db.commit()


def test_parse_canonical_filename(db):
    _seed_countries(db)
    hints = parse_filename_metadata("202609_amazon_US_Fryers.xlsx", db)
    assert hints.month == 202609
    assert hints.platform == "amazon"
    assert hints.country_code == "US"
    assert hints.country_name == "美国"


def test_parse_dash_month_and_aliases(db):
    _seed_countries(db)
    hints = parse_filename_metadata("2026-09_虾皮_MX_AirPurifiers.xlsx", db)
    assert hints.month == 202609
    assert hints.platform == "shopee"
    assert hints.country_code == "MX"


def test_parse_chinese_platform_and_country(db):
    _seed_countries(db)
    hints = parse_filename_metadata("202609_亚马逊_美国_文件.xlsx", db)
    assert hints.platform == "amazon"
    assert hints.country_code == "US"


def test_parse_english_country_name(db):
    _seed_countries(db)
    hints = parse_filename_metadata("202609_amazon_Canada_file.xlsx", db)
    assert hints.country_code == "CA"


def test_parse_ambiguous_month_is_unresolved(db):
    _seed_countries(db)
    hints = parse_filename_metadata("202609_202608_amazon_US_file.xlsx", db)
    assert hints.month is None
    assert hints.month_ambiguous is True


def test_parse_ambiguous_platform_is_unresolved(db):
    _seed_countries(db)
    hints = parse_filename_metadata("202609_amazon_shopee_US_file.xlsx", db)
    assert hints.platform is None
    assert hints.platform_ambiguous is True


def test_parse_inactive_country_is_unresolved(db):
    _seed_countries(db)
    hints = parse_filename_metadata("202609_amazon_DE_file.xlsx", db)
    assert hints.country_code is None


def test_parse_date_token_does_not_become_month(db):
    _seed_countries(db)
    hints = parse_filename_metadata("副本20261008_Top100 202608_Fryers.xlsx", db)
    assert hints.month == 202608
    assert hints.platform is None
    assert hints.country_code is None


def test_parse_category_from_brackets_by_name(db):
    _seed_countries(db)
    hints = parse_filename_metadata("202609_amazon_US_[运动相机]_Fryers.xlsx", db)
    assert hints.category_code == "action_cameras"
    assert hints.category_name == "运动相机"


def test_parse_category_from_brackets_by_code(db):
    _seed_countries(db)
    hints = parse_filename_metadata("202609_amazon_US_[action_cameras]_Fryers.xlsx", db)
    assert hints.category_code == "action_cameras"
    assert hints.category_name == "运动相机"


def test_parse_ambiguous_category_is_unresolved(db):
    _seed_countries(db)
    hints = parse_filename_metadata("202609_amazon_US_[运动相机]_[路由器]_file.xlsx", db)
    assert hints.category_code is None
    assert hints.category_ambiguous is True


def test_parse_unknown_category_leaves_empty_with_warning(db):
    _seed_countries(db)
    hints = parse_filename_metadata("202609_amazon_US_[不存在的品类]_file.xlsx", db)
    assert hints.category_code is None
    assert hints.category_name is None
    assert hints.warnings


def test_parse_category_from_simple_tail_format(db):
    _seed_countries(db)
    hints = parse_filename_metadata("202609_amazon_US_action_cameras.xlsx", db)
    assert hints.category_code == "action_cameras"
    assert hints.category_name == "运动相机"


def test_parse_chinese_category_from_simple_tail_format(db):
    _seed_countries(db)
    hints = parse_filename_metadata("202609_amazon_US_运动相机.xlsx", db)
    assert hints.category_code == "action_cameras"


def test_simple_tail_format_with_description_does_not_guess_category(db):
    _seed_countries(db)
    hints = parse_filename_metadata("202609_amazon_US_运动相机_描述.xlsx", db)
    assert hints.category_code is None
