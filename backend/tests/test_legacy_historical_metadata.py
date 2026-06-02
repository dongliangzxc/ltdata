import io

import pandas as pd

from app.models.schemas import Category, MetadataSpec, ModelRecord, ModelSpec
import app.services.legacy_historical_metadata as legacy_metadata
from app.services.legacy_historical_metadata import import_legacy_historical_metadata


def _excel(rows: list[dict], sheet_name="Sheet1") -> bytes:
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        pd.DataFrame(rows).to_excel(writer, sheet_name=sheet_name, index=False)
    buffer.seek(0)
    return buffer.getvalue()


def test_import_legacy_metadata_dry_run_does_not_write(db, tmp_path):
    db.add(Category(code="router", name="路由器"))
    db.commit()
    path = tmp_path / "路由器数据库202501-202604.xlsx"
    path.write_bytes(_excel([{
        "年度": 2025,
        "月度": "2025.12",
        "平台": "天猫",
        "商品名称": "路由器 商品",
        "商品网址": "https://detail.tmall.com/item.htm?id=1006960105587",
        "品牌": "追觅",
        "产品系列": "D70",
        "WiFi协议": "WiFi7",
        "是否支持NAS": "是",
    }]))

    report = import_legacy_historical_metadata(db, [path], dry_run=True)

    assert report["files"][0]["category_code"] == "router"
    assert report["totals"]["metadata_specs"] == 2
    assert report["totals"]["models"] == 1
    assert report["totals"]["model_specs"] == 2
    assert db.query(MetadataSpec).count() == 0
    assert db.query(ModelRecord).count() == 0
    assert db.query(ModelSpec).count() == 0


def test_import_legacy_metadata_writes_specs_and_models(db, tmp_path):
    db.add(Category(code="router", name="路由器"))
    db.commit()
    path = tmp_path / "路由器数据库202501-202604.xlsx"
    path.write_bytes(_excel([{
        "年度": 2025,
        "月度": "2025.12",
        "平台": "天猫",
        "商品名称": "路由器 商品",
        "商品网址": "https://detail.tmall.com/item.htm?id=1006960105587",
        "品牌": "追觅",
        "产品系列": "D70",
        "WiFi协议": "WiFi7",
        "是否支持NAS": "是",
    }]))

    report = import_legacy_historical_metadata(db, [path], dry_run=False)

    assert report["totals"]["metadata_specs"] == 2
    wifi_spec = db.query(MetadataSpec).filter_by(category_code="router", spec_name="WiFi协议").one()
    nas_spec = db.query(MetadataSpec).filter_by(category_code="router", spec_name="是否支持NAS").one()
    assert wifi_spec.spec_type == "文本型"
    assert wifi_spec.spec_values == "WiFi7"
    assert nas_spec.spec_values == "是"
    model = db.query(ModelRecord).one()
    assert model.brand_code == "追觅"
    assert model.model_code == "D70"
    assert model.category_code == "router"
    specs = {(s.spec_name, s.spec_value) for s in db.query(ModelSpec).all()}
    assert ("WiFi协议", "WiFi7") in specs
    assert ("是否支持NAS", "是") in specs


def test_import_legacy_metadata_reports_conflicts(db, tmp_path):
    db.add(Category(code="door_lock", name="门锁"))
    db.commit()
    path = tmp_path / "2023-2026.04门锁-传统+新兴.xlsx"
    path.write_bytes(_excel([
        {"年度": 2026, "月度": 4, "平台": "京东", "宝贝名称": "商品1", "宝贝链接": "https://item.jd.com/1.html", "品牌": "品牌A", "机型": "Lock A", "把手形态": "推拉式"},
        {"年度": 2026, "月度": 4, "平台": "京东", "宝贝名称": "商品2", "宝贝链接": "https://item.jd.com/2.html", "品牌": "品牌A", "机型": "Lock A", "把手形态": "执手式"},
        {"年度": 2026, "月度": 4, "平台": "京东", "宝贝名称": "商品3", "宝贝链接": "https://item.jd.com/3.html", "品牌": "品牌A", "机型": "Lock A", "把手形态": "推拉式"},
    ]))

    report = import_legacy_historical_metadata(db, [path], dry_run=False)

    conflict = report["files"][0]["conflicts"][0]
    assert conflict["type"] == "spec_value_conflict"
    assert conflict["model_code"] == "Lock A"
    assert conflict["spec_name"] == "把手形态"
    assert conflict["selected_value"] == "推拉式"
    assert conflict["resolution"] == "most_frequent_latest_tie"
    model = db.query(ModelRecord).one()
    spec = db.query(ModelSpec).filter_by(model_id=model.id, spec_name="把手形态").one()
    assert spec.spec_value == "推拉式"


