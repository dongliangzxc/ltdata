import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.models.database import get_db
from app.models.schemas import (
    CleanJobRecord, Category, UploadFileRecord,
)
from app.api.clean import router as clean_router


@pytest.fixture()
def clean_client(db):
    app = FastAPI()
    app.include_router(clean_router)

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    return TestClient(app)


def _seed_task(db, *, task_name, category_code, platform=None, month=None, status="done"):
    upload = UploadFileRecord(filename=f"{task_name}.xlsx", status="done")
    db.add(upload)
    db.flush()
    cj = CleanJobRecord(
        file_ids=[upload.id],
        task_name=task_name,
        category_code=category_code,
        platform=platform,
        status=status,
    )
    db.add(cj)
    db.commit()
    return cj


def test_clean_tasks_search_by_task_name(db, clean_client):
    db.add(Category(code="camera", name="运动相机"))
    db.add(Category(code="smartlock", name="智能门锁"))
    db.commit()
    t1 = _seed_task(db, task_name="运动相机-京东-202606", category_code="camera", platform="jd")
    t2 = _seed_task(db, task_name="智能门锁-京东-202606", category_code="smartlock", platform="jd")

    resp = clean_client.get("/api/clean/tasks/search", params={"keyword": "相机"})
    assert resp.status_code == 200
    items = resp.json()
    ids = [x["id"] for x in items]
    assert t1.id in ids
    assert t2.id not in ids
    assert items[0]["category_name"] == "运动相机"


def test_clean_tasks_search_excludes_current_and_archived(db, clean_client):
    db.add(Category(code="camera", name="运动相机"))
    db.commit()
    active = _seed_task(db, task_name="活跃任务", category_code="camera", platform="jd", status="done")
    archived = _seed_task(db, task_name="归档任务", category_code="camera", platform="jd", status="archived")
    current = _seed_task(db, task_name="当前任务", category_code="camera", platform="jd", status="done")

    resp = clean_client.get(
        "/api/clean/tasks/search",
        params={"keyword": "任务", "exclude_id": current.id},
    )
    assert resp.status_code == 200
    ids = [x["id"] for x in resp.json()]
    assert active.id in ids
    assert current.id not in ids
    assert archived.id not in ids


def test_clean_tasks_search_by_category_name(db, clean_client):
    db.add(Category(code="camera", name="运动相机"))
    db.commit()
    task = _seed_task(db, task_name="任务A", category_code="camera", platform="jd")

    resp = clean_client.get("/api/clean/tasks/search", params={"keyword": "运动相机"})
    assert resp.status_code == 200
    assert task.id in [x["id"] for x in resp.json()]


def test_clean_tasks_search_by_platform(db, clean_client):
    db.add(Category(code="camera", name="运动相机"))
    db.commit()
    jd_task = _seed_task(db, task_name="任务A", category_code="camera", platform="jd")
    tmall_task = _seed_task(db, task_name="任务B", category_code="camera", platform="tmall")

    resp = clean_client.get("/api/clean/tasks/search", params={"keyword": "jd"})
    ids = [x["id"] for x in resp.json()]
    assert jd_task.id in ids
    assert tmall_task.id not in ids
