"""
测试 parse_raw_excel 对 CSV 格式的兼容性。
"""
import csv
from pathlib import Path
import pytest
from app.services.excel_parser import parse_raw_excel


def _write_csv(path: Path, rows: list[dict], encoding: str = "utf-8-sig"):
    """工具函数：写标准 JD 格式 CSV"""
    fieldnames = [
        "平台", "月", "Lv0类目名称(逐月固定)", "Lv1类目名称(逐月固定)",
        "Lv2类目名称(逐月固定)", "宝贝ID", "宝贝名称", "宝贝图片",
        "宝贝链接", "参考价格", "宝贝品牌(bid)", "宝贝店铺名称", "销量", "销售额",
    ]
    with open(path, "w", newline="", encoding=encoding) as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


_SAMPLE_ROW = {
    "平台": "京东全部",
    "月": "202602",
    "Lv0类目名称(逐月固定)": "手机通讯",
    "Lv1类目名称(逐月固定)": "手机",
    "Lv2类目名称(逐月固定)": "智能手机",
    "宝贝ID": "12345678",
    "宝贝名称": "测试商品",
    "宝贝图片": "http://img.example.com/1.jpg",
    "宝贝链接": "https://item.jd.com/12345678.html",
    "参考价格": "999.00",
    "宝贝品牌(bid)": "小米",
    "宝贝店铺名称": "小米官方旗舰店",
    "销量": "1000",
    "销售额": "999000.00",
}


def test_parse_csv_utf8_bom(tmp_path):
    """UTF-8 BOM 编码的 CSV 能正确解析，平台标准化为 jd"""
    tmp = tmp_path / "test.csv"
    _write_csv(tmp, [_SAMPLE_ROW], encoding="utf-8-sig")

    records, platform, month_range = parse_raw_excel(tmp)

    assert len(records) == 1
    assert records[0]["item_id"] == "12345678"
    assert records[0]["platform"] == "jd"
    assert records[0]["month"] == 202602
    assert records[0]["item_name"] == "测试商品"
    assert records[0]["ref_price"] == 999.0
    assert records[0]["sales_qty"] == 1000
    assert platform == "JD"
    assert month_range == "202602"


def test_parse_csv_gbk(tmp_path):
    """GBK 编码的 CSV 能 fallback 正确解析"""
    tmp = tmp_path / "test.csv"
    _write_csv(tmp, [_SAMPLE_ROW], encoding="gbk")

    records, platform, month_range = parse_raw_excel(tmp)

    assert len(records) == 1
    assert records[0]["item_id"] == "12345678"
    assert records[0]["platform"] == "jd"
    assert records[0]["item_name"] == "测试商品"


def test_parse_csv_missing_optional_columns(tmp_path):
    """CSV 缺少「价格/品牌/机型」列时，对应字段为 None，不抛出异常。
    此测试验证：缺失的标准字段会被自动补全为 None（fill missing standard fields with None）。
    """
    tmp = tmp_path / "test.csv"
    _write_csv(tmp, [_SAMPLE_ROW], encoding="utf-8-sig")

    records, _, _ = parse_raw_excel(tmp)

    assert records[0]["price"] is None
    assert records[0]["brand_std"] is None
    assert records[0]["model_std"] is None
