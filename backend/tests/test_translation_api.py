"""Translation API and cache tests."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import translation_api
from app.api.translation_api import router
from app.core.auth_deps import get_current_user
from app.core.config import settings
from app.models.database import Base, get_db
from app.models.schemas import TranslationCache


class DummyUser:
    is_admin = 1
    permissions = []
    category_permissions = []


@pytest.fixture
def client(monkeypatch):
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
    monkeypatch.setattr(settings, "TRANSLATION_ENABLED", True)
    monkeypatch.setattr(settings, "TRANSLATION_PROVIDER", "mock")
    monkeypatch.setattr(settings, "TRANSLATION_TARGET_LANG", "zh-Hans")
    test_client = TestClient(app)
    test_client.Session = Session
    return test_client


def test_status_reports_mock_enabled(client):
    res = client.get("/api/translation/status")
    assert res.status_code == 200
    assert res.json()["enabled"] is True
    assert res.json()["configured"] is True


def test_translate_deduplicates_and_caches(client, monkeypatch):
    calls = []
    original = translation_api.translate_texts

    def fake_translate_texts(db, texts, **kwargs):
        calls.append(list(texts))
        return original(db, texts, **kwargs)

    monkeypatch.setattr(translation_api, "translate_texts", fake_translate_texts)

    res = client.post("/api/translation/translate", json={"texts": ["Hello world", "Hello world"]})
    assert res.status_code == 200, res.text
    payload = res.json()
    assert [item["translated_text"] for item in payload["translations"]] == ["【译】Hello world", "【译】Hello world"]
    assert calls == [["Hello world", "Hello world"]]

    res2 = client.post("/api/translation/translate", json={"texts": ["Hello world"]})
    assert res2.status_code == 200
    assert res2.json()["translations"][0]["translated_text"] == "【译】Hello world"
    assert len(calls) == 2

    with client.Session() as session:
        assert session.query(TranslationCache).count() == 1


def test_translate_returns_empty_when_disabled(client, monkeypatch):
    monkeypatch.setattr(settings, "TRANSLATION_ENABLED", False)
    res = client.post("/api/translation/translate", json={"texts": ["Hello"]})
    assert res.status_code == 200
    assert res.json()["translations"][0]["translated_text"] == ""
