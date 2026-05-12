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


from app.services.excel_parser import parse_with_mapping


def test_parse_with_mapping_basic(tmp_path):
    """parse_with_mapping 正确将列名按 mapping 映射到标准字段，未映射列进 extra_data"""
    import csv
    tmp = tmp_path / "test.csv"
    with open(tmp, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["平台", "月", "宝贝ID", "宝贝名称", "销量", "销售额", "价格", "附加列"])
        writer.writeheader()
        writer.writerow({"平台": "京东全部", "月": "202602", "宝贝ID": "111",
                         "宝贝名称": "测试", "销量": "100", "销售额": "999.0",
                         "价格": "9.99", "附加列": "extra_val"})

    mapping = {
        "平台": "platform", "月": "month", "宝贝ID": "item_id",
        "宝贝名称": "item_name", "销量": "sales_qty",
        "销售额": "sales_amount", "价格": "price",
    }
    records, platform, month_range = parse_with_mapping(tmp, mapping, ignore_columns=[])

    assert len(records) == 1
    r = records[0]
    assert r["item_id"] == "111"
    assert r["platform"] == "jd"
    assert r["month"] == 202602
    assert r["sales_qty"] == 100
    assert r["extra_data"] == {"附加列": "extra_val"}
    assert platform == "JD"
    assert month_range == "202602"


def test_parse_with_mapping_ignore(tmp_path):
    """ignore_columns 中的列不出现在 extra_data 里"""
    import csv
    tmp = tmp_path / "test.csv"
    with open(tmp, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["平台", "月", "宝贝ID", "宝贝名称", "销量", "销售额", "价格", "内部备注"])
        writer.writeheader()
        writer.writerow({"平台": "京东全部", "月": "202602", "宝贝ID": "222",
                         "宝贝名称": "测试2", "销量": "50", "销售额": "500.0",
                         "价格": "10.0", "内部备注": "忽略我"})

    mapping = {
        "平台": "platform", "月": "month", "宝贝ID": "item_id",
        "宝贝名称": "item_name", "销量": "sales_qty",
        "销售额": "sales_amount", "价格": "price",
    }
    records, _, _ = parse_with_mapping(tmp, mapping, ignore_columns=["内部备注"])

    extra = records[0].get("extra_data") or {}
    assert "内部备注" not in extra


def test_parse_with_mapping_ext_explicit(tmp_path):
    """mapping 值为 __ext__ 的列也进 extra_data"""
    import csv
    tmp = tmp_path / "test.csv"
    with open(tmp, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["平台", "月", "宝贝ID", "宝贝名称", "销量", "销售额", "价格", "备注"])
        writer.writeheader()
        writer.writerow({"平台": "京东全部", "月": "202602", "宝贝ID": "333",
                         "宝贝名称": "测试3", "销量": "10", "销售额": "100.0",
                         "价格": "10.0", "备注": "保留进ext"})

    mapping = {
        "平台": "platform", "月": "month", "宝贝ID": "item_id",
        "宝贝名称": "item_name", "销量": "sales_qty",
        "销售额": "sales_amount", "价格": "price",
        "备注": "__ext__",
    }
    records, _, _ = parse_with_mapping(tmp, mapping, ignore_columns=[])

    assert records[0]["extra_data"]["备注"] == "保留进ext"
