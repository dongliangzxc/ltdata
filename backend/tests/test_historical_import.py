import io
from datetime import datetime

import pandas as pd
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event

from app.api.historical_api import router as historical_router
from app.models.database import get_db
from app.models.schemas import Category, HistoricalMapping, ModelRecord


def _client(db):
    def override_db():
        yield db

    test_app = FastAPI()
    test_app.include_router(historical_router)
    test_app.dependency_overrides[get_db] = override_db
    return TestClient(test_app)


def _history_excel(rows: list[dict]) -> bytes:
    buffer = io.BytesIO()
    pd.DataFrame(rows).to_excel(buffer, index=False)
    buffer.seek(0)
    return buffer.getvalue()


def _history_excel_with_sheets(sheets: dict[str, list[dict]]) -> bytes:
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer) as writer:
        for sheet_name, rows in sheets.items():
            pd.DataFrame(rows).to_excel(writer, sheet_name=sheet_name, index=False)
    buffer.seek(0)
    return buffer.getvalue()


def _seed_model(db, *, model_code="QH-001", model_name="Mini", brand_code="DJI", category_code="sports_camera"):
    model = ModelRecord(
        brand_code=brand_code,
        model_code=model_code,
        model_name=model_name,
        category_code=category_code,
    )
    db.add(model)
    db.commit()
    return model


