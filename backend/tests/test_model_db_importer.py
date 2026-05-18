"""
model_db_importer.py 单元测试。
"""
import openpyxl
import pytest

from app.services.model_db_importer import parse_brand, import_model_db, ATTR_SPEC_TYPES
from app.models.schemas import ModelRecord, MetadataSpec, Category


# ── parse_brand ────────────────────────────────────────────

def test_parse_brand_with_slash():
    code, name = parse_brand("EDIFIER/漫步者")
    assert code == "EDIFIER"
    assert name == "漫步者"


def test_parse_brand_without_slash():
    code, name = parse_brand("JBL")
    assert code == "JBL"
    assert name == "JBL"


def test_parse_brand_multiple_slashes():
    """只按第一个斜杠拆分"""
    code, name = parse_brand("Sony/索尼/extra")
    assert code == "Sony"
    assert name == "索尼/extra"


def test_parse_brand_strips_whitespace():
    code, name = parse_brand("  Sony / 索尼  ")
    assert code == "Sony"
    assert name == "索尼"


# ── import 结果验证 ────────────────────────────────────────

@pytest.fixture
def tiny_excel(tmp_path):
    """创建最小测试用耳机数据库 Excel（1条有效数据）"""
    path = tmp_path / "test_db.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    headers = [
        "平台", "宝贝名称", "宝贝链接", "销量", "销售额", "ASP",
        "品牌", "型号", "佩戴类型", "In-ear Type", "开放式外观",
        "Power Type", "Bluetooth Version", "Sport", "Gaming", "HIFI",
        "ANC", "ENC", "Fast Charging", "IP Marking", "Health Monitoring",
        "Touch Screen Monitor", "骨传导", "AI", "AI+功能",
    ]
    ws.append(headers)
    ws.append([
        "JD", "索尼耳机", "https://item.jd.com/12345.html",
        100, 50000, 500,
        "Sony/索尼", "WH-1000XM5",
        "Headband", "Over Ear", "NULL", "Hybrid", 5.4,
        "NO", "NO", "NO", "YES", "YES", "NO", "NO", "NO", "NO", "NO", "NO", "",
    ])
    wb.save(path)
    return str(path)


def test_import_sets_brand_name(db, tiny_excel):
    """import 后 ModelRecord 应有正确的 brand_code 和 brand_name"""
    db.add(Category(code="headphone", name="耳机"))
    db.commit()

    import_model_db(tiny_excel, "headphone", db, dry_run=False)

    rec = db.query(ModelRecord).filter_by(model_code="WH-1000XM5").first()
    assert rec is not None
    assert rec.brand_code == "Sony"
    assert rec.brand_name == "索尼"


def test_import_seeds_metadata_specs(db, tiny_excel):
    """import 后 metadata_specs 应包含 17 条 headphone 定义"""
    db.add(Category(code="headphone", name="耳机"))
    db.commit()

    import_model_db(tiny_excel, "headphone", db, dry_run=False)

    specs = db.query(MetadataSpec).filter_by(category_code="headphone").all()
    spec_names = {s.spec_name for s in specs}
    assert "anc" in spec_names
    assert "bluetooth_version" in spec_names
    assert len(spec_names) == 17
    bt = next(s for s in specs if s.spec_name == "bluetooth_version")
    assert bt.spec_type == "number"


def test_import_metadata_specs_idempotent(db, tiny_excel):
    """重复导入不重复插入 metadata_specs"""
    db.add(Category(code="headphone", name="耳机"))
    db.commit()

    import_model_db(tiny_excel, "headphone", db, dry_run=False)
    import_model_db(tiny_excel, "headphone", db, dry_run=False)

    count = db.query(MetadataSpec).filter_by(category_code="headphone").count()
    assert count == 17


def test_attr_spec_types_covers_all_attr_col_map():
    """ATTR_SPEC_TYPES 必须覆盖 ATTR_COL_MAP 的所有 spec_name"""
    from app.services.model_db_importer import ATTR_COL_MAP
    for spec_name in ATTR_COL_MAP.values():
        assert spec_name in ATTR_SPEC_TYPES, f"ATTR_SPEC_TYPES 缺少 {spec_name}"


# ── 型号脏数据行仍捕获 URL ─────────────────────────────────

@pytest.fixture
def dirty_model_excel(tmp_path):
    """品牌有效、型号为空、URL有效的一行数据"""
    path = tmp_path / "dirty_model.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    headers = [
        "平台", "宝贝名称", "宝贝链接", "销量", "销售额", "ASP",
        "品牌", "型号", "佩戴类型", "In-ear Type", "开放式外观",
        "Power Type", "Bluetooth Version", "Sport", "Gaming", "HIFI",
        "ANC", "ENC", "Fast Charging", "IP Marking", "Health Monitoring",
        "Touch Screen Monitor", "骨传导", "AI", "AI+功能",
    ]
    ws.append(headers)
    ws.append([
        "JD", "某品牌耳机", "https://item.jd.com/99999.html",
        50, 10000, 200,
        "Sony/索尼", "",          # ← 型号为空
        "Headband", "Over Ear", "NULL", "Hybrid", 5.0,
        "NO", "NO", "NO", "YES", "NO", "NO", "NO", "NO", "NO", "NO", "NO", "",
    ])
    wb.save(path)
    return str(path)


def test_dirty_model_row_creates_url_mapping(db, dirty_model_excel):
    """型号为空但品牌+URL有效时，应建 ItemUrlMapping(model_id=None, brand_code='Sony')"""
    from app.models.schemas import ItemUrlMapping
    db.add(Category(code="headphone", name="耳机"))
    db.commit()

    stats = import_model_db(dirty_model_excel, "headphone", db, dry_run=False)

    url_mapping = db.query(ItemUrlMapping).filter_by(
        platform="jd", item_id="99999"
    ).first()
    assert url_mapping is not None
    assert url_mapping.model_id is None
    assert url_mapping.brand_code == "Sony"   # ← new assertion
    assert stats["urls_from_dirty_model"] == 1


def test_dirty_model_dry_run_counts_urls(dirty_model_excel):
    """dry-run 模式也要统计 urls_from_dirty_model"""
    stats = import_model_db(dirty_model_excel, "headphone", db=None, dry_run=True)
    assert stats["urls_from_dirty_model"] == 1