def test_import_legacy_metadata_excludes_historical_model_aliases_from_specs(db, tmp_path):
    db.add(Category(code="router", name="路由器"))
    db.commit()
    path = tmp_path / "路由器数据库202501-202604.xlsx"
    path.write_bytes(_excel([{
        "年度": 2025,
        "月度": "2025.12",
        "平台": "天猫",
        "商品名称": "路由器 商品",
        "商品网址": "https://detail.tmall.com/item.htm?id=1006960105587",
        "品牌": "品牌A",
        "品牌产品系列": "Router A",
        "WiFi协议": "WiFi7",
    }]))

    import_legacy_historical_metadata(db, [path], dry_run=False)

    spec_names = {spec.spec_name for spec in db.query(MetadataSpec).all()}
    assert "品牌产品系列" not in spec_names
    assert "WiFi协议" in spec_names


def test_import_legacy_metadata_uses_detected_mapping_for_model_aliases(db, tmp_path):
    db.add(Category(code="router", name="路由器"))
    db.commit()
    path = tmp_path / "路由器数据库202501-202604.xlsx"
    path.write_bytes(_excel([{
        "年度": 2025,
        "月度": "2025.12",
        "平台": "天猫",
        "商品名称": "路由器 商品",
        "商品网址": "https://detail.tmall.com/item.htm?id=1006960105587",
        "品牌": "品牌A",
        "系列/机型": "Router A",
        "WiFi协议": "WiFi7",
    }]))

    import_legacy_historical_metadata(db, [path], dry_run=False)

    model = db.query(ModelRecord).one()
    assert model.model_code == "Router A"
    assert db.query(ModelSpec).filter_by(model_id=model.id, spec_name="WiFi协议", spec_value="WiFi7").one()


def test_import_legacy_metadata_preserves_unrelated_existing_specs(db, tmp_path):
    db.add(Category(code="router", name="路由器"))
    model = ModelRecord(brand_code="品牌A", model_code="Router A", category_code="router")
    db.add(model)
    db.flush()
    db.add(ModelSpec(model_id=model.id, spec_name="保留字段", spec_value="保留值"))
    db.commit()
    path = tmp_path / "路由器数据库202501-202604.xlsx"
    path.write_bytes(_excel([{
        "年度": 2025,
        "月度": "2025.12",
        "平台": "天猫",
        "商品名称": "路由器 商品",
        "商品网址": "https://detail.tmall.com/item.htm?id=1006960105587",
        "品牌": "品牌A",
        "产品系列": "Router A",
        "WiFi协议": "WiFi7",
    }]))

    import_legacy_historical_metadata(db, [path], dry_run=False)

    specs = {(spec.spec_name, spec.spec_value) for spec in db.query(ModelSpec).filter_by(model_id=model.id).all()}
    assert ("保留字段", "保留值") in specs
    assert ("WiFi协议", "WiFi7") in specs


