from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import export as export_api
from app.core.auth_deps import get_current_user
from app.models.database import Base, get_db
from app.models.schemas import Category, CleanJobRecord, ExportJob


class DummyUser:
    def __init__(self, *, is_admin=0, category_permissions=None):
        self.is_admin = is_admin
        self.category_permissions = category_permissions


class NoopThread:
    def __init__(self, target=None, args=(), daemon=None):
        self.target = target
        self.args = args
        self.daemon = daemon

    def start(self):
        return None


@pytest.fixture(autouse=True)
def disable_export_thread(monkeypatch):
    monkeypatch.setattr(export_api, "threading", SimpleNamespace(Thread=NoopThread))


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture
def client(db):
    app = FastAPI()
    app.include_router(export_api.router)
    current_user = {"value": DummyUser(category_permissions=["headphone"])}

    def override_db():
        yield db

    def override_current_user():
        return current_user["value"]

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_current_user
    test_client = TestClient(app)
    test_client.current_user = current_user
    return test_client


def test_trigger_export_creates_filter_job(client, db):
    response = client.post("/api/export", json={
        "months": [202501, 202502],
        "category_code": "headphone",
        "platforms": ["jd", "tmall"],
        "filename_prefix": "筛选导出",
    })

    assert response.status_code == 200
    body = response.json()
    assert body["job_id"]

    job = db.query(ExportJob).filter(ExportJob.id == body["job_id"]).one()
    assert job.clean_job_id is None
    assert job.months == [202501, 202502]
    assert job.category_code == "headphone"
    assert job.platforms == ["jd", "tmall"]
    assert job.filename_prefix == "筛选导出"


def test_trigger_export_rejects_null_mixed_clean_job_and_filters(client):
    response = client.post("/api/export", json={
        "clean_job_id": None,
        "months": [202501],
        "category_code": "headphone",
        "platforms": ["jd"],
    })

    assert response.status_code == 400
    assert "不能同时" in response.json()["detail"]


@pytest.mark.parametrize("payload, message", [
    ({"months": [], "category_code": "headphone", "platforms": ["jd"]}, "months 不能为空"),
    ({"months": [202501], "category_code": "", "platforms": ["jd"]}, "category_code 不能为空"),
    ({"months": [202501], "category_code": "headphone", "platforms": []}, "platforms 不能为空"),
    ({}, "months 不能为空"),
])
def test_trigger_export_validates_filter_payload(client, payload, message):
    response = client.post("/api/export", json=payload)

    assert response.status_code == 400
    assert message in response.json()["detail"]


def test_trigger_export_keeps_clean_job_compatibility(client, db):
    clean_job = CleanJobRecord(
        category_code="headphone",
        platform="jd",
        source_scope={"months": [202501]},
        status="done",
    )
    db.add(clean_job)
    db.commit()

    response = client.post("/api/export", json={
        "clean_job_id": clean_job.id,
        "filename_prefix": "旧导出",
    })

    assert response.status_code == 200
    job = db.query(ExportJob).filter(ExportJob.id == response.json()["job_id"]).one()
    assert job.clean_job_id == clean_job.id
    assert job.months is None
    assert job.category_code is None
    assert job.platforms is None
    assert job.filename_prefix == "旧导出"


def test_list_jobs_serializes_filter_fields(client, db):
    job = ExportJob(
        clean_job_id=None,
        months=[202501, 202502],
        category_code="headphone",
        platforms=["jd", "tmall"],
        filename_prefix="筛选导出",
        status="done",
    )
    db.add(job)
    db.commit()

    response = client.get("/api/export/jobs")

    assert response.status_code == 200
    body = response.json()
    assert body["data"][0]["months"] == [202501, 202502]
    assert body["data"][0]["category_code"] == "headphone"
    assert body["data"][0]["platforms"] == ["jd", "tmall"]


def test_export_filters_include_reviewing_clean_jobs(client, db):
    db.add(Category(code="headphone", name="耳机"))
    db.add(CleanJobRecord(
        category_code="headphone",
        platform="jd",
        source_scope={"months": [202501]},
        status="reviewing",
    ))
    db.commit()

    response = client.get("/api/export/filters")

    assert response.status_code == 200
    assert response.json() == {
        "months": [202501],
        "platforms": ["jd"],
        "categories": [{"code": "headphone", "name": "耳机"}],
    }


def test_export_filters_are_scoped_by_category_permissions(client, db):
    db.add_all([
        Category(code="headphone", name="耳机"),
        Category(code="projector", name="投影"),
        CleanJobRecord(
            category_code="headphone",
            platform="jd",
            source_scope={"months": [202501]},
            status="reviewing",
        ),
        CleanJobRecord(
            category_code="projector",
            platform="tmall",
            source_scope={"months": [202502]},
            status="reviewing",
        ),
    ])
    db.commit()

    response = client.get("/api/export/filters")

    assert response.status_code == 200
    assert response.json() == {
        "months": [202501],
        "platforms": ["jd"],
        "categories": [{"code": "headphone", "name": "耳机"}],
    }


def test_trigger_export_rejects_invisible_category(client):
    response = client.post("/api/export", json={
        "months": [202501],
        "category_code": "projector",
        "platforms": ["jd"],
        "filename_prefix": "越权导出",
    })

    assert response.status_code == 403
    assert response.json()["detail"] == "无权限访问该品类"


def test_list_jobs_filters_invisible_categories(client, db):
    db.add_all([
        ExportJob(
            clean_job_id=None,
            months=[202501],
            category_code="headphone",
            platforms=["jd"],
            filename_prefix="耳机导出",
            status="done",
        ),
        ExportJob(
            clean_job_id=None,
            months=[202502],
            category_code="projector",
            platforms=["tmall"],
            filename_prefix="投影导出",
            status="done",
        ),
    ])
    db.commit()

    response = client.get("/api/export/jobs")

    assert response.status_code == 200
    data = response.json()["data"]
    assert [job["category_code"] for job in data] == ["headphone"]
