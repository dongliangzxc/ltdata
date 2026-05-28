from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.rules_api import router
from app.models.database import get_db
from app.models.schemas import (
    Category,
    CleanJobRecord,
    FilteredItem,
    InterventionRule,
    RawDataRecord,
    UploadFileRecord,
)


def _make_client(db):
    app = FastAPI()
    app.include_router(router)

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    return TestClient(app)


def test_create_and_list_intervention_rule(db):
    client = _make_client(db)
    db.add(Category(code="projector", name="投影"))
    db.commit()

    response = client.post("/api/rules/intervention-rules", json={
        "name": "海信低价配件过滤",
        "category_code": "projector",
        "action": "filter",
        "priority": 10,
        "conditions": {
            "brand_in": ["海信"],
            "item_name_not_contains_any": ["激光电视"],
            "reference_price": {"op": "lt", "value": 500},
        },
    })

    assert response.status_code == 201
    created = response.json()
    assert created["id"] > 0
    assert created["name"] == "海信低价配件过滤"
    assert created["category_code"] == "projector"
    assert created["action"] == "filter"
    assert created["priority"] == 10
    assert created["is_active"] == 1
    assert created["conditions"]["brand_in"] == ["海信"]

    listed = client.get("/api/rules/intervention-rules", params={"category_code": "projector"}).json()
    assert [row["id"] for row in listed] == [created["id"]]
    assert listed[0]["summary"] == "品牌 in [海信] 且 商品名称不包含 [激光电视] 且 参考价格 < 500"


def test_intervention_rule_requires_category_and_valid_action(db):
    client = _make_client(db)

    missing_category = client.post("/api/rules/intervention-rules", json={
        "name": "无品类规则",
        "category_code": "",
        "action": "filter",
        "priority": 10,
        "conditions": {"item_name_contains_any": ["配件"]},
    })
    assert missing_category.status_code == 400
    assert missing_category.json()["detail"] == "category_code 不能为空"

    db.add(Category(code="projector", name="投影"))
    db.commit()

    invalid_action = client.post("/api/rules/intervention-rules", json={
        "name": "错误动作",
        "category_code": "projector",
        "action": "delete",
        "priority": 10,
        "conditions": {"item_name_contains_any": ["配件"]},
    })
    assert invalid_action.status_code == 400
    assert invalid_action.json()["detail"] == "action 必须是 filter 或 allow"


def test_intervention_rule_validates_price_condition(db):
    client = _make_client(db)
    db.add(Category(code="projector", name="投影"))
    db.commit()

    response = client.post("/api/rules/intervention-rules", json={
        "name": "错误价格规则",
        "category_code": "projector",
        "action": "filter",
        "priority": 10,
        "conditions": {"reference_price": {"op": "between", "value": 500}},
    })

    assert response.status_code == 400
    assert response.json()["detail"] == "reference_price between 必须包含 min 和 max"


def test_intervention_rule_rejects_unknown_condition_key(db):
    client = _make_client(db)
    db.add(Category(code="projector", name="投影"))
    db.commit()

    response = client.post("/api/rules/intervention-rules", json={
        "name": "未知条件规则",
        "category_code": "projector",
        "action": "filter",
        "priority": 10,
        "conditions": {"unknown_key": ["x"]},
    })

    assert response.status_code == 400
    assert response.json()["detail"] == "不支持的干预条件: unknown_key"


def test_intervention_rule_rejects_invalid_numeric_price_value(db):
    client = _make_client(db)
    db.add(Category(code="projector", name="投影"))
    db.commit()

    response = client.post("/api/rules/intervention-rules", json={
        "name": "非法价格规则",
        "category_code": "projector",
        "action": "filter",
        "priority": 10,
        "conditions": {"reference_price": {"op": "lt", "value": "abc"}},
    })

    assert response.status_code == 400
    assert response.json()["detail"] == "reference_price 数值必须是有效数字"