def test_import_legacy_metadata_skips_existing_model_category_conflict(db, tmp_path):
    db.add_all([Category(code="cat_a", name="品类A"), Category(code="cat_b", name="品类B")])
    model = ModelRecord(brand_code="品牌A", model_code="Model A", category_code="cat_a")
    db.add(model)
    db.commit()
    path = tmp_path / "品类B数据库202501-202604.xlsx"
    path.write_bytes(_excel([{
        "年度": 2025,
        "月度": "2025.12",
        "平台": "天猫",
        "商品名称": "品类B 商品",
        "商品网址": "https://detail.tmall.com/item.htm?id=1006960105587",
        "品牌": "品牌A",
        "产品系列": "Model A",
        "WiFi协议": "WiFi7",
    }]))

    report = import_legacy_historical_metadata(db, [path], dry_run=False)

    db.refresh(model)
    assert model.category_code == "cat_a"
    assert db.query(ModelSpec).filter_by(model_id=model.id, spec_name="WiFi协议").count() == 0
    assert [conflict["type"] for conflict in report["files"][0]["conflicts"]] == ["model_category_conflict"]
    assert report["files"][0]["models"] == 0
    assert report["files"][0]["model_specs"] == 0
    assert report["totals"]["models"] == 0
    assert report["totals"]["model_specs"] == 0


def test_import_legacy_metadata_dry_run_reports_existing_model_category_conflict(db, tmp_path):
    db.add_all([Category(code="cat_a", name="品类A"), Category(code="cat_b", name="品类B")])
    model = ModelRecord(brand_code="品牌A", model_code="Model A", category_code="cat_a")
    db.add(model)
    db.commit()
    path = tmp_path / "品类B数据库202501-202604.xlsx"
    path.write_bytes(_excel([{
        "年度": 2025,
        "月度": "2025.12",
        "平台": "天猫",
        "商品名称": "品类B 商品",
        "商品网址": "https://detail.tmall.com/item.htm?id=1006960105587",
        "品牌": "品牌A",
        "产品系列": "Model A",
        "WiFi协议": "WiFi7",
    }]))

    report = import_legacy_historical_metadata(db, [path], dry_run=True)

    db.refresh(model)
    assert model.category_code == "cat_a"
    assert db.query(ModelSpec).filter_by(model_id=model.id, spec_name="WiFi协议").count() == 0
    assert report["files"][0]["conflicts"][0]["type"] == "model_category_conflict"
    assert report["files"][0]["models"] == 0
    assert report["files"][0]["model_specs"] == 0
    assert report["totals"]["models"] == 0
    assert report["totals"]["model_specs"] == 0


def test_import_legacy_metadata_uses_brand_code_as_name_when_brand_name_unknown(db, tmp_path):
    db.add(Category(code="router", name="路由器"))
    db.commit()
    path = tmp_path / "路由器数据库202501-202604.xlsx"
    path.write_bytes(_excel([{
        "年度": 2025,
        "月度": "2025.12",
        "平台": "天猫",
        "商品名称": "路由器 商品",
        "商品网址": "https://detail.tmall.com/item.htm?id=1006960105587",
        "品牌码": "BRANDA",
        "品牌": "未知",
        "产品系列": "Router A",
        "WiFi协议": "WiFi7",
    }]))

    import_legacy_historical_metadata(db, [path], dry_run=False)

    model = db.query(ModelRecord).one()
    assert model.brand_code == "BRANDA"
    assert model.brand_name == "BRANDA"


def test_import_legacy_metadata_tie_conflict_uses_latest_value(db, tmp_path):
    db.add(Category(code="router", name="路由器"))
    db.commit()
    path = tmp_path / "路由器数据库202501-202604.xlsx"
    path.write_bytes(_excel([
        {"年度": 2025, "月度": "2025.12", "平台": "天猫", "商品名称": "商品1", "商品网址": "https://detail.tmall.com/item.htm?id=1", "品牌": "品牌A", "产品系列": "Router A", "WiFi协议": "A"},
        {"年度": 2025, "月度": "2025.12", "平台": "天猫", "商品名称": "商品2", "商品网址": "https://detail.tmall.com/item.htm?id=2", "品牌": "品牌A", "产品系列": "Router A", "WiFi协议": "B"},
    ]))

    report = import_legacy_historical_metadata(db, [path], dry_run=False)

    conflict = report["files"][0]["conflicts"][0]
    assert conflict["type"] == "spec_value_conflict"
    assert conflict["spec_name"] == "WiFi协议"
    assert conflict["selected_value"] == "B"
    assert conflict["resolution"] == "most_frequent_latest_tie"
    model = db.query(ModelRecord).one()
    spec = db.query(ModelSpec).filter_by(model_id=model.id, spec_name="WiFi协议").one()
    assert spec.spec_value == "B"


