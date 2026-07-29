from decimal import Decimal
from types import SimpleNamespace

from app.api.match_api import _reviewed_row_payload


def test_reviewed_row_payload_includes_raw_price():
    mr = SimpleNamespace(
        id=1,
        clean_job_id=10,
        raw_data_id=20,
        model_id=30,
        match_status="confirmed",
        matched_by="manual",
        match_source="manual",
        is_disabled=0,
        disable_reason=None,
        brand_identified=1,
        price_flag="ok",
        price_ref=Decimal("98.00"),
        adjusted_price=Decimal("123.45"),
        sales_coefficient=None,
        dispute_reason=None,
        review_note=None,
        reviewed_at=None,
        revertible=False,
    )
    rd = SimpleNamespace(
        item_name="商品",
        item_url="https://example.test/item",
        brand_raw="原品牌",
        sales_qty=12,
        price=Decimal("99.99"),
    )

    payload = _reviewed_row_payload(mr, rd)

    assert payload.price == 99.99
    assert payload.price_ref == 98.00
    assert payload.adjusted_price == 123.45
