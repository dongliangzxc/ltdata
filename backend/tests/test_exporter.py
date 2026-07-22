"""
exporter.py 单元测试。
使用 conftest.py 的 db fixture（SQLite in-memory）。
"""
import pandas as pd
import pytest

from app.services.exporter import BASE_CN_NAMES, BASE_FIELD_NAMES, _base_row, export_match_filters, export_match_job
from app.models.schemas import (
    Category, CleanJobRecord, MetadataSpec, ModelRecord, RawDataRecord, MatchResult, FilteredItem,
)
from app.core.config import settings


@pytest.fixture(autouse=True)
def export_dir(tmp_path, monkeypatch):
    """将导出目录重定向到临时目录，避免写入真实路径。"""
    monkeypatch.setattr(settings, "EXPORT_DIR", str(tmp_path))


def test_base_export_headers_use_confirmed_brand_and_model_labels():
    assert "原品牌" in BASE_CN_NAMES
    assert "入库品牌" in BASE_CN_NAMES
    assert "型号" in BASE_CN_NAMES
    assert "品牌" not in BASE_CN_NAMES
    assert "品牌名称" not in BASE_CN_NAMES
    assert "型号名称" not in BASE_CN_NAMES
    assert "model_code" not in BASE_FIELD_NAMES
    assert "model_name" in BASE_FIELD_NAMES

    raw = RawDataRecord(brand_std="原始品牌", brand_raw="兜底品牌")
    model = ModelRecord(model_code="MODEL-CODE", model_name="入库型号", brand_name="入库品牌")
    row = _base_row(raw, model)

    assert row["brand_std"] == "原始品牌"
    assert row["brand_name"] == "入库品牌"
    assert row["model_name"] == "入库型号"
    assert "model_code" not in row


def _seed(db):
    """写入最小测试数据，返回 clean_job_id。"""
    cat = Category(code="headphone", name="耳机")
    db.add(cat)
    db.flush()

    spec_def = MetadataSpec(category_code="headphone", spec_name="anc", spec_type="text")
    db.add(spec_def)
    db.flush()

    model = ModelRecord(
        brand_code="sony", model_code="WH-1000XM5",
        category_code="headphone",
        brand_name="索尼", model_name="WH-1000XM5降噪耳机",
    )
    db.add(model)
    db.flush()

    rd = RawDataRecord(
        file_id=1, platform="jd", month=202501,
        item_id="100001", item_name="索尼耳机",
        brand_raw="Sony", brand_std="sony",
        sales_qty=100, sales_amount=50000.0, price=500.0,
    )
    db.add(rd)
    db.flush()

    mr = MatchResult(
        clean_job_id=1,
        raw_data_id=rd.id,
        model_id=model.id,
        match_status="matched",
        matched_by="auto",
        match_source="s1",
        is_disabled=0,
    )
    db.add(mr)
    db.commit()
    return 1


def test_brand_name_and_model_name_in_export(db):
    """已匹配 Sheet 应按确认文案导出入库品牌和型号名称值。"""
    clean_job_id = _seed(db)
    result = export_match_job(db, clean_job_id)
    assert result, "导出结果不应为空"

    xl = pd.read_excel(result[0]["path"], sheet_name="耳机-已处理")
    assert "入库品牌" in xl.columns, "缺少入库品牌列"
    assert "型号" in xl.columns, "缺少型号列"
    assert "品牌名称" not in xl.columns
    assert "型号名称" not in xl.columns
    assert xl["入库品牌"].iloc[0] == "索尼"
    assert xl["型号"].iloc[0] == "WH-1000XM5降噪耳机"


def test_text_only_export_sheet_uses_url_mapping_pending_label(db):
    """URL 映射待确认 Sheet 应与复核工作台 Tab 文案一致。"""
    clean_job_id = _seed(db)
    model = db.query(ModelRecord).first()
    rd = _make_extra_raw(db, "200000", "URL 映射待确认商品")
    db.add(MatchResult(
        clean_job_id=clean_job_id,
        raw_data_id=rd.id,
        model_id=model.id,
        match_status="text_only",
        matched_by="auto",
        match_source="s1",
        is_disabled=0,
    ))
    db.commit()

    result = export_match_job(db, clean_job_id)
    sheets = pd.ExcelFile(result[0]["path"]).sheet_names

    assert "耳机-URL映射待确认" in sheets
    assert "耳机-待审核" not in sheets


def test_disabled_items_excluded_from_export(db):
    """is_disabled=1 的条目不应出现在已匹配 Sheet。"""
    clean_job_id = _seed(db)

    # 将已有 MatchResult 标为禁用
    mr = db.query(MatchResult).filter_by(clean_job_id=clean_job_id).first()
    mr.is_disabled = 1
    db.commit()

    result = export_match_job(db, clean_job_id)
    # 没有任何可导出行时返回空列表
    assert result == [] or result[0]["rows"] == 0


