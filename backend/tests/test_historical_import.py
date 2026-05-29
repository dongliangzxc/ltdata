import io
from datetime import datetime

import pandas as pd
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event

from app.api.historical_api import router as historical_router
from app.models.database import get_db
from app.models.schemas import HistoricalMapping, ModelRecord


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


def test_import_requires_platform_title_model_year_and_month(db):
    client = _client(db)
    content = _history_excel([{"商场": "", "标题": "", "型号": "", "年": "", "月": ""}])

    resp = client.post(
        "/api/historical/import",
        files={"file": ("bad.xlsx", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] == 0
    reasons = "\n".join(e["reason"] for e in data["errors"])
    assert "商场不能为空" in reasons
    assert "标题不能为空" in reasons
    assert "型号不能为空" in reasons
    assert "年不能为空" in reasons
    assert "月不能为空" in reasons


def test_import_uses_model_text_as_model_code_when_model_code_raw_empty(db):
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


def test_import_rejects_unknown_model(db):
    client = _client(db)
    content = _history_excel([{
        "年": 2026, "月": 5, "商场": "JD", "标题": "洛图测试商品", "型号": "DOES-NOT-EXIST"
    }])

    resp = client.post(
        "/api/historical/import",
        files={"file": ("history.xlsx", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] == 0
    assert "在型号库中不存在" in data["errors"][0]["reason"]


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
        {"batch": "new.xlsx", "count": 1, "updated_at": "2026-06-01T00:00:00"},
        {"batch": "old.xlsx", "count": 2, "updated_at": "2026-05-01T00:00:00"},
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
