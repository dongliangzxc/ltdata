"""Imports cannot overlap; failed master-data writes release every lock."""
from contextlib import contextmanager
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import pymysql
import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError

from app.api import models_api, url_mapping_api
from app.core.auth_deps import get_current_user
from app.models.database import get_db
from app.models.schemas import BrandCategory, BrandRecord, Category, ItemUrlMapping, ModelRecord
from app.services import catalog_import_lock as locks, url_mapping_importer as importer


@pytest.fixture
def client(db, tmp_path, monkeypatch):
    db.add(Category(code="camera", name="监控摄像头"))
    db.commit()
    monkeypatch.setattr(models_api, "UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(url_mapping_api, "UPLOAD_DIR", str(tmp_path))
    (tmp_path / "tmp").mkdir()
    (tmp_path / "tmp" / "lock-test.csv").write_text(
        "platform,item_url,brand_code,model_code\njd,https://item.jd.com/123.html,SMOKE,NEW\n",
    )
    app = FastAPI()
    app.include_router(models_api.router)
    app.include_router(url_mapping_api.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(is_admin=1, category_permissions=[])
    return TestClient(app, raise_server_exceptions=False)


def payload():
    return dict(temp_file_id="lock-test", mapping={}, category_code="camera")


def test_all_model_and_url_import_endpoints_share_one_lock(db, client):
    with locks.catalog_execution_lock(db.get_bind()) as acquired:
        assert acquired
        for module in ("models", "url-mappings"):
            response = client.post(f"/api/{module}/confirm", json=payload())
            assert response.status_code == 409, response.text
            assert response.json()["detail"] == locks.IMPORT_BUSY_MESSAGE
            response = client.post(f"/api/{module}/import", files={"file": ("sample.xlsx", b"invalid")})
            assert response.status_code == 409, response.text
    # No work was started; after the holder exits both confirm routes can run.
    assert db.query(BrandRecord).count() == 0
    assert client.post("/api/models/confirm", json={**payload(), "temp_file_id": "missing"}).status_code == 404
    assert client.post("/api/url-mappings/confirm", json={**payload(), "temp_file_id": "missing"}).status_code == 404


@pytest.mark.parametrize("errno", [1205, 1213, None])
def test_failure_during_auto_model_creation_rolls_back_brands_and_releases_mutex(db, client, monkeypatch, errno):
    insert = importer._insert_missing

    def fail_models(session, model, rows, unique_columns):
        if model is ModelRecord:
            if errno:
                raise OperationalError("INSERT INTO models", {}, pymysql.err.OperationalError(errno, "database locked"))
            raise ValueError("injected model failure")
        return insert(session, model, rows, unique_columns)

    monkeypatch.setattr(importer, "_insert_missing", fail_models)
    response = client.post("/api/url-mappings/confirm", json=payload())
    assert response.status_code == (409 if errno else 500), response.text
    if errno:
        assert "本次导入已回滚" in response.json()["detail"]
        assert "INSERT INTO" not in response.text
    assert db.query(BrandRecord).count() == db.query(BrandCategory).count() == 0
    assert db.query(ModelRecord).count() == db.query(ItemUrlMapping).count() == 0
    with locks.catalog_execution_lock(db.get_bind()) as acquired:
        assert acquired


def test_model_import_failure_rolls_back_and_does_not_block_url_import(db, client, monkeypatch):
    def fail_brand(session, *args):
        session.add(BrandRecord(brand_code="FAILED"))
        session.flush()
        raise OperationalError("INSERT INTO models", {}, pymysql.err.OperationalError(1205, "locked"))

    monkeypatch.setattr(models_api, "_ensure_import_brand", fail_brand)
    response = client.post("/api/models/confirm", json=payload())
    assert response.status_code == 409, response.text
    assert db.query(BrandRecord).count() == 0
    assert client.post("/api/url-mappings/confirm", json=payload()).status_code == 200


def test_catalog_mutex_excludes_another_process(tmp_path):
    url = "sqlite:///" + str(tmp_path / "catalog.db")
    bind = create_engine(url)
    code = ("from sqlalchemy import create_engine; from app.services.catalog_import_lock import catalog_execution_lock; "
            f"e=create_engine({url!r});\nwith catalog_execution_lock(e) as acquired: print(acquired)")
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])}
    with locks.catalog_execution_lock(bind) as acquired:
        assert acquired
        result = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=15)
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "False"
    with locks.catalog_execution_lock(bind) as acquired:
        assert acquired
    bind.dispose()


def fake_mysql(acquired=1, release_error=False, acquire_commit_error=False):
    calls = []

    class Connection:
        invalidated = False
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def execute(self, stmt, params):
            sql = str(stmt)
            calls.append("get" if "GET_LOCK" in sql else "release")
            if "RELEASE_LOCK" in sql and release_error:
                raise RuntimeError("connection lost on release")
            return SimpleNamespace(scalar=lambda: acquired if "GET_LOCK" in sql else 1)
        def commit(self):
            calls.append("lock.commit")
            self.commits = getattr(self, "commits", 0) + 1
            if acquire_commit_error and self.commits == 1:
                raise RuntimeError("acquisition commit failed")
        def rollback(self):
            calls.append("lock.rollback")
        def invalidate(self):
            calls.append("invalidate")
            self.invalidated = True

    bind = SimpleNamespace(dialect=SimpleNamespace(name="mysql"),
                           url=SimpleNamespace(database="test"), connect=Connection)
    db = SimpleNamespace(get_bind=lambda: bind, rollback=lambda: calls.append("work.rollback"))
    return db, bind, calls


def test_mysql_rolls_back_work_before_releasing_lock_and_refreshes_snapshot():
    db, bind, calls = fake_mysql()
    guard = contextmanager(locks.catalog_import_slot)
    with pytest.raises(HTTPException) as error:
        with guard(db):
            assert calls[-1] == "work.rollback"  # authentication snapshot ended
            calls.append("work.write")
            raise OperationalError("INSERT", {}, pymysql.err.OperationalError(1205, "timeout"))
    assert error.value.status_code == 409
    assert calls.index("work.write") < len(calls) - 1
    assert calls[calls.index("release") - 2:] == ["work.rollback", "lock.rollback", "release", "lock.commit"]


@pytest.mark.parametrize("result", [0, None])
def test_mysql_never_releases_an_unowned_lock(result):
    _, bind, calls = fake_mysql(acquired=result)
    if result is None:
        with pytest.raises(HTTPException) as error:
            with locks.catalog_execution_lock(bind):
                pytest.fail("NULL acquisition must not start work")
        assert error.value.status_code == 503
    else:
        with locks.catalog_execution_lock(bind) as acquired:
            assert not acquired
    assert "release" not in calls


def test_mysql_release_failure_discards_connection_instead_of_leaking_pool_lock():
    _, bind, calls = fake_mysql(release_error=True)
    with locks.catalog_execution_lock(bind) as acquired:
        assert acquired
    assert "release" in calls and calls[-1] == "invalidate"


def test_mysql_acquisition_commit_failure_still_releases_owned_lock():
    _, bind, calls = fake_mysql(acquire_commit_error=True)
    with pytest.raises(RuntimeError, match="acquisition commit failed"):
        with locks.catalog_execution_lock(bind):
            pytest.fail("work must not start after a failed acquisition commit")
    assert "release" in calls