def test_import_legacy_metadata_skips_oversized_metadata_spec_values_but_writes_model_specs(db, tmp_path):
    db.add(Category(code="door_lock", name="门锁"))
    db.commit()
    path = tmp_path / "2023-2026.04门锁-传统+新兴.xlsx"
    rows = []
    for index in range(legacy_metadata.SPEC_VALUES_MAX_OPTIONS + 1):
        rows.append({
            "年度": 2025,
            "月度": "2025.12",
            "平台": "京东",
            "宝贝名称": f"门锁商品{index}",
            "宝贝链接": f"https://item.jd.com/{index}.html",
            "品牌": "品牌A",
            "机型": f"Lock {index}",
            "品牌机型": f"品牌A Lock {index}",
        })
    path.write_bytes(_excel(rows))

    import_legacy_historical_metadata(db, [path], dry_run=False)

    metadata_spec = db.query(MetadataSpec).filter_by(category_code="door_lock", spec_name="品牌机型").one()
    assert metadata_spec.spec_values is None
    assert db.query(ModelSpec).filter_by(spec_name="品牌机型").count() == legacy_metadata.SPEC_VALUES_MAX_OPTIONS + 1



def test_import_legacy_metadata_rolls_back_failed_file_and_keeps_session_usable(db, tmp_path, monkeypatch):
    db.add(Category(code="router", name="路由器"))
    db.commit()
    first_path = tmp_path / "路由器第一批数据库202501-202604.xlsx"
    first_path.write_bytes(_excel([{
        "年度": 2025,
        "月度": "2025.12",
        "平台": "天猫",
        "商品名称": "路由器 商品1",
        "商品网址": "https://detail.tmall.com/item.htm?id=1",
        "品牌": "品牌A",
        "产品系列": "Router A",
        "WiFi协议": "WiFi7",
    }]))
    second_path = tmp_path / "路由器第二批数据库202501-202604.xlsx"
    second_path.write_bytes(_excel([{
        "年度": 2025,
        "月度": "2025.12",
        "平台": "天猫",
        "商品名称": "路由器 商品2",
        "商品网址": "https://detail.tmall.com/item.htm?id=2",
        "品牌": "品牌B",
        "产品系列": "Router B",
        "故障字段": "触发异常",
    }]))
    original_upsert = legacy_metadata._upsert_metadata_spec

    def fail_for_specific_spec(session, category_code, spec_name, value_counts=None):
        if spec_name == "故障字段":
            raise RuntimeError("boom during metadata write")
        return original_upsert(session, category_code, spec_name, value_counts)

    monkeypatch.setattr(legacy_metadata, "_upsert_metadata_spec", fail_for_specific_spec)

    report = import_legacy_historical_metadata(db, [first_path, second_path], dry_run=False)

    assert "boom during metadata write" in report["files"][1]["error"]
    assert db.query(ModelRecord).count() == 1
    model = db.query(ModelRecord).one()
    assert model.model_code == "Router A"
    assert db.query(ModelSpec).filter_by(model_id=model.id, spec_name="WiFi协议", spec_value="WiFi7").one()
    assert db.query(MetadataSpec).filter_by(spec_name="故障字段").count() == 0
    assert report["totals"]["metadata_specs"] == 1
    assert report["totals"]["models"] == 1
    assert report["totals"]["model_specs"] == 1
