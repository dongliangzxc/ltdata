import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import dispatch_api
from app.api.dispatch_api import router
from app.models.database import Base, get_db
from app.models.schemas import DispatchBatch, DispatchItem, DispatchRule, RawDataRecord, UploadFileRecord


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
