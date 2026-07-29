from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from app.api.match_api import _build_match_results_summary


def row(raw_qty, cleaned_qty, coefficient, raw_price, adjusted_price):
    return SimpleNamespace(
        raw_sales_qty=raw_qty,
        corrected_sales_qty=cleaned_qty,
        sales_coefficient=coefficient,
        price=raw_price,
        adjusted_price=adjusted_price,
    )


def test_match_results_summary_uses_all_filtered_rows_and_adjustments():
    summary = _build_match_results_summary([
        row(10, None, None, Decimal("100.00"), None),
        row(5, 8, Decimal("2.0000"), Decimal("200.00"), Decimal("250.00")),
        row(None, None, None, None, None),
    ])

    assert summary == {
        "original_price": 133.33,
        "adjusted_price": 192.31,
        "original_sales_qty": 15,
        "adjusted_sales_qty": 26,
        "original_consumption_amount": 2000.00,
        "adjusted_consumption_amount": 5000.00,
    }


def test_match_results_summary_returns_null_averages_when_no_quantity():
    summary = _build_match_results_summary([
        row(None, None, Decimal("2.0000"), Decimal("100.00"), Decimal("120.00")),
    ])

    assert summary == {
        "original_price": None,
        "adjusted_price": None,
        "original_sales_qty": 0,
        "adjusted_sales_qty": 0,
        "original_consumption_amount": 0.00,
        "adjusted_consumption_amount": 0.00,
    }


def test_global_reviewed_route_returns_summary_before_pagination():
    source = Path(__file__).resolve().parents[1] / "app" / "api" / "match_api.py"
    text = source.read_text()
    route_index = text.index('@router.get("/reviewed", response_model=None)')
    next_route_index = text.index("\n@router.", route_index + 1)
    route_source = text[route_index:next_route_index]

    assert "summary_rows =" in route_source
    assert "_build_match_results_summary(summary_rows)" in route_source
    assert "\"summary\": summary" in route_source
    assert route_source.index("summary_rows =") < route_source.index("offset((page - 1) * page_size)")
