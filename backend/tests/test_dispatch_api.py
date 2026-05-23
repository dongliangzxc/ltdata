import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import dispatch_api
from app.api.dispatch_api import router
from app.models.database import Base, get_db
from app.models.schemas import Category, DispatchBatch, DispatchItem, DispatchRule, RawDataRecord, UploadFileRecord


@pytest.fixture
def client_and_db(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    app = FastAPI()
    app.include_router(router)

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    monkeypatch.setattr(dispatch_api, "DISPATCH_PAGE_SIZE", 2)
    try:
        yield TestClient(app), db
    finally:
        db.close()
        Base.metadata.drop_all(engine)


def test_run_dispatch_processes_raw_data_in_pages(client_and_db):
    client, db = client_and_db
    file_record = UploadFileRecord(filename="large.xlsx", platform="JD", row_count=5, status="done")
    db.add(file_record)
    db.flush()
    db.add(DispatchRule(
        category_code="headphone",
        platform="jd",
        field="category_lv1",
        match_type="contains",
        value="耳机",
        priority=1,
        is_active=1,
    ))
    db.add(DispatchRule(
        category_code="speaker",
        platform=None,
        field="item_name",
        match_type="contains",
        value="音箱",
        priority=2,
        is_active=1,
    ))
    for idx, (category, item_name) in enumerate([
        ("蓝牙耳机", "商品 1"),
        ("头戴耳机", "商品 2"),
        ("智能硬件", "无线音箱"),
        ("手机配件", "保护壳"),
        ("入耳耳机", "商品 5"),
    ], start=1):
        db.add(RawDataRecord(
            file_id=file_record.id,
            platform="jd",
            month=202605,
            item_id=f"item-{idx}",
            category_lv1=category,
            item_name=item_name,
        ))
    db.commit()

    response = client.post("/api/dispatch/run", json={"file_id": file_record.id})

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "done"
    assert payload["total_rows"] == 5
    assert payload["dispatched_rows"] == 4
    assert payload["unmatched_rows"] == 1
    batch = db.query(DispatchBatch).filter_by(id=payload["id"]).one()
    assert batch.status == "done"
    items = db.query(DispatchItem).filter_by(batch_id=batch.id).all()
    assert len(items) == 4
    assert [item.category_code for item in items] == ["headphone", "headphone", "speaker", "headphone"]


def test_run_dispatch_marks_error_and_rolls_back_partial_items(client_and_db, monkeypatch):
    client, db = client_and_db
    file_record = UploadFileRecord(filename="error.xlsx", platform="JD", row_count=3, status="done")
    db.add(file_record)
    db.flush()
    db.add(DispatchRule(
        category_code="headphone",
        platform="jd",
        field="item_name",
        match_type="contains",
        value="商品",
        priority=1,
        is_active=1,
    ))
    for idx, item_name in enumerate(["商品 1", "商品 2", "boom"], start=1):
        db.add(RawDataRecord(
            file_id=file_record.id,
            platform="jd",
            month=202605,
            item_id=f"item-{idx}",
            item_name=item_name,
        ))
    db.commit()

    def fail_on_boom(row, rule):
        if row.item_name == "boom":
            raise RuntimeError("boom")
        return dispatch_api._field_value(row, rule.field).find(rule.value) >= 0

    monkeypatch.setattr(dispatch_api, "_rule_matches", fail_on_boom)

    with pytest.raises(RuntimeError):
        client.post("/api/dispatch/run", json={"file_id": file_record.id})

    batch = db.query(DispatchBatch).one()
    assert batch.status == "error"
    assert db.query(DispatchItem).count() == 0


def test_get_batch_stats_returns_category_names_and_rule_counts(client_and_db):
    client, db = client_and_db
    db.add(Category(code="headphone", name="耳机", sort_order=1))
    db.add(Category(code="speaker", name="音箱", sort_order=2))
    file_record = UploadFileRecord(filename="stats.xlsx", platform="JD", row_count=4, status="done")
    db.add(file_record)
    db.flush()
    rule_one = DispatchRule(
        category_code="headphone",
        platform="jd",
        field="category_lv1",
        match_type="contains",
        value="耳机",
        item_name_keyword=None,
        priority=1,
        is_active=1,
    )
    rule_two = DispatchRule(
        category_code="speaker",
        platform=None,
        field="item_name",
        match_type="contains",
        value="音箱",
        item_name_keyword="无线",
        priority=2,
        is_active=1,
    )
    db.add(rule_one)
    db.add(rule_two)
    db.flush()
    batch = DispatchBatch(
        file_id=file_record.id,
        status="done",
        total_rows=4,
        dispatched_rows=3,
        unmatched_rows=1,
    )
    db.add(batch)
    db.flush()
    db.add_all([
        DispatchItem(batch_id=batch.id, raw_data_id=1, category_code="headphone", matched_rule_id=rule_one.id),
        DispatchItem(batch_id=batch.id, raw_data_id=2, category_code="headphone", matched_rule_id=rule_one.id),
        DispatchItem(batch_id=batch.id, raw_data_id=3, category_code="speaker", matched_rule_id=rule_two.id),
    ])
    db.commit()

    response = client.get(f"/api/dispatch/batches/{batch.id}/stats")

    assert response.status_code == 200
    payload = response.json()
    assert payload["batch_id"] == batch.id
    assert payload["total_rows"] == 4
    assert payload["dispatched_rows"] == 3
    assert payload["unmatched_rows"] == 1
    assert payload["categories"] == [
        {"category_code": "headphone", "category_name": "耳机", "count": 2},
        {"category_code": "speaker", "category_name": "音箱", "count": 1},
    ]
    assert payload["rules"] == [
        {
            "rule_id": rule_one.id,
            "category_code": "headphone",
            "category_name": "耳机",
            "field": "category_lv1",
            "match_type": "contains",
            "value": "耳机",
            "item_name_keyword": None,
            "platform": "jd",
            "priority": 1,
            "is_active": 1,
            "count": 2,
        },
        {
            "rule_id": rule_two.id,
            "category_code": "speaker",
            "category_name": "音箱",
            "field": "item_name",
            "match_type": "contains",
            "value": "音箱",
            "item_name_keyword": "无线",
            "platform": None,
            "priority": 2,
            "is_active": 1,
            "count": 1,
        },
    ]


def test_get_batch_stats_returns_404_for_missing_batch(client_and_db):
    client, _ = client_and_db

    response = client.get("/api/dispatch/batches/999/stats")

    assert response.status_code == 404


def test_get_batch_stats_preserves_deleted_rule_counts(client_and_db):
    client, db = client_and_db
    db.add(Category(code="headphone", name="耳机", sort_order=1))
    file_record = UploadFileRecord(filename="deleted-rule.xlsx", platform="JD", row_count=1, status="done")
    db.add(file_record)
    db.flush()
    batch = DispatchBatch(
        file_id=file_record.id,
        status="done",
        total_rows=1,
        dispatched_rows=1,
        unmatched_rows=0,
    )
    db.add(batch)
    db.flush()
    deleted_rule_id = 12345
    db.add(DispatchItem(
        batch_id=batch.id,
        raw_data_id=1,
        category_code="headphone",
        matched_rule_id=deleted_rule_id,
    ))
    db.commit()

    response = client.get(f"/api/dispatch/batches/{batch.id}/stats")

    assert response.status_code == 200
    payload = response.json()
    assert payload["rules"] == [
        {
            "rule_id": deleted_rule_id,
            "category_code": "headphone",
            "category_name": "耳机",
            "field": None,
            "match_type": None,
            "value": None,
            "item_name_keyword": None,
            "platform": None,
            "priority": None,
            "is_active": None,
            "count": 1,
        },
    ]


def test_get_batch_stats_groups_deleted_rule_counts_by_rule_id(client_and_db):
    client, db = client_and_db
    db.add(Category(code="headphone", name="耳机", sort_order=1))
    db.add(Category(code="speaker", name="音箱", sort_order=2))
    file_record = UploadFileRecord(filename="deleted-rule-multi-category.xlsx", platform="JD", row_count=2, status="done")
    db.add(file_record)
    db.flush()
    batch = DispatchBatch(
        file_id=file_record.id,
        status="done",
        total_rows=2,
        dispatched_rows=2,
        unmatched_rows=0,
    )
    db.add(batch)
    db.flush()
    deleted_rule_id = 12345
    db.add_all([
        DispatchItem(batch_id=batch.id, raw_data_id=1, category_code="speaker", matched_rule_id=deleted_rule_id),
        DispatchItem(batch_id=batch.id, raw_data_id=2, category_code="headphone", matched_rule_id=deleted_rule_id),
    ])
    db.commit()

    response = client.get(f"/api/dispatch/batches/{batch.id}/stats")

    assert response.status_code == 200
    payload = response.json()
    assert payload["rules"] == [
        {
            "rule_id": deleted_rule_id,
            "category_code": "headphone",
            "category_name": "耳机",
            "field": None,
            "match_type": None,
            "value": None,
            "item_name_keyword": None,
            "platform": None,
            "priority": None,
            "is_active": None,
            "count": 2,
        },
    ]
