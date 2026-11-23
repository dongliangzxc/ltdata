"""Data warnings cover all source rows, retaining original values for review."""
import csv
from pathlib import Path

import pytest

from app.services.excel_parser import iter_mapped_chunks
from app.services.upload_validation import inspect_upload_values


FIELDS = ["platform", "month", "item_id", "item_name", "sales_qty", "sales_amount", "price"]
MAPPING = {field: field for field in FIELDS}
FIXTURES = Path(__file__).resolve().parents[2] / "sample_data/upload_cases"


def valid_row(**changes):
    return {"platform": "jd", "month": 202610, "item_id": "TEST-ID", "item_name": "测试耳机",
            "sales_qty": 10, "sales_amount": 990, "price": 99, **changes}


def source_csv(tmp_path, rows):
    path = tmp_path / "check.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return path


@pytest.mark.parametrize("field,value", [
    ("sales_qty", "十件"), ("sales_qty", "1.5"), ("sales_qty", "2147483648"),
    ("price", "￥99"), ("price", "1,299.00"), ("price", "inf"),
    ("price", "NaN"), ("price", "10000000000"), ("sales_amount", "1000000000000"),
])
def test_invalid_number_warns_with_original_and_remains_uploadable(tmp_path, field, value):
    path = source_csv(tmp_path, [valid_row(**{field: value})])
    result = inspect_upload_values(path, MAPPING, [])
    assert result["counts"]["invalid_number"] == result["affected_rows"] == 1
    assert result["samples"][0]["value"] == value
    assert result["samples"][0]["row"] == 2
    chunks = list(iter_mapped_chunks(path, MAPPING, [], tolerate_invalid_numbers=True))
    assert chunks[0][0][0][field] is None


@pytest.mark.parametrize("value", ["202613", "202600", "2026-10", "202610.5", "NaN", "1e99"])
def test_invalid_month_is_warned_without_exception(tmp_path, value):
    path = source_csv(tmp_path, [valid_row(month=value)])
    result = inspect_upload_values(path, MAPPING, [])
    assert result["counts"]["invalid_month"] == 1
    assert result["samples"][0]["value"] == value
    chunks = list(iter_mapped_chunks(path, MAPPING, [], tolerate_invalid_numbers=True))
    assert len(chunks[0][0]) == 1


def test_real_zero_and_text_id_are_valid(tmp_path):
    path = source_csv(tmp_path, [valid_row(item_id="00000001", sales_qty=0, sales_amount=0, price=0)])
    result = inspect_upload_values(path, MAPPING, [])
    assert result["issue_count"] == result["affected_rows"] == 0


def test_literal_text_ids_and_blank_values_match_the_warning(tmp_path):
    path = source_csv(tmp_path, [valid_row(item_id="NA", item_name="NA"), valid_row(item_id=" ", item_name=" ")])
    result = inspect_upload_values(path, MAPPING, [])
    assert result["counts"]["missing_required"] == 2
    chunks = list(iter_mapped_chunks(path, MAPPING, [], tolerate_invalid_numbers=True))
    rows = chunks[0][0]
    assert rows[0]["item_id"] == rows[0]["item_name"] == "NA"
    assert rows[1]["item_id"] is rows[1]["item_name"] is None


def test_counts_cover_whole_file_but_examples_are_bounded(tmp_path):
    path = source_csv(tmp_path, [valid_row(item_id="") for _ in range(75)])
    result = inspect_upload_values(path, MAPPING, [])
    assert result["total_rows"] == result["affected_rows"] == result["issue_count"] == 75
    assert len(result["samples"]) == 50
    assert result["samples"][-1]["row"] == 51
    assert result["truncated"] is True


def test_checks_include_rows_beyond_first_chunk(tmp_path):
    rows = [valid_row(item_id=f"TEST-{index}") for index in range(5002)]
    rows[0]["price"] = "错误价格"
    rows[-1]["sales_qty"] = "错误销量"
    path = source_csv(tmp_path, rows)
    result = inspect_upload_values(path, MAPPING, [])
    assert result["total_rows"] == 5002
    assert result["issue_count"] == result["affected_rows"] == 2
    assert [sample["row"] for sample in result["samples"]] == [2, 5003]


def test_filename_fills_month_and_platform_before_check(tmp_path):
    path = source_csv(tmp_path, [valid_row(month="", platform="")])
    result = inspect_upload_values(path, MAPPING, [], filename_month=202610, filename_platform="amazon")
    assert result["issue_count"] == 0


def test_ignored_optional_values_are_not_checked(tmp_path):
    path = source_csv(tmp_path, [valid_row()])
    mapping = {**MAPPING, "item_name": "ref_price"}
    result = inspect_upload_values(path, mapping, ["item_name"])
    assert result["counts"]["invalid_number"] == 0
    assert result["counts"]["missing_required"] == 1


def test_csv_blank_lines_and_multiline_values_keep_record_numbers(tmp_path):
    path = source_csv(tmp_path, [valid_row(item_name='测试, "引号"\n第二行'), valid_row(price="异常")])
    text = path.read_text(encoding="utf-8-sig")
    header, data = text.split("\n", 1)
    path.write_text(header + "\n\n" + data, encoding="utf-8-sig")
    result = inspect_upload_values(path, MAPPING, [])
    assert result["total_rows"] == 2
    assert result["samples"][0]["row"] == 4


def test_excel_blank_rows_keep_actual_sheet_row_numbers(tmp_path):
    from openpyxl import load_workbook

    workbook = load_workbook(FIXTURES / "normal/jd.xlsx")
    workbook.active.insert_rows(2)
    workbook.active["G4"] = "异常价格"
    path = tmp_path / "check.xlsx"
    workbook.save(path)
    workbook.close()
    headers = ["平台", "月", "宝贝ID", "宝贝名称", "销量", "销售额", "价格"]
    result = inspect_upload_values(path, dict(zip(headers, FIELDS)), [])
    assert result["total_rows"] == 3
    assert result["samples"][0]["row"] == 4
    assert result["samples"][0]["column"] == "价格"
