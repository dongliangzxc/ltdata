from datetime import datetime
from decimal import Decimal

from app.services.publisher import _build_published_item_params, _count_unique_published_items


def _row(**overrides):
    base = {
        "match_result_id": 1,
        "platform": "JD",
        "month": 202605,
        "category_lv0": "消费电子",
        "category_lv1": "影音娱乐",
        "category_lv2": None,
        "category_lv3": None,
        "category_lv4": None,
        "category_lv5": None,
        "item_id": "sku-1",
        "item_name": "商品1",
        "item_image": None,
        "item_url": "https://example.test/sku-1",
        "ref_price": Decimal("199.00"),
        "shop_name": "店铺",
        "sales_qty": 100,
        "sales_amount": Decimal("19900.00"),
        "price": Decimal("199.00"),
        "brand_code": "BR",
        "brand_name": "品牌",
        "model_code": "M1",
        "model_name": "型号1",
        "category_name": "耳机",
        "calc_price": Decimal("199.00"),
        "corrected_sales_qty": None,
        "corrected_sales_amount": None,
        "sales_coefficient": None,
    }
    base.update(overrides)
    return base


def test_build_published_item_applies_coefficient_after_correction_rule_base():
    item = _build_published_item_params(
        _row(corrected_sales_qty=80, sales_coefficient=Decimal("1.5000")),
        clean_job_id=7,
        published_at=datetime(2026, 5, 19),
    )

    assert item["corrected_sales_qty"] == 120


def test_build_published_item_preserves_base_quantity_when_coefficient_null():
    item = _build_published_item_params(
        _row(corrected_sales_qty=80, sales_coefficient=None),
        clean_job_id=7,
        published_at=datetime(2026, 5, 19),
    )

    assert item["corrected_sales_qty"] == 80


def test_build_published_item_zero_coefficient_writes_zero_quantity():
    item = _build_published_item_params(
        _row(corrected_sales_qty=80, sales_coefficient=Decimal("0.0000")),
        clean_job_id=7,
        published_at=datetime(2026, 5, 19),
    )

    assert item["corrected_sales_qty"] == 0


def test_build_published_item_keeps_raw_sales_and_amounts_unchanged():
    item = _build_published_item_params(
        _row(
            sales_qty=100,
            sales_amount=Decimal("19900.00"),
            corrected_sales_qty=80,
            corrected_sales_amount=Decimal("15920.00"),
            sales_coefficient=Decimal("2.0000"),
        ),
        clean_job_id=7,
        published_at=datetime(2026, 5, 19),
    )

    assert item["sales_qty"] == 100
    assert item["sales_amount"] == Decimal("19900.00")
    assert item["corrected_sales_amount"] == Decimal("15920.00")


def test_count_unique_published_items_matches_analytics_unique_key():
    published_at = datetime(2026, 5, 19)
    items = [
        _build_published_item_params(
            _row(match_result_id=1, platform="jd", item_id="sku-1", month=202605),
            clean_job_id=7,
            published_at=published_at,
        ),
        _build_published_item_params(
            _row(match_result_id=2, platform="jd", item_id="sku-1", month=202605),
            clean_job_id=7,
            published_at=published_at,
        ),
        _build_published_item_params(
            _row(match_result_id=3, platform="jd", item_id="sku-2", month=202605),
            clean_job_id=7,
            published_at=published_at,
        ),
    ]

    assert _count_unique_published_items(items) == 2