def test_import_chinese_history_excel_persists_confirmed_detail_fields(db):
    model = _seed_model(db, model_code="DJI-MINI-4", model_name="Mini 4 Pro", brand_code="DJI")
    client = _client(db)
    content = _history_excel([
        {
            "年": 2026,
            "月": 5,
            "周": "W21",
            "报告类型": "月报",
            "渠道": "电商",
            "商场": "TMALL",
            "品类": "运动相机",
            "品牌": "大疆",
            "型号": "Mini 4 Pro",
            "品类码": "sports_camera",
            "品牌码": "DJI",
            "型号码": "DJI-MINI-4",
            "标题": "DJI Mini 4 Pro 航拍无人机",
            "销额": 12345.67,
            "销量": 12,
            "单价": 1028.81,
            "网址": "https://detail.tmall.com/item.htm?id=909868962326",
        }
    ])

    resp = client.post(
        "/api/historical/import",
        files={"file": ("history.xlsx", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    assert resp.status_code == 200
    assert resp.json()["success"] == 1
    assert resp.json()["created"] == 1
    assert resp.json()["updated"] == 0
    row = db.query(HistoricalMapping).one()
    assert row.id is not None
    assert row.import_batch is not None
    assert row.created_at is not None
    assert row.updated_at is not None
    assert row.model == model
    assert row.platform == "tmall"
    assert row.item_id == "909868962326"
    assert row.item_url == "https://detail.tmall.com/item.htm?id=909868962326"
    assert row.item_name == "DJI Mini 4 Pro 航拍无人机"
    assert row.item_name_norm == "DJI MINI 4 PRO 航拍无人机"
    assert row.year == 2026
    assert row.month_num == 5
    assert row.week == "W21"
    assert row.month == "2026-05"
    assert row.report_type == "月报"
    assert row.channel == "电商"
    assert row.category_name_raw == "运动相机"
    assert row.category_code_raw == "sports_camera"
    assert row.brand_raw == "大疆"
    assert row.brand_code_raw == "DJI"
    assert row.model_text == "Mini 4 Pro"
    assert row.model_code_raw == "DJI-MINI-4"
    assert row.model_id == model.id
    assert row.model_code == "DJI-MINI-4"
    assert row.category_code == "sports_camera"
    assert float(row.sales_amount) == 12345.67
    assert row.sales_qty == 12
    assert float(row.price) == 1028.81
    assert row.match_key_type == "item_id"
    assert row.raw_payload["标题"] == "DJI Mini 4 Pro 航拍无人机"


def test_import_accepts_year_month_values_in_month_column(db):
    client = _client(db)
    content = _history_excel([
        {"年": 2026, "月": "2026.03", "商场": "TMALL", "标题": "小数月份", "网址": "https://detail.tmall.com/item.htm?id=301"},
        {"年": 2026, "月": "202603", "商场": "JD", "标题": "年月数字", "网址": "https://item.jd.com/302.html"},
    ])

    resp = client.post(
        "/api/historical/import",
        files={"file": ("history.xlsx", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    assert resp.status_code == 200
    assert resp.json()["success"] == 2
    assert resp.json()["errors"] == []
    rows = db.query(HistoricalMapping).order_by(HistoricalMapping.item_id).all()
    assert [row.month_num for row in rows] == [3, 3]
    assert [row.month for row in rows] == ["2026-03", "2026-03"]


def test_import_preloads_model_resolution_without_per_row_model_queries(db):
    _seed_model(db, model_code="DJI-MINI-4", model_name="Mini 4 Pro", brand_code="DJI")
    _seed_model(db, model_code="QH-215", model_name="QHTF 21.5", brand_code="ROCK")
    client = _client(db)
    content = _history_excel([
        {"年": 2026, "月": 5, "商场": "TMALL", "标题": "型号码匹配", "型号": "Mini 4 Pro", "型号码": "DJI-MINI-4", "网址": "https://detail.tmall.com/item.htm?id=101"},
        {"年": 2026, "月": 5, "商场": "JD", "标题": "型号文本按编码匹配", "型号": "QH-215", "网址": "https://item.jd.com/102.html"},
        {"年": 2026, "月": 5, "商场": "TMALL", "标题": "型号文本按名称匹配", "型号": "Mini 4 Pro", "网址": "https://detail.tmall.com/item.htm?id=103"},
    ])
    model_selects = []

    def track_model_selects(conn, cursor, statement, parameters, context, executemany):
        if "FROM models" in statement and statement.lstrip().upper().startswith("SELECT"):
            model_selects.append(statement)

    event.listen(db.bind, "before_cursor_execute", track_model_selects)
    try:
        resp = client.post(
            "/api/historical/import",
            files={"file": ("history.xlsx", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
    finally:
        event.remove(db.bind, "before_cursor_execute", track_model_selects)

    assert resp.status_code == 200
    assert resp.json()["success"] == 3
    assert resp.json()["errors"] == []
    assert len(model_selects) == 2


def test_import_merges_duplicate_keys_in_same_file_with_sales_sum_and_note(db):
    client = _client(db)
    content = _history_excel([
        {
            "年": 2026,
            "月": 5,
            "商场": "JD",
            "标题": "重复商品",
            "网址": "https://item.jd.com/10001.html",
            "销量": 2,
            "销额": 20,
        },
        {
            "年": 2026,
            "月": 5,
            "商场": "JD",
            "标题": "重复商品",
            "网址": "https://item.jd.com/10001.html",
            "销量": 3,
            "销额": 30,
        },
    ])

    resp = client.post(
        "/api/historical/import",
        files={"file": ("history.xlsx", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] == 2
    assert data["created"] == 1
    assert data["updated"] == 0
    row = db.query(HistoricalMapping).one()
    assert row.sales_qty == 5
    assert float(row.sales_amount) == 50
    assert row.raw_payload["_merge_note"] == "同一导入批次内发现 2 条相同历史键记录，销量和销额已累加"
    assert row.raw_payload["_merged_rows"] == [2, 3]



def test_import_preloads_existing_history_without_per_row_history_queries(db):
    client = _client(db)
    content = _history_excel([
        {"年": 2026, "月": 5, "商场": "TMALL", "标题": "商品1", "网址": "https://detail.tmall.com/item.htm?id=201"},
        {"年": 2026, "月": 5, "商场": "TMALL", "标题": "商品2", "网址": "https://detail.tmall.com/item.htm?id=202"},
        {"年": 2026, "月": 5, "商场": "JD", "标题": "商品3", "网址": "https://item.jd.com/203.html"},
    ])
    history_selects = []

    def track_history_selects(conn, cursor, statement, parameters, context, executemany):
        if "FROM historical_mappings" in statement and statement.lstrip().upper().startswith("SELECT"):
            history_selects.append(statement)

    event.listen(db.bind, "before_cursor_execute", track_history_selects)
    try:
        resp = client.post(
            "/api/historical/import",
            files={"file": ("history.xlsx", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
    finally:
        event.remove(db.bind, "before_cursor_execute", track_history_selects)

    assert resp.status_code == 200
    assert resp.json()["success"] == 3
    assert resp.json()["errors"] == []
    assert len(history_selects) <= 1


def test_headers_detects_detail_sheet_and_maps_door_lock_aliases(db, tmp_path, monkeypatch):
    monkeypatch.setattr("app.api.historical_api.settings.UPLOAD_DIR", str(tmp_path))
    db.add(Category(code="door_lock", name="智能门锁"))
    db.commit()
    client = _client(db)
    content = _history_excel_with_sheets({
        "Sheet2": [{"Unnamed: 0": "汇总", "Unnamed: 1": 1}],
        "Sheet1": [{
            "年度": 2026,
            "月度": 4,
            "平台": "京东",
            "渠道类型": "线上",
            "宝贝名称": "门锁 商品",
            "宝贝链接": "https://item.jd.com/300001.html",
            "品牌": "品牌A",
            "机型": "Lock A",
            "成交价": 1999,
            "原始量": 8,
            "原始额": 15992,
        }],
    })

    resp = client.post(
        "/api/historical/headers",
        files={"file": ("2023-2026.04门锁-传统+新兴.xlsx", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["sheet_name"] == "Sheet1"
    assert data["category_code"] == "door_lock"
    assert data["mapping"]["year"] == "年度"
    assert data["mapping"]["month_num"] == "月度"
    assert data["mapping"]["platform"] == "平台"
    assert data["mapping"]["item_name"] == "宝贝名称"
    assert data["mapping"]["item_url"] == "宝贝链接"
    assert data["mapping"]["model_text"] == "机型"
    assert data["preview"][0]["商场"] == "京东"
    assert data["preview"][0]["标题"] == "门锁 商品"
    assert data["issues"] == []


def test_confirm_imports_old_router_alias_format_after_preview(db, tmp_path, monkeypatch):
    monkeypatch.setattr("app.api.historical_api.settings.UPLOAD_DIR", str(tmp_path))
    db.add(Category(code="router", name="路由器"))
    db.commit()
    _seed_model(db, model_code="ROUTER-B", model_name="Router B", brand_code="BRAND-B", category_code="router")
    client = _client(db)
    content = _history_excel([{
        "年度": 2025,
        "月度": 1,
        "平台": "京东",
        "渠道类型": "线上",
        "商品名称": "路由器 商品",
        "商品网址": "https://item.jd.com/400001.html",
        "品牌": "品牌B",
        "产品系列": "Router B",
        "单价": 299,
        "销量": 3,
        "销额": 897,
    }])
    headers_resp = client.post(
        "/api/historical/headers",
        files={"file": ("路由器数据库202501-202604.xlsx", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert headers_resp.status_code == 200
    preview = headers_resp.json()

    resp = client.post("/api/historical/confirm", json={
        "temp_file_id": preview["temp_file_id"],
        "sheet_name": preview["sheet_name"],
        "mapping": preview["mapping"],
        "category_code": preview["category_code"],
    })

    assert resp.status_code == 200
    assert resp.json()["success"] == 1
    row = db.query(HistoricalMapping).one()
    assert row.platform == "jd"
    assert row.item_id == "400001"
    assert row.category_code == "router"
    assert row.item_name == "路由器 商品"
    assert row.model_text == "Router B"
    assert row.sales_qty == 3


def test_headers_maps_notebook_time_dimension_and_requires_category_when_unresolved(db, tmp_path, monkeypatch):
    monkeypatch.setattr("app.api.historical_api.settings.UPLOAD_DIR", str(tmp_path))
    client = _client(db)
    content = _history_excel([{
        "URL": "https://item.jd.com/500001.html",
        "品牌+系列": "Notebook C",
        "时间维度": 26.01,
        "平台": "京东",
        "商品名称": "笔记本 商品",
        "网址": "https://item.jd.com/500001.html",
        "销额": 6000,
        "销量": 2,
        "单价": 3000,
    }])

    resp = client.post(
        "/api/historical/headers",
        files={"file": ("未知品类.xlsx", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["mapping"]["month_num"] == "时间维度"
    assert data["mapping"]["model_text"] == "品牌+系列"
    assert data["preview"][0]["月"] == "1"
    assert "未识别品类" in "\n".join(data["issues"])


def test_list_history_returns_beijing_time_strings(db):
    row = HistoricalMapping(
        import_batch="batch1",
        platform="tmall",
        item_id="1001",
        item_name="商品1",
        item_name_norm="商品1",
        year=2026,
        month_num=6,
        month="2026-06",
        model_text=None,
        model_id=None,
        model_code=None,
        category_code="monitor",
        match_key_type="item_id",
        raw_payload={"标题": "商品1"},
        created_at=datetime(2026, 6, 1, 1, 2, 3),
        updated_at=datetime(2026, 6, 1, 1, 2, 3),
    )
    db.add(row)
    db.commit()
    client = _client(db)

    batch_resp = client.get("/api/historical/batches")
    mapping_resp = client.get("/api/historical/mappings")

    assert batch_resp.status_code == 200
    assert mapping_resp.status_code == 200
    assert batch_resp.json()[0]["updated_at"] == "2026-06-01 09:02:03"
    assert mapping_resp.json()["items"][0]["updated_at"] == "2026-06-01 09:02:03"


def test_import_requires_platform_title_year_and_month(db):
    client = _client(db)
    content = _history_excel([{"商场": " ", "渠道": " ", "标题": " ", "型号": " ", "年": " ", "月": " "}])

    resp = client.post(
        "/api/historical/import",
        files={"file": ("bad.xlsx", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] == 0
    reasons = "\n".join(e["reason"] for e in data["errors"])
    assert "商场/渠道不能为空" in reasons
    assert "标题不能为空" in reasons
    assert "型号不能为空" not in reasons
    assert "年不能为空" in reasons
    assert "月不能为空" in reasons


def test_import_reads_rawdata_sheet_uses_channel_as_platform_and_allows_blank_model(db):
    db.add(Category(code="monitor", name="显示器"))
    db.commit()
    client = _client(db)
    content = _history_excel_with_sheets({
        "元数据": [{"品类码": "monitor", "规格名称": "产品细分"}],
        "rawdata": [{
            "年": 2023,
            "月": 1,
            "周": "W01",
            "报告类型": "ONLINE_M",
            "渠道": "TMALL",
            "商场": "",
            "品类": "显示器",
            "品牌": "清华同方",
            "型号": "",
            "品类码": "",
            "品牌码": "THTF",
            "型号码": "",
            "标题": "清华同方 21.5英寸液晶显示器",
            "销额": 3552,
            "销量": 4,
            "单价": 888,
            "网址": "https://detail.tmall.com/item.htm?id=15498989111",
        }],
    })

    resp = client.post(
        "/api/historical/import",
        files={"file": ("monitor.xlsx", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] == 1
    assert data["created"] == 1
    assert data["errors"] == []
    row = db.query(HistoricalMapping).one()
    assert row.platform == "tmall"
    assert row.item_id == "15498989111"
    assert row.model_text is None
    assert row.model_id is None
    assert row.model_code is None
    assert row.category_code == "monitor"
    assert row.brand_raw == "清华同方"
    assert row.brand_code_raw == "THTF"
    assert row.match_key_type == "item_id"


def test_import_uses_model_code_when_model_text_matches_code(db):
    model = _seed_model(db, model_code="QH-215", model_name="QHTF 21.5", brand_code="ROCK")
    client = _client(db)
    content = _history_excel([{
        "年": 2026, "月": 5, "商场": "JD", "标题": "洛图测试商品", "型号": "QH-215"
    }])

    resp = client.post(
        "/api/historical/import",
        files={"file": ("history.xlsx", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    assert resp.status_code == 200
    assert resp.json()["success"] == 1
    assert db.query(HistoricalMapping).one().model_id == model.id


def test_import_uses_unique_model_name_when_code_does_not_match(db):
    model = _seed_model(db, model_code="QH-215", model_name="QHTF 21.5", brand_code="ROCK")
    client = _client(db)
    content = _history_excel([{
        "年": 2026, "月": 5, "商场": "JD", "标题": "洛图测试商品", "型号": "QHTF 21.5"
    }])

    resp = client.post(
        "/api/historical/import",
        files={"file": ("history.xlsx", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    assert resp.status_code == 200
    assert resp.json()["success"] == 1
    assert db.query(HistoricalMapping).one().model_id == model.id


def test_import_uses_brand_code_to_disambiguate_duplicate_model_names(db):
    _seed_model(db, model_code="MINI-DJI", model_name="Mini", brand_code="DJI")
    target = _seed_model(db, model_code="MINI-INSTA", model_name="Mini", brand_code="INSTA")
    client = _client(db)
    content = _history_excel([{
        "年": 2026, "月": 5, "商场": "JD", "标题": "洛图测试商品", "型号": "Mini", "品牌码": "INSTA"
    }])

    resp = client.post(
        "/api/historical/import",
        files={"file": ("history.xlsx", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    assert resp.status_code == 200
    assert resp.json()["success"] == 1
    assert db.query(HistoricalMapping).one().model_id == target.id


def test_import_rejects_ambiguous_model_name_without_brand_code(db):
    _seed_model(db, model_code="MINI-DJI", model_name="Mini", brand_code="DJI")
    _seed_model(db, model_code="MINI-INSTA", model_name="Mini", brand_code="INSTA")
    client = _client(db)
    content = _history_excel([{
        "年": 2026, "月": 5, "商场": "JD", "标题": "洛图测试商品", "型号": "Mini"
    }])

    resp = client.post(
        "/api/historical/import",
        files={"file": ("history.xlsx", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] == 0
    assert "匹配到多个型号" in data["errors"][0]["reason"]


def test_import_auto_creates_unknown_model(db):
    client = _client(db)
    content = _history_excel([{
        "年": 2026, "月": 5, "商场": "JD", "标题": "洛图测试商品", "型号": "DOES-NOT-EXIST", "品牌": "品牌A"
    }])

    resp = client.post(
        "/api/historical/import",
        files={"file": ("history.xlsx", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] == 1
    model = db.query(ModelRecord).one()
    assert model.brand_code == "品牌A"
    assert model.model_code == "DOES-NOT-EXIST"
    assert db.query(HistoricalMapping).one().model_id == model.id


def test_import_uses_brand_name_as_brand_code_for_ambiguous_model_code(db):
    target = _seed_model(db, model_code="SAME-CODE", model_name="Model A", brand_code="BRAND-A")
    _seed_model(db, model_code="SAME-CODE", model_name="Model B", brand_code="BRAND-B")
    client = _client(db)
    content = _history_excel([{
        "年": 2026,
        "月": 5,
        "商场": "JD",
        "标题": "无品牌码商品",
        "品牌": "BRAND-A",
        "型号码": "SAME-CODE",
        "网址": "https://item.jd.com/920001.html",
    }])

    resp = client.post(
        "/api/historical/import",
        files={"file": ("history.xlsx", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] == 1
    row = db.query(HistoricalMapping).one()
    assert row.model_id == target.id
    assert row.brand_code_raw == "BRAND-A"


def test_import_auto_creates_same_model_code_for_different_brands(db):
    client = _client(db)
    content = _history_excel([
        {
            "年": 2026,
            "月": 5,
            "商场": "JD",
            "标题": "品牌A 商品",
            "品牌": "品牌A",
            "品牌码": "BRAND-A",
            "型号": "共享型号",
            "型号码": "SAME-CODE",
            "网址": "https://item.jd.com/900001.html",
        },
        {
            "年": 2026,
            "月": 5,
            "商场": "JD",
            "标题": "品牌B 商品",
            "品牌": "品牌B",
            "品牌码": "BRAND-B",
            "型号": "共享型号",
            "型号码": "SAME-CODE",
            "网址": "https://item.jd.com/900002.html",
        },
    ])

    resp = client.post(
        "/api/historical/import",
        files={"file": ("history.xlsx", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    assert resp.status_code == 200
    assert resp.json()["success"] == 2
    models = {model.brand_code: model for model in db.query(ModelRecord).all()}
    assert set(models) == {"BRAND-A", "BRAND-B"}
    assert {model.model_code for model in models.values()} == {"SAME-CODE"}
    rows = {row.item_id: row for row in db.query(HistoricalMapping).all()}
    assert rows["900001"].model_id == models["BRAND-A"].id
    assert rows["900002"].model_id == models["BRAND-B"].id


def test_import_rejects_unbranded_model_code_when_batch_contains_multiple_brands(db):
    client = _client(db)
    content = _history_excel([
        {
            "年": 2026,
            "月": 5,
            "商场": "JD",
            "标题": "品牌A 商品",
            "品牌码": "BRAND-A",
            "型号": "共享型号",
            "型号码": "SAME-CODE",
            "网址": "https://item.jd.com/930001.html",
        },
        {
            "年": 2026,
            "月": 5,
            "商场": "JD",
            "标题": "无品牌商品",
            "型号码": "SAME-CODE",
            "网址": "https://item.jd.com/930002.html",
        },
        {
            "年": 2026,
            "月": 5,
            "商场": "JD",
            "标题": "品牌B 商品",
            "品牌码": "BRAND-B",
            "型号": "共享型号",
            "型号码": "SAME-CODE",
            "网址": "https://item.jd.com/930003.html",
        },
    ])

    resp = client.post(
        "/api/historical/import",
        files={"file": ("history.xlsx", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] == 2
    assert "匹配到多个品牌" in data["errors"][0]["reason"]
    assert db.query(HistoricalMapping).filter_by(item_id="930002").count() == 0


def test_import_unknown_brand_code_does_not_auto_create_model(db):
    client = _client(db)
    content = _history_excel([{
        "年": 2026,
        "月": 5,
        "商场": "JD",
        "标题": "UNKNOWN品牌商品",
        "品牌码": "UNKNOWN",
        "型号": "X1",
        "网址": "https://item.jd.com/940001.html",
    }])

    resp = client.post(
        "/api/historical/import",
        files={"file": ("history.xlsx", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    assert resp.status_code == 200
    assert resp.json()["success"] == 1
    assert resp.json()["errors"] == []
    assert db.query(ModelRecord).count() == 0
    row = db.query(HistoricalMapping).one()
    assert row.model_id is None
    assert row.model_code is None
    assert row.model_text == "X1"
    assert row.brand_code_raw == "UNKNOWN"


def test_import_unknown_brand_name_does_not_auto_create_model(db):
    client = _client(db)
    content = _history_excel([{
        "年": 2026,
        "月": 5,
        "商场": "JD",
        "标题": "unknown brand商品",
        "品牌": "unknown brand",
        "型号": "X2",
        "网址": "https://item.jd.com/940002.html",
    }])

    resp = client.post(
        "/api/historical/import",
        files={"file": ("history.xlsx", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    assert resp.status_code == 200
    assert resp.json()["success"] == 1
    assert resp.json()["errors"] == []
    assert db.query(ModelRecord).count() == 0
    row = db.query(HistoricalMapping).one()
    assert row.model_id is None
    assert row.model_code is None
    assert row.model_text == "X2"
    assert row.brand_raw == "unknown brand"


def test_import_model_text_without_brand_does_not_auto_create_model(db):
    client = _client(db)
    content = _history_excel([{
        "年": 2026,
        "月": 5,
        "商场": "JD",
        "标题": "无品牌商品",
        "型号": "NO-BRAND-MODEL",
        "网址": "https://item.jd.com/910001.html",
    }])

    resp = client.post(
        "/api/historical/import",
        files={"file": ("history.xlsx", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    assert resp.status_code == 200
    assert resp.json()["success"] == 1
    assert resp.json()["errors"] == []
    assert db.query(ModelRecord).count() == 0
    row = db.query(HistoricalMapping).one()
    assert row.model_id is None
    assert row.model_code is None
    assert row.model_text == "NO-BRAND-MODEL"


def test_import_keeps_same_title_rows_with_different_item_ids_separate(db):
    _seed_model(db, model_code="QH-215", model_name="QHTF 21.5", brand_code="ROCK")
    client = _client(db)
    content = _history_excel([
        {
            "年": 2026,
            "月": 5,
            "商场": "JD",
            "标题": "洛图测试商品",
            "型号": "QH-215",
            "网址": "https://item.jd.com/100001.html",
        },
        {
            "年": 2026,
            "月": 5,
            "商场": "JD",
            "标题": "洛图测试商品",
            "型号": "QH-215",
            "网址": "https://item.jd.com/100002.html",
        },
    ])

    resp = client.post(
        "/api/historical/import",
        files={"file": ("history.xlsx", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] == 2
    assert data["created"] == 2
    assert data["updated"] == 0
    item_ids = {row.item_id for row in db.query(HistoricalMapping).all()}
    assert item_ids == {"100001", "100002"}


def test_import_rejects_non_integral_month(db):
    _seed_model(db, model_code="QH-215", model_name="QHTF 21.5", brand_code="ROCK")
    client = _client(db)
    content = _history_excel([{
        "年": 2026, "月": 5.9, "商场": "JD", "标题": "洛图测试商品", "型号": "QH-215"
    }])

    resp = client.post(
        "/api/historical/import",
        files={"file": ("history.xlsx", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] == 0
    assert "月不能为空" in data["errors"][0]["reason"]
    assert db.query(HistoricalMapping).count() == 0


def test_import_same_product_different_months_coexist(db):
    _seed_model(db, model_code="DJI-MINI-4", model_name="Mini 4 Pro", brand_code="DJI")
    client = _client(db)
    first = _history_excel([{"年": 2026, "月": 5, "商场": "TMALL", "标题": "同款商品", "型号": "DJI-MINI-4", "网址": "https://detail.tmall.com/item.htm?id=100"}])
    second = _history_excel([{"年": 2026, "月": 6, "商场": "TMALL", "标题": "同款商品", "型号": "DJI-MINI-4", "网址": "https://detail.tmall.com/item.htm?id=100"}])

    client.post("/api/historical/import", files={"file": ("may.xlsx", first, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    resp = client.post("/api/historical/import", files={"file": ("jun.xlsx", second, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})

    assert resp.json()["created"] == 1
    assert resp.json()["updated"] == 0
    assert db.query(HistoricalMapping).count() == 2


def test_import_same_product_same_month_updates_existing(db):
    _seed_model(db, model_code="DJI-MINI-4", model_name="Mini 4 Pro", brand_code="DJI")
    client = _client(db)
    first = _history_excel([{"年": 2026, "月": 5, "商场": "TMALL", "标题": "旧标题", "型号": "DJI-MINI-4", "销量": 1, "网址": "https://detail.tmall.com/item.htm?id=100"}])
    second = _history_excel([{"年": 2026, "月": 5, "商场": "TMALL", "标题": "新标题", "型号": "DJI-MINI-4", "销量": 9, "网址": "https://detail.tmall.com/item.htm?id=100"}])

    client.post("/api/historical/import", files={"file": ("first.xlsx", first, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    resp = client.post("/api/historical/import", files={"file": ("second.xlsx", second, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})

    assert resp.json()["created"] == 0
    assert resp.json()["updated"] == 1
    row = db.query(HistoricalMapping).one()
    assert row.item_name == "新标题"
    assert row.sales_qty == 9
    assert row.import_batch == "second.xlsx"


def test_import_same_product_same_month_different_weeks_coexist(db):
    _seed_model(db, model_code="DJI-MINI-4", model_name="Mini 4 Pro", brand_code="DJI")
    client = _client(db)
    w1 = _history_excel([{"年": 2026, "月": 5, "周": "W20", "商场": "TMALL", "标题": "同款商品", "型号": "DJI-MINI-4", "网址": "https://detail.tmall.com/item.htm?id=100"}])
    w2 = _history_excel([{"年": 2026, "月": 5, "周": "W21", "商场": "TMALL", "标题": "同款商品", "型号": "DJI-MINI-4", "网址": "https://detail.tmall.com/item.htm?id=100"}])

    client.post("/api/historical/import", files={"file": ("w20.xlsx", w1, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    client.post("/api/historical/import", files={"file": ("w21.xlsx", w2, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})

    assert db.query(HistoricalMapping).count() == 2


def test_list_mappings_filters_by_month_model_and_item_keywords(db):
    _seed_model(db, model_code="DJI-MINI-4", model_name="Mini 4 Pro", brand_code="DJI")
    client = _client(db)
    content = _history_excel([
        {"年": 2026, "月": 5, "商场": "TMALL", "标题": "DJI Mini 商品", "型号": "DJI-MINI-4", "网址": "https://detail.tmall.com/item.htm?id=100"},
        {"年": 2026, "月": 6, "商场": "JD", "标题": "其他商品", "型号": "DJI-MINI-4", "网址": "https://item.jd.com/200.html"},
    ])
    client.post("/api/historical/import", files={"file": ("history.xlsx", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})

    resp = client.get("/api/historical/mappings", params={"month": "2026-05", "model_keyword": "MINI", "item_keyword": "DJI"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    item = data["items"][0]
    assert set(item.keys()) == {
        "id",
        "platform",
        "item_id",
        "item_url",
        "item_name",
        "brand_raw",
        "brand_code_raw",
        "model_text",
        "model_id",
        "model_code",
        "standard_model_name",
        "category_code",
        "category_name_raw",
        "year",
        "month_num",
        "month",
        "week",
        "sales_qty",
        "price",
        "sales_amount",
        "import_batch",
        "match_key_type",
        "updated_at",
    }
    assert item["platform"] == "tmall"
    assert item["item_name"] == "DJI Mini 商品"
    assert item["month"] == "2026-05"
    assert item["model_code"] == "DJI-MINI-4"
    assert item["standard_model_name"] == "Mini 4 Pro"


def test_list_mappings_filters_by_platform_import_batch_and_category_code(db):
    _seed_model(db, model_code="DJI-MINI-4", model_name="Mini 4 Pro", brand_code="DJI", category_code="drone")
    _seed_model(db, model_code="QH-215", model_name="QHTF 21.5", brand_code="ROCK", category_code="display")
    client = _client(db)
    first = _history_excel([{"年": 2026, "月": 5, "商场": "TMALL", "标题": "无人机商品", "型号": "DJI-MINI-4"}])
    second = _history_excel([{"年": 2026, "月": 5, "商场": "JD", "标题": "显示器商品", "型号": "QH-215"}])

    first_resp = client.post("/api/historical/import", files={"file": ("first.xlsx", first, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    client.post("/api/historical/import", files={"file": ("second.xlsx", second, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})

    resp = client.get(
        "/api/historical/mappings",
        params={"platform": "TMALL", "import_batch": first_resp.json()["import_batch"], "category_code": "drone"},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    item = data["items"][0]
    assert item["platform"] == "tmall"
    assert item["import_batch"] == "first.xlsx"
    assert item["category_code"] == "drone"
    assert item["model_code"] == "DJI-MINI-4"


def test_list_mappings_paginates_with_page_and_page_size(db):
    _seed_model(db, model_code="DJI-MINI-4", model_name="Mini 4 Pro", brand_code="DJI")
    client = _client(db)
    content = _history_excel([
        {"年": 2026, "月": 5, "商场": "TMALL", "标题": "商品1", "型号": "DJI-MINI-4", "网址": "https://detail.tmall.com/item.htm?id=101"},
        {"年": 2026, "月": 5, "商场": "TMALL", "标题": "商品2", "型号": "DJI-MINI-4", "网址": "https://detail.tmall.com/item.htm?id=102"},
        {"年": 2026, "月": 5, "商场": "TMALL", "标题": "商品3", "型号": "DJI-MINI-4", "网址": "https://detail.tmall.com/item.htm?id=103"},
    ])
    client.post("/api/historical/import", files={"file": ("history.xlsx", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})

    resp = client.get("/api/historical/mappings", params={"page": 2, "page_size": 2})

    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 3
    assert data["page"] == 2
    assert data["page_size"] == 2
    assert [item["item_id"] for item in data["items"]] == ["101"]


def test_list_batches_returns_count_updated_at_and_orders_newest_first(db):
    _seed_model(db, model_code="DJI-MINI-4", model_name="Mini 4 Pro", brand_code="DJI")
    client = _client(db)
    first = _history_excel([
        {"年": 2026, "月": 5, "商场": "TMALL", "标题": "商品1", "型号": "DJI-MINI-4", "网址": "https://detail.tmall.com/item.htm?id=101"},
        {"年": 2026, "月": 5, "商场": "TMALL", "标题": "商品2", "型号": "DJI-MINI-4", "网址": "https://detail.tmall.com/item.htm?id=102"},
    ])
    second = _history_excel([
        {"年": 2026, "月": 6, "商场": "TMALL", "标题": "商品3", "型号": "DJI-MINI-4", "网址": "https://detail.tmall.com/item.htm?id=103"},
    ])
    client.post("/api/historical/import", files={"file": ("old.xlsx", first, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    client.post("/api/historical/import", files={"file": ("new.xlsx", second, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    db.query(HistoricalMapping).filter(HistoricalMapping.import_batch == "old.xlsx").update(
        {HistoricalMapping.updated_at: datetime(2026, 5, 1, 0, 0, 0)},
        synchronize_session=False,
    )
    db.query(HistoricalMapping).filter(HistoricalMapping.import_batch == "new.xlsx").update(
        {HistoricalMapping.updated_at: datetime(2026, 6, 1, 0, 0, 0)},
        synchronize_session=False,
    )
    db.commit()

    resp = client.get("/api/historical/batches")

    assert resp.status_code == 200
    data = resp.json()
    assert data == [
        {"batch": "new.xlsx", "count": 1, "updated_at": "2026-06-01 08:00:00"},
        {"batch": "old.xlsx", "count": 2, "updated_at": "2026-05-01 08:00:00"},
    ]


def test_list_mappings_and_batch_delete_after_import(db):
    _seed_model(db, model_code="QH-215", model_name="QHTF 21.5", brand_code="ROCK")
    client = _client(db)
    content = _history_excel([{
        "年": 2026, "月": 5, "商场": "JD", "标题": "洛图测试商品", "型号": "QH-215"
    }])

    import_resp = client.post(
        "/api/historical/import",
        files={"file": ("history.xlsx", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    import_batch = import_resp.json()["import_batch"]

    list_resp = client.get("/api/historical/mappings")
    assert list_resp.status_code == 200
    list_data = list_resp.json()
    assert list_data["total"] == 1
    assert len(list_data["items"]) == 1

    delete_resp = client.request(
        "DELETE",
        "/api/historical/mappings/batch",
        json={"import_batch": import_batch},
    )
    assert delete_resp.status_code == 204
    assert db.query(HistoricalMapping).count() == 0


def test_headers_parses_legacy_time_dimension_and_preview_stats(db, tmp_path, monkeypatch):
    monkeypatch.setattr("app.api.historical_api.settings.UPLOAD_DIR", str(tmp_path))
    db.add(Category(code="laptop", name="笔记本电脑"))
    db.commit()
    client = _client(db)
    content = _history_excel([{
        "URL": "https://item.jd.com/100188063897.html",
        "品牌+系列": "微软Surface Pro 12（二合一）",
        "年度": "26",
        "时间维度": "26.01",
        "平台": "京东",
        "商品名称": "微软 Surface Pro 12 商品",
        "网址": "https://item.jd.com/100188063897.html",
        "销额": "2107018.08",
        "销量": "305",
        "单价": "6908.256",
        "屏幕尺寸": "12英寸",
    }])

    resp = client.post(
        "/api/historical/headers",
        files={"file": ("【202601】洛图科技笔记本电脑线上数据库.xlsx", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["category_code"] == "laptop"
    assert data["mapping"]["item_url"] == "网址"
    assert data["mapping"]["model_text"] == "品牌+系列"
    assert data["preview"][0]["年"] == "2026"
    assert data["preview"][0]["月"] == "1"
    assert data["stats"]["total_rows"] == 1
    assert data["stats"]["importable_rows"] == 1
    assert data["stats"]["missing_required_rows"] == 0
    assert data["stats"]["missing_model_rows"] == 1
    assert data["stats"]["auto_create_model_count"] == 0


def test_headers_preview_stats_does_not_use_full_streaming_dataframe(db, tmp_path, monkeypatch):
    monkeypatch.setattr("app.api.historical_api.settings.UPLOAD_DIR", str(tmp_path))
    if db.query(Category).filter_by(code="router").first() is None:
        db.add(Category(code="router", name="路由器"))
        db.commit()
    client = _client(db)
    content = _history_excel([
        {"年度": 2025, "月度": "2025.12", "平台": "天猫", "商品名称": "路由器 商品", "商品网址": "https://detail.tmall.com/item.htm?id=1006960105587", "产品系列": "D70"},
        {"年度": 2025, "月度": "2025.12", "平台": "天猫", "商品名称": "路由器 商品2", "商品网址": "https://detail.tmall.com/item.htm?id=1006960105588", "产品系列": "D80"},
    ])

    def fail_full_dataframe_read(*args, **kwargs):
        raise AssertionError("headers preview must not build a full streaming DataFrame")

    monkeypatch.setattr("app.api.historical_api._read_sheet_streaming", fail_full_dataframe_read)

    resp = client.post(
        "/api/historical/headers",
        files={"file": ("路由器数据库202501-202604.xlsx", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["stats"]["total_rows"] == 2
    assert len(data["preview"]) == 2


def test_headers_counts_rows_missing_required_fields(db, tmp_path, monkeypatch):
    monkeypatch.setattr("app.api.historical_api.settings.UPLOAD_DIR", str(tmp_path))
    db.add(Category(code="router", name="路由器"))
    db.commit()
    client = _client(db)
    content = _history_excel([
        {"年度": 2025, "月度": "2025.12", "平台": "天猫", "商品名称": "路由器 商品", "商品网址": "https://detail.tmall.com/item.htm?id=1006960105587", "产品系列": "D70"},
        {"年度": 2025, "月度": "2025.12", "平台": "天猫", "商品名称": "", "商品网址": "https://detail.tmall.com/item.htm?id=1006960105588", "产品系列": "D80"},
    ])

    resp = client.post(
        "/api/historical/headers",
        files={"file": ("路由器数据库202501-202604.xlsx", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    assert resp.status_code == 200
    stats = resp.json()["stats"]
    assert stats["total_rows"] == 2
    assert stats["importable_rows"] == 1
    assert stats["missing_required_rows"] == 1


def test_headers_unknown_brand_code_not_auto_create_candidate(db, tmp_path, monkeypatch):
    monkeypatch.setattr("app.api.historical_api.settings.UPLOAD_DIR", str(tmp_path))
    db.add(Category(code="router", name="路由器"))
    db.commit()
    client = _client(db)
    content = _history_excel([{
        "年度": 2025,
        "月度": "2025.12",
        "平台": "天猫",
        "商品名称": "unknown品牌路由器 商品",
        "商品网址": "https://detail.tmall.com/item.htm?id=1006960105593",
        "品牌码": "unknown",
        "产品系列": "X1",
    }])

    resp = client.post(
        "/api/historical/headers",
        files={"file": ("路由器数据库202501-202604.xlsx", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    assert resp.status_code == 200
    stats = resp.json()["stats"]
    assert stats["missing_model_rows"] == 1
    assert stats["auto_create_model_count"] == 0


def test_headers_unknown_brand_name_not_auto_create_candidate(db, tmp_path, monkeypatch):
    monkeypatch.setattr("app.api.historical_api.settings.UPLOAD_DIR", str(tmp_path))
    db.add(Category(code="router", name="路由器"))
    db.commit()
    client = _client(db)
    content = _history_excel([{
        "年度": 2025,
        "月度": "2025.12",
        "平台": "天猫",
        "商品名称": "unknown brand路由器 商品",
        "商品网址": "https://detail.tmall.com/item.htm?id=1006960105594",
        "品牌": "unknown brand",
        "产品系列": "X2",
    }])

    resp = client.post(
        "/api/historical/headers",
        files={"file": ("路由器数据库202501-202604.xlsx", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    assert resp.status_code == 200
    stats = resp.json()["stats"]
    assert stats["missing_model_rows"] == 1
    assert stats["auto_create_model_count"] == 0


def test_headers_counts_under_branded_missing_model_without_auto_create_candidate(db, tmp_path, monkeypatch):
    monkeypatch.setattr("app.api.historical_api.settings.UPLOAD_DIR", str(tmp_path))
    db.add(Category(code="router", name="路由器"))
    db.commit()
    client = _client(db)
    content = _history_excel([{
        "年度": 2025,
        "月度": "2025.12",
        "平台": "天猫",
        "商品名称": "无品牌路由器 商品",
        "商品网址": "https://detail.tmall.com/item.htm?id=1006960105590",
        "产品系列": "D70",
    }])

    resp = client.post(
        "/api/historical/headers",
        files={"file": ("路由器数据库202501-202604.xlsx", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    assert resp.status_code == 200
    stats = resp.json()["stats"]
    assert stats["missing_model_rows"] == 1
    assert stats["auto_create_model_count"] == 0


def test_headers_uses_brand_name_as_brand_code_for_ambiguous_model_code(db, tmp_path, monkeypatch):
    monkeypatch.setattr("app.api.historical_api.settings.UPLOAD_DIR", str(tmp_path))
    _seed_model(db, model_code="SAME-CODE", model_name="Model A", brand_code="BRAND-A")
    _seed_model(db, model_code="SAME-CODE", model_name="Model B", brand_code="BRAND-B")
    db.add(Category(code="router", name="路由器"))
    db.commit()
    client = _client(db)
    content = _history_excel([{
        "年度": 2025,
        "月度": "2025.12",
        "平台": "天猫",
        "商品名称": "品牌展示名商品",
        "商品网址": "https://detail.tmall.com/item.htm?id=1006960105591",
        "品牌": "BRAND-A",
        "型号码": "SAME-CODE",
    }])

    resp = client.post(
        "/api/historical/headers",
        files={"file": ("路由器数据库202501-202604.xlsx", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    assert resp.status_code == 200
    stats = resp.json()["stats"]
    assert stats["missing_model_rows"] == 0
    assert stats["auto_create_model_count"] == 0


def test_headers_uses_brand_name_as_brand_code_for_ambiguous_model_name(db, tmp_path, monkeypatch):
    monkeypatch.setattr("app.api.historical_api.settings.UPLOAD_DIR", str(tmp_path))
    _seed_model(db, model_code="MODEL-A", model_name="Shared Name", brand_code="BRAND-A")
    _seed_model(db, model_code="MODEL-B", model_name="Shared Name", brand_code="BRAND-B")
    db.add(Category(code="router", name="路由器"))
    db.commit()
    client = _client(db)
    content = _history_excel([{
        "年度": 2025,
        "月度": "2025.12",
        "平台": "天猫",
        "商品名称": "品牌展示名商品",
        "商品网址": "https://detail.tmall.com/item.htm?id=1006960105592",
        "品牌": "BRAND-A",
        "产品系列": "Shared Name",
    }])

    resp = client.post(
        "/api/historical/headers",
        files={"file": ("路由器数据库202501-202604.xlsx", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    assert resp.status_code == 200
    stats = resp.json()["stats"]
    assert stats["missing_model_rows"] == 0
    assert stats["auto_create_model_count"] == 0


def test_headers_counts_missing_model_rows_per_row_but_auto_create_candidates_distinct(db, tmp_path, monkeypatch):
    monkeypatch.setattr("app.api.historical_api.settings.UPLOAD_DIR", str(tmp_path))
    db.add(Category(code="router", name="路由器"))
    db.commit()
    client = _client(db)
    content = _history_excel([
        {"年度": 2025, "月度": "2025.12", "平台": "天猫", "商品名称": "路由器 商品1", "商品网址": "https://detail.tmall.com/item.htm?id=1006960105587", "品牌": "追觅", "产品系列": "D70"},
        {"年度": 2025, "月度": "2025.12", "平台": "天猫", "商品名称": "路由器 商品2", "商品网址": "https://detail.tmall.com/item.htm?id=1006960105588", "品牌": "追觅", "产品系列": "D70"},
    ])

    resp = client.post(
        "/api/historical/headers",
        files={"file": ("路由器数据库202501-202604.xlsx", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    assert resp.status_code == 200
    stats = resp.json()["stats"]
    assert stats["missing_model_rows"] == 2
    assert stats["auto_create_model_count"] == 1


def test_confirm_auto_creates_missing_model_from_legacy_row(db, tmp_path, monkeypatch):
    monkeypatch.setattr("app.api.historical_api.settings.UPLOAD_DIR", str(tmp_path))
    db.add(Category(code="router", name="路由器"))
    db.commit()
    client = _client(db)
    content = _history_excel([{
        "年度": 2025,
        "月度": "2025.12",
        "平台": "天猫",
        "渠道类型": "平台电商",
        "商品名称": "追觅生活D70路由器BE3600家用高速WIFI7双频路由器",
        "商品网址": "https://detail.tmall.com/item.htm?id=1006960105587",
        "品牌": "追觅",
        "产品系列": "D70",
        "品牌产品系列": "追觅D70",
        "单价": 399,
        "销量": 4,
        "销额": 1596,
    }])
    headers_resp = client.post(
        "/api/historical/headers",
        files={"file": ("路由器数据库202501-202604.xlsx", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert headers_resp.status_code == 200
    preview = headers_resp.json()

    resp = client.post("/api/historical/confirm", json={
        "temp_file_id": preview["temp_file_id"],
        "sheet_name": preview["sheet_name"],
        "mapping": preview["mapping"],
        "category_code": preview["category_code"],
    })

    assert resp.status_code == 200
    assert resp.json()["success"] == 1
    model = db.query(ModelRecord).one()
    assert model.brand_code == "追觅"
    assert model.model_code == "D70"
    assert model.model_name == "D70"
    assert model.category_code == "router"
    row = db.query(HistoricalMapping).one()
    assert row.model_id == model.id
    assert row.model_code == "D70"
    assert row.category_code == "router"


def test_import_allows_blank_model_without_auto_create(db):
    db.add(Category(code="door_lock", name="门锁"))
    db.commit()
    client = _client(db)
    content = _history_excel([{
        "年度": 2026,
        "月度": 4,
        "平台": "京东",
        "宝贝名称": "门锁 商品",
        "宝贝链接": "https://item.jd.com/300001.html",
        "品牌": "品牌A",
        "机型": None,
    }])

    resp = client.post(
        "/api/historical/import",
        files={"file": ("2023-2026.04门锁-传统+新兴.xlsx", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    assert resp.status_code == 200
    assert resp.json()["success"] == 1
    assert db.query(ModelRecord).count() == 0
    row = db.query(HistoricalMapping).one()
    assert row.model_id is None
    assert row.model_code is None


def test_preview_rejects_invalid_temp_file_id(db, tmp_path, monkeypatch):
    monkeypatch.setattr("app.api.historical_api.settings.UPLOAD_DIR", str(tmp_path))
    client = _client(db)

    resp = client.post("/api/historical/preview", json={
        "temp_file_id": "*",
        "sheet_name": "Sheet1",
        "mapping": {},
        "category_code": "router",
    })

    assert resp.status_code == 400
    assert resp.json()["detail"] == "无效的临时文件 ID"


def test_preview_reports_invalid_mapping_source_column(db, tmp_path, monkeypatch):
    monkeypatch.setattr("app.api.historical_api.settings.UPLOAD_DIR", str(tmp_path))
    db.add(Category(code="router", name="路由器"))
    db.commit()
    client = _client(db)
    content = _history_excel([{
        "年度": 2025,
        "月度": "2025.12",
        "平台": "天猫",
        "商品名称": "路由器 商品",
        "商品网址": "https://detail.tmall.com/item.htm?id=1006960105587",
    }])
    headers_resp = client.post(
        "/api/historical/headers",
        files={"file": ("路由器数据库202501-202604.xlsx", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert headers_resp.status_code == 200
    preview = headers_resp.json()
    mapping = dict(preview["mapping"])
    mapping["item_name"] = "不存在列"

    resp = client.post("/api/historical/preview", json={
        "temp_file_id": preview["temp_file_id"],
        "sheet_name": preview["sheet_name"],
        "mapping": mapping,
        "category_code": preview["category_code"],
    })

    assert resp.status_code == 200
    assert "字段映射不存在：标题 -> 不存在列" in resp.json()["issues"]
    assert resp.json()["mapping"]["item_name"] == "商品名称"


def test_confirm_rejects_invalid_mapping_source_column(db, tmp_path, monkeypatch):
    monkeypatch.setattr("app.api.historical_api.settings.UPLOAD_DIR", str(tmp_path))
    db.add(Category(code="router", name="路由器"))
    db.commit()
    client = _client(db)
    content = _history_excel([{
        "年度": 2025,
        "月度": "2025.12",
        "平台": "天猫",
        "商品名称": "路由器 商品",
        "商品网址": "https://detail.tmall.com/item.htm?id=1006960105587",
    }])
    headers_resp = client.post(
        "/api/historical/headers",
        files={"file": ("路由器数据库202501-202604.xlsx", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert headers_resp.status_code == 200
    preview = headers_resp.json()
    mapping = dict(preview["mapping"])
    mapping["item_name"] = "不存在列"

    resp = client.post("/api/historical/confirm", json={
        "temp_file_id": preview["temp_file_id"],
        "sheet_name": preview["sheet_name"],
        "mapping": mapping,
        "category_code": preview["category_code"],
    })

    assert resp.status_code == 422
    assert "字段映射不存在：标题 -> 不存在列" in resp.json()["detail"]
