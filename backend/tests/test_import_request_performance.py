import asyncio
import io
import threading
from types import SimpleNamespace

import httpx
import pandas as pd
import pytest
from fastapi import FastAPI, UploadFile
from sqlalchemy import event

from app.api import metadata
from app.core.auth_deps import get_current_user
from app.models.database import get_db
from app.models.schemas import Category, MetadataSpec


def _file(rows):
    data = io.BytesIO()
    pd.DataFrame(rows).to_excel(data, index=False, sheet_name="元数据")
    return UploadFile(file=io.BytesIO(data.getvalue()), filename="metadata.xlsx")


def _row(index, value="old"):
    return {"品类码": "TV", "属性字段名称": f"字段{index}", "字段类型": "文本型", "字段内容实例": value}


def test_metadata_preview_only_resolves_a_repeated_category_once(db):
    db.add(Category(code="TV", name="电视"))
    db.commit()
    statements = []
    listener = lambda conn, cursor, statement, *args: statements.append(statement)
    event.listen(db.bind, "before_cursor_execute", listener)
    try:
        result = metadata.preview_metadata(_file([_row(i) for i in range(1000)]), db, SimpleNamespace(is_admin=1))
    finally:
        event.remove(db.bind, "before_cursor_execute", listener)
    assert result["valid_rows"] == 1000
    assert len([s for s in statements if "FROM categories" in s]) == 2  # resolve + permission scope


def test_metadata_batch_upsert_preserves_last_row_and_reimport(db):
    db.add(Category(code="TV", name="电视"))
    db.commit()
    rows = [_row(i) for i in range(601)] + [_row(0, "last")]
    statements = []
    listener = lambda conn, cursor, statement, *args: statements.append(statement)
    event.listen(db.bind, "before_cursor_execute", listener)
    try:
        result = metadata.import_metadata(_file(rows), db, SimpleNamespace(is_admin=1))
    finally:
        event.remove(db.bind, "before_cursor_execute", listener)
    assert result == {"imported": 602, "upserted": 602}
    assert len([s for s in statements if s.startswith("INSERT INTO metadata_specs")]) == 3
    assert db.query(MetadataSpec).count() == 601
    assert db.query(MetadataSpec).filter_by(spec_name="字段0").one().spec_values == "last"
    metadata.import_metadata(_file([_row(0, "changed")]), db, SimpleNamespace(is_admin=1))
    assert db.query(MetadataSpec).count() == 601
    assert db.query(MetadataSpec).filter_by(spec_name="字段0").one().spec_values == "changed"


def test_metadata_failed_second_batch_rolls_back_first_batch(db):
    db.add(Category(code="TV", name="电视"))
    db.commit()
    calls = 0

    def fail(conn, cursor, statement, *args):
        nonlocal calls
        if statement.startswith("INSERT INTO metadata_specs"):
            calls += 1
            if calls == 2:
                raise RuntimeError("synthetic second batch failure")

    event.listen(db.bind, "before_cursor_execute", fail)
    try:
        with pytest.raises(RuntimeError, match="second batch"):
            metadata.import_metadata(_file([_row(i) for i in range(301)]), db, SimpleNamespace(is_admin=1))
        db.rollback()  # same rollback as the request's session close on exception
    finally:
        event.remove(db.bind, "before_cursor_execute", fail)
    assert db.query(MetadataSpec).count() == 0


def test_slow_metadata_preview_does_not_hold_up_other_requests(db, monkeypatch):
    app = FastAPI()
    app.include_router(metadata.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(is_admin=1)
    app.add_api_route("/probe", lambda: {"ok": True})
    started, release = threading.Event(), threading.Event()
    parse_thread = []

    def slow_parse(content, session):
        parse_thread.append(threading.get_ident())
        started.set()
        assert release.wait(5)
        return {"preview": [], "valid_rows": 0, "total_rows": 0, "errors": [], "warnings": []}

    monkeypatch.setattr(metadata, "_parse_metadata_file", slow_parse)

    async def check():
        loop_thread = threading.get_ident()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            task = asyncio.create_task(client.post("/api/metadata/preview", files={"file": ("t.xlsx", b"test")}))
            try:
                assert await asyncio.to_thread(started.wait, 3)
                assert len(parse_thread) == 1 and parse_thread[0] != loop_thread
                assert not task.done()
                assert (await asyncio.wait_for(client.get("/probe"), 1)).status_code == 200
                assert not release.is_set()
            finally:
                release.set()
            assert (await task).status_code == 200

    asyncio.run(check())


def test_slow_authentication_keeps_its_session_in_a_worker_and_health_responds(monkeypatch):
    import app.main as main
    started, release = threading.Event(), threading.Event()
    session_threads = []

    class FakeSession:
        def __init__(self):
            session_threads.append(threading.get_ident())

        def query(self, *args):
            session_threads.append(threading.get_ident())
            return self

        def filter(self, *args):
            return self

        def first(self):
            started.set()
            assert release.wait(5)
            return SimpleNamespace(is_active=1, is_admin=1, permissions=[])

        def close(self):
            session_threads.append(threading.get_ident())

    monkeypatch.setattr(main, "SessionLocal", FakeSession)
    monkeypatch.setattr(main, "verify_token", lambda token: "admin")

    async def check():
        loop_thread = threading.get_ident()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://test") as client:
            task = asyncio.create_task(client.get("/api/unregistered-probe", headers={"Authorization": "Bearer test"}))
            try:
                assert await asyncio.to_thread(started.wait, 3)
                assert not task.done()
                assert (await asyncio.wait_for(client.get("/health"), 1)).status_code == 200
                assert not release.is_set()
            finally:
                release.set()
            assert (await task).status_code == 404
        assert len(set(session_threads)) == 1 and session_threads[0] != loop_thread

    asyncio.run(check())
