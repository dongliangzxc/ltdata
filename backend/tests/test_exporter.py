"""
exporter.py 单元测试。
使用 conftest.py 的 db fixture（SQLite in-memory）。
"""
import pandas as pd
import pytest

from app.services.exporter import export_match_job
from app.models.schemas import (
    Category, MetadataSpec, ModelRecord, RawDataRecord, MatchResult,
)
from app.core.config import settings


@pytest.fixture(autouse=True)
def export_dir(tmp_path, monkeypatch):
    """将导出目录重定向到临时目录，避免写入真实路径。"""
    monkeypatch.setattr(settings, "EXPORT_DIR", str(tmp_path))


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
    """已匹配 Sheet 应包含品牌名称和型号名称列。"""
    clean_job_id = _seed(db)
    result = export_match_job(db, clean_job_id)
    assert result, "导出结果不应为空"

    xl = pd.read_excel(result[0]["path"], sheet_name="耳机")
    assert "品牌名称" in xl.columns, "缺少品牌名称列"
    assert "型号名称" in xl.columns, "缺少型号名称列"
    assert xl["品牌名称"].iloc[0] == "索尼"
    assert xl["型号名称"].iloc[0] == "WH-1000XM5降噪耳机"


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