def _make_extra_raw(db, item_id: str, item_name: str) -> RawDataRecord:
    rd = RawDataRecord(
        file_id=1, platform="jd", month=202501,
        item_id=item_id, item_name=item_name,
        brand_raw="Sony", brand_std="sony",
        sales_qty=1, sales_amount=1.0, price=1.0,
    )
    db.add(rd)
    db.flush()
    return rd


def test_disputed_excluded_filtered_included_in_export(db):
    """争议复核 / 已排除 / 干扰项过滤 三类数据应各自导出到独立 Sheet。"""
    clean_job_id = _seed(db)
    model = db.query(ModelRecord).first()

    # 争议复核（保留 model_id）
    disputed_rd = _make_extra_raw(db, "200001", "争议商品")
    db.add(MatchResult(
        clean_job_id=clean_job_id, raw_data_id=disputed_rd.id, model_id=model.id,
        match_status="disputed", matched_by="manual", is_disabled=0,
    ))

    # 已排除（无 model_id，模拟同标题批量排除）
    excluded_rd = _make_extra_raw(db, "200002", "排除商品")
    db.add(MatchResult(
        clean_job_id=clean_job_id, raw_data_id=excluded_rd.id, model_id=None,
        match_status="excluded", matched_by="manual", is_disabled=0,
    ))

    # 干扰项过滤：未恢复 + 已恢复 各一条，只应导出未恢复的
    filtered_rd = _make_extra_raw(db, "200003", "干扰商品")
    db.add(FilteredItem(
        raw_data_id=filtered_rd.id, clean_job_id=clean_job_id,
        matched_keyword="促销", intervention_rule_name="促销词过滤",
        matched_reason="标题包含促销词", is_recovered=0,
    ))
    recovered_rd = _make_extra_raw(db, "200004", "已恢复商品")
    db.add(FilteredItem(
        raw_data_id=recovered_rd.id, clean_job_id=clean_job_id,
        matched_keyword="促销", intervention_rule_name="促销词过滤",
        matched_reason="标题包含促销词", is_recovered=1,
    ))
    db.commit()

    result = export_match_job(db, clean_job_id)
    assert result, "导出结果不应为空"
    path = result[0]["path"]
    sheets = pd.ExcelFile(path).sheet_names
    assert "争议复核" in sheets
    assert "已排除" in sheets
    assert "干扰项过滤" in sheets

    disputed = pd.read_excel(path, sheet_name="争议复核")
    assert disputed["宝贝ID"].astype(str).tolist() == ["200001"]
    # 争议复核保留了 model_id，入库品牌/型号应有值
    assert disputed["入库品牌"].iloc[0] == "索尼"

    excluded = pd.read_excel(path, sheet_name="已排除")
    assert excluded["宝贝ID"].astype(str).tolist() == ["200002"]
    # 已排除 model_id 为空时，入库品牌/型号留空
    assert pd.isna(excluded["入库品牌"].iloc[0]) or excluded["入库品牌"].iloc[0] == ""

    filtered = pd.read_excel(path, sheet_name="干扰项过滤")
    assert filtered["宝贝ID"].astype(str).tolist() == ["200003"], "已恢复的干扰项不应被导出"
    assert filtered["命中关键词"].iloc[0] == "促销"
    assert filtered["命中规则"].iloc[0] == "促销词过滤"
    assert filtered["命中原因"].iloc[0] == "标题包含促销词"


def test_only_filtered_items_still_produces_file(db):
    """即便只有干扰项过滤数据，也应生成导出文件。"""
    # 构造仅有 filtered_items 的场景
    cat = Category(code="headphone", name="耳机")
    db.add(cat)
    db.flush()
    rd = RawDataRecord(
        file_id=1, platform="jd", month=202501,
        item_id="300001", item_name="仅干扰项",
        brand_raw="Sony", brand_std="sony",
        sales_qty=1, sales_amount=1.0, price=1.0,
    )
    db.add(rd)
    db.flush()
    db.add(FilteredItem(
        raw_data_id=rd.id, clean_job_id=1,
        matched_keyword="促销", is_recovered=0,
    ))
    db.commit()

    result = export_match_job(db, 1)
    assert result, "仅干扰项时也应生成文件"
    sheets = pd.ExcelFile(result[0]["path"]).sheet_names
    assert sheets == ["干扰项过滤"]


def test_export_match_filters_include_reviewing_clean_jobs(db):
    clean_job_id = _seed(db)
    db.add(CleanJobRecord(
        id=clean_job_id,
        category_code="headphone",
        platform="jd",
        source_scope={"months": [202501]},
        status="reviewing",
    ))
    db.commit()

    result = export_match_filters(
        db,
        months=[202501],
        category_code="headphone",
        platforms=["jd"],
    )

    assert result
    assert result[0]["rows"] == 1
