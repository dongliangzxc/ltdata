from pathlib import Path


def test_global_reviewed_results_include_raw_and_adjusted_price():
    source = Path(__file__).resolve().parents[1] / "app" / "api" / "match_api.py"
    text = source.read_text()
    route_index = text.index('@router.get("/reviewed", response_model=None)')
    next_route_index = text.index("\n@router.", route_index + 1)
    route_source = text[route_index:next_route_index]

    assert "price=float(rd.price) if rd.price is not None else None" in route_source
    assert "adjusted_price=float(mr.adjusted_price) if mr.adjusted_price is not None else None" in route_source