def test_intervention_rule_rejects_non_finite_price_value(db):
    client = _make_client(db)
    db.add(Category(code="projector", name="投影"))
    db.commit()

    response = client.post("/api/rules/intervention-rules", json={
        "name": "非有限价格规则",
        "category_code": "projector",
        "action": "filter",
        "priority": 10,
        "conditions": {"reference_price": {"op": "lt", "value": "nan"}},
    })

    assert response.status_code == 400
    assert response.json()["detail"] == "reference_price 数值必须是有效数字"


def test_intervention_rule_rejects_between_min_greater_than_max(db):
    client = _make_client(db)
    db.add(Category(code="projector", name="投影"))
    db.commit()

    response = client.post("/api/rules/intervention-rules", json={
        "name": "价格区间错误规则",
        "category_code": "projector",
        "action": "filter",
        "priority": 10,
        "conditions": {"reference_price": {"op": "between", "min": 1000, "max": 500}},
    })

    assert response.status_code == 400
    assert response.json()["detail"] == "reference_price between 最低价不能大于最高价"


def test_intervention_rule_patch_rejects_invalid_is_active(db):
    client = _make_client(db)
    db.add(Category(code="projector", name="投影"))
    db.add(InterventionRule(
        name="旧规则",
        category_code="projector",
        action="filter",
        priority=50,
        conditions={"item_name_contains_any": ["配件"]},
    ))
    db.commit()
    rule = db.query(InterventionRule).first()

    response = client.patch(f"/api/rules/intervention-rules/{rule.id}", json={"is_active": 2})

    assert response.status_code == 400
    assert response.json()["detail"] == "is_active 必须是 0 或 1"


def test_update_toggle_and_delete_intervention_rule(db):
    client = _make_client(db)
    db.add(Category(code="projector", name="投影"))
    db.add(InterventionRule(
        name="旧规则",
        category_code="projector",
        action="filter",
        priority=50,
        conditions={"item_name_contains_any": ["配件"]},
    ))
    db.commit()
    rule = db.query(InterventionRule).first()

    updated = client.patch(f"/api/rules/intervention-rules/{rule.id}", json={
        "name": "新规则",
        "action": "allow",
        "priority": 5,
        "is_active": 0,
    })
    assert updated.status_code == 200
    assert updated.json()["name"] == "新规则"
    assert updated.json()["action"] == "allow"
    assert updated.json()["priority"] == 5
    assert updated.json()["is_active"] == 0

    deleted = client.delete(f"/api/rules/intervention-rules/{rule.id}")
    assert deleted.status_code == 204
    assert db.query(InterventionRule).count() == 0


def test_filtered_items_include_intervention_rule_reason(db):
    client = _make_client(db)
    db.add(Category(code="projector", name="投影"))
    rule = InterventionRule(
        name="配件过滤",
        category_code="projector",
        action="filter",
        priority=10,
        conditions={"item_name_contains_any": ["配件"]},
    )
    upload_file = UploadFileRecord(filename="test.xlsx", platform="JD", row_count=1)
    db.add_all([rule, upload_file])
    db.flush()

    raw = RawDataRecord(
        file_id=upload_file.id,
        platform="JD",
        month=202605,
        item_id="sku-1",
        item_name="投影仪配件",
        brand_raw="测试品牌",
        shop_name="测试店铺",
    )
    clean_job = CleanJobRecord(file_ids=[upload_file.id], rules={}, status="done", row_in=1, row_out=0, row_filtered=1)
    db.add_all([raw, clean_job])
    db.flush()

    db.add(FilteredItem(
        raw_data_id=raw.id,
        clean_job_id=clean_job.id,
        matched_keyword="配件",
        intervention_rule_id=rule.id,
        intervention_rule_name=rule.name,
        matched_reason="命中规则「配件过滤」：商品名称包含 [配件]",
    ))
    db.commit()

    response = client.get("/api/rules/filtered-items")

    assert response.status_code == 200
    first_item = response.json()["items"][0]
    assert first_item["intervention_rule_id"] == rule.id
    assert first_item["intervention_rule_name"] == "配件过滤"
    assert first_item["matched_reason"] == "命中规则「配件过滤」：商品名称包含 [配件]"
