"""Clean task supplement upload appends only new rows and preserves old results."""
import io

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.clean import router
from app.core.auth_deps import get_current_user
from app.models.database import Base, get_db
from app.models.schemas import (
    Category,
    CleanJobItemRecord,
    CleanJobRecord,
    CleanedDataRecord,
    ColumnTemplate,
    DispatchBatch,
    DispatchItem,
    MatchResult,
    RawDataRecord,
    UploadFileRecord,
)


class DummyUser:
    is_admin = 1
    category_permissions = []


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    app = FastAPI()
    app.include_router(router)

    def override_db():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: DummyUser()
    test_client = TestClient(app)
    test_client.Session = Session
    return test_client


def _seed_task(session):
    session.add(Category(code="laptop", name="笔记本"))
    upload = UploadFileRecord(filename="old.xlsx", platform="jd", row_count=1, status="done")
    session.add(upload)
    session.flush()
    old_raw = RawDataRecord(
        file_id=upload.id,
        country_code="CN",
        platform="jd",
        month=202609,
        item_id="old-1",
        item_name="旧数据",
        sales_qty=1,
        sales_amount=100,
        price=100,
    )
    session.add(old_raw)
    session.flush()
    job = CleanJobRecord(
        file_ids=[upload.id],
        rules={"dedup": True},
        status="reviewing",
        category_code="laptop",
        dispatch_category_code="laptop",
        platform="jd",
        source_scope={"months": [202609], "platforms": ["jd"], "file_ids": [upload.id]},
        row_in=1,
        row_out=1,
    )
    session.add(job)
    session.flush()
    session.add(CleanJobItemRecord(
        clean_job_id=job.id,
        raw_data_id=old_raw.id,
        category_code="laptop",
        platform="jd",
    ))
    session.add(CleanedDataRecord(
        clean_job_id=job.id,
        raw_data_id=old_raw.id,
        country_code="CN",
        platform="jd",
        month=202609,
        item_id="old-1",
        shop_name="旧店铺",
    ))
    session.add(MatchResult(
        clean_job_id=job.id,
        raw_data_id=old_raw.id,
        match_status="confirmed",
        matched_by="manual",
        model_id=1,
    ))
    template = ColumnTemplate(
        name="笔记本补充模板",
        module="sales",
        mapping={
            "商品ID": "item_id",
            "商品名称": "item_name",
            "销量": "sales_qty",
            "销售额": "sales_amount",
            "价格": "price",
            "月份": "month",
            "平台": "platform",
        },
        ignore_columns=[],
        is_builtin=0,
    )
    session.add(template)
    session.commit()
    return job.id, template.id, old_raw.id


def test_supplement_appends_new_rows_and_keeps_old_results(client):
    with client.Session() as session:
        job_id, template_id, old_raw_id = _seed_task(session)

    csv_content = (
        "商品ID,商品名称,销量,销售额,价格,月份,平台\n"
        "new-1,新增数据,2,200,100,202609,jd\n"
        "old-1,旧数据,1,100,100,202609,jd\n"
    )
    res = client.post(
        f"/api/clean/tasks/{job_id}/supplement",
        files={"file": ("supplement.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")},
        data={"template_id": str(template_id)},
    )
    assert res.status_code == 200, res.text
    data = res.json()["data"]
    assert data["inserted_rows"] == 1
    assert data["duplicate_rows"] == 1
    assert data["appended_items"] == 1
    assert data["row_in"] == 2

    with client.Session() as session:
        new_raw = session.query(RawDataRecord).filter(RawDataRecord.item_id == "new-1").one()
        assert new_raw.country_code == "CN"
        assert new_raw.platform == "jd"
        assert new_raw.month == 202609
        assert session.query(CleanJobItemRecord).filter(
            CleanJobItemRecord.clean_job_id == job_id,
            CleanJobItemRecord.raw_data_id == new_raw.id,
        ).one()
        batch = session.query(DispatchBatch).filter(DispatchBatch.file_id == new_raw.file_id).one()
        assert batch.status == "done"
        assert session.query(DispatchItem).filter(
            DispatchItem.batch_id == batch.id,
            DispatchItem.raw_data_id == new_raw.id,
            DispatchItem.category_code == "laptop",
        ).one()
        assert session.query(MatchResult).filter(
            MatchResult.clean_job_id == job_id,
            MatchResult.raw_data_id == new_raw.id,
        ).one()
        old_result = session.query(MatchResult).filter(
            MatchResult.clean_job_id == job_id,
            MatchResult.raw_data_id == old_raw_id,
        ).one()
        assert old_result.match_status == "confirmed"
