"""Tests for import_helper shared utilities."""
import io
import pytest
from pathlib import Path
from app.services.import_helper import (
    col_fingerprint, jaccard, read_columns,
)


def test_col_fingerprint_deterministic():
    cols = ["宝贝ID", "销量", "月"]
    fp1 = col_fingerprint(cols)
    fp2 = col_fingerprint(["月", "宝贝ID", "销量"])  # different order, same result
    assert fp1 == fp2
    assert len(fp1) == 32  # MD5 hex


def test_col_fingerprint_differs_for_different_cols():
    assert col_fingerprint(["A", "B"]) != col_fingerprint(["A", "C"])


def test_jaccard_identical():
    assert jaccard({"A", "B"}, {"A", "B"}) == 1.0


def test_jaccard_disjoint():
    assert jaccard({"A"}, {"B"}) == 0.0


def test_jaccard_partial():
    score = jaccard({"A", "B", "C"}, {"A", "B", "D"})
    assert abs(score - 0.5) < 0.001  # intersection=2, union=4


def test_jaccard_both_empty():
    assert jaccard(set(), set()) == 1.0


def test_read_columns_xlsx(tmp_path):
    """read_columns can read a real xlsx file."""
    import pandas as pd
    df = pd.DataFrame({"宝贝ID": ["123"], "销量": [5], "月": [202507]})
    p = tmp_path / "test.xlsx"
    df.to_excel(p, index=False)
    cols = read_columns(p)
    assert "宝贝ID" in cols
    assert "销量" in cols
    assert "月" in cols
