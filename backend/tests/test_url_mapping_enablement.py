"""Category/month-scoped URL enablement and its effect on matching."""
import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Query as ORMQuery, Session

from app.models.schemas import ItemUrlMapping, MatchResult, ModelRecord
from app.services import matcher
from tests.test_url_mappings_api_permissions import client, seed_data
from tests.test_url_mapping_filtered_delete import filtered_client, seed_many
from tests.test_url_mapping_import_batches import confirm, row
from tests.test_matcher_url_batches import _job, _model, enabled_cache
from tests.test_historical_matcher import _seed, _add_history


def test_migration_keeps_existing_links_enabled(monkeypatch):
    path = Path(__file__).resolve().parents[1] / "alembic/versions/p80a1b2c3d4e5_url_mapping_enabled.py"
    spec = importlib.util.spec_from_file_location("url_enablement_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE item_url_mappings (id INTEGER PRIMARY KEY, item_id VARCHAR(100))"))
        connection.execute(text("INSERT INTO item_url_mappings (item_id) VALUES ('old')"))
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
        migration.upgrade()
        connection.execute(text("INSERT INTO item_url_mappings (item_id) VALUES ('new')"))
        assert connection.execute(text("SELECT item_id, is_enabled FROM item_url_mappings ORDER BY id")).all() == [
            ("old", 1), ("new", 1),
        ]
        migration.downgrade()
        assert "is_enabled" not in {col["name"] for col in inspect(connection).get_columns("item_url_mappings")}
        assert connection.execute(text("SELECT COUNT(*) FROM item_url_mappings")).scalar_one() == 2
    engine.dispose()


def test_month_range_is_inclusive_and_crosses_years(client):
    with client.Session() as db:
        seed_data(db)
        db.add_all(ItemUrlMapping(platform="jd", item_id=f"month-{month}", brand_code="SONY",
                                  category_code="TV", data_year=month // 100, data_month=month % 100)
                   for month in (202511, 202512, 202601, 202602))
        db.commit()
    scope = {"category_code": "TV", "start_month": 202512, "end_month": 202601}
    listed = client.get("/api/url-mappings", params=scope).json()
    assert {item["item_id"] for item in listed["items"]} == {"month-202512", "month-202601"}
    assert all(item["is_enabled"] is True for item in listed["items"])
    assert client.get("/api/url-mappings/category-count", params=scope).json()["count"] == 2
    response = client.post("/api/url-mappings/bulk-status", json={**scope, "is_enabled": False})
    assert response.status_code == 200
    assert response.json()["updated"] == 2
    assert client.get("/api/url-mappings", params={**scope, "enabled": True}).json()["total"] == 0
    assert client.get("/api/url-mappings", params={**scope, "enabled": False}).json()["total"] == 2
    with client.Session() as db:
        assert db.query(ItemUrlMapping).filter_by(is_enabled=0).count() == 2
        # Undated links and out-of-range months are left alone.
        assert db.query(ItemUrlMapping).filter_by(item_id="tv-item").one().is_enabled == 1


@pytest.mark.parametrize("category", ["TV", "AC"])
def test_same_bulk_controls_work_for_every_category(client, category):
    client.current_user.is_admin = 1
    with client.Session() as db:
        seed_data(db)
        db.commit()
    scope = {"category_code": category}
    result = client.post("/api/url-mappings/bulk-status", json={**scope, "is_enabled": False})
    assert result.status_code == 200
    assert result.json()["updated"] == 1
    listed = client.get("/api/url-mappings", params=scope).json()["items"]
    assert len(listed) == 1 and listed[0]["is_enabled"] is False
    with client.Session() as db:
        assert db.query(ItemUrlMapping).filter_by(is_enabled=1).count() == 1
        assert db.query(ModelRecord).count() == 2


def test_status_changes_respect_all_filters_selection_and_permissions(filtered_client):
    client = filtered_client
    with client.Session() as db:
        ids = {item.item_id: item.id for item in db.query(ItemUrlMapping).all()}
    scope = {"category_code": "TV", "platform": "jd", "brand": "sony",
             "start_month": 202610, "end_month": 202610,
             "exclude_ids": [ids["placeholder"], ids["ac-item"], 999999]}
    result = client.post("/api/url-mappings/bulk-status", json={**scope, "is_enabled": False})
    assert result.status_code == 200
    assert result.json()["matched"] == result.json()["updated"] == 1
    with client.Session() as db:
        assert {r.item_id for r in db.query(ItemUrlMapping).filter_by(is_enabled=0)} == {"target"}
    assert client.post("/api/url-mappings/bulk-status", json={**scope, "is_enabled": False}).json()["updated"] == 0
    assert client.post("/api/url-mappings/bulk-status", json={**scope, "is_enabled": True}).json()["updated"] == 1


@pytest.mark.parametrize("selection", [{"include_ids": []}, {"include_ids": [999999]}])
def test_empty_selection_does_not_change_other_links(filtered_client, selection):
    result = filtered_client.post("/api/url-mappings/bulk-status", json={
        "category_code": "TV", "is_enabled": False, **selection,
    })
    assert result.status_code == 200 and result.json()["updated"] == 0
    with filtered_client.Session() as db:
        assert db.query(ItemUrlMapping).filter_by(is_enabled=0).count() == 0


@pytest.mark.parametrize("payload, status", [
    ({"category_code": "AC", "is_enabled": False}, 403),
    ({"is_enabled": False}, 422),
    ({"category_code": "TV"}, 422),
    ({"category_code": "TV", "is_enabled": False, "start_month": 202613}, 422),
    ({"category_code": "TV", "is_enabled": False, "start_month": 202610, "end_month": 202609}, 422),
    ({"category_code": "TV", "is_enabled": False, "include_ids": [1], "exclude_ids": [2]}, 422),
])
def test_invalid_scope_and_invisible_categories_cannot_be_updated(filtered_client, payload, status):
    assert filtered_client.post("/api/url-mappings/bulk-status", json=payload).status_code == status
    with filtered_client.Session() as db:
        assert db.query(ItemUrlMapping).filter_by(is_enabled=0).count() == 0


def test_bulk_status_covers_every_page_and_rolls_back_on_failure(client, monkeypatch):
    seed_many(client)
    scope = {"category_code": "TV", "keyword": "batch-", "is_enabled": False}
    update = ORMQuery.update
    calls = 0

    def failing_update(self, *args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("second chunk failed")
        return update(self, *args, **kwargs)

    with monkeypatch.context() as context:
        context.setattr(ORMQuery, "update", failing_update)
        with pytest.raises(RuntimeError, match="second chunk"):
            client.post("/api/url-mappings/bulk-status", json=scope)
    with client.Session() as db:
        assert db.query(ItemUrlMapping).filter_by(is_enabled=0).count() == 0
    result = client.post("/api/url-mappings/bulk-status", json=scope)
    assert result.status_code == 200 and result.json()["updated"] == 1005
    with client.Session() as db:
        assert db.query(ItemUrlMapping).filter_by(is_enabled=0).count() == 1005
        assert db.query(ItemUrlMapping).filter_by(item_id="tv-item").one().is_enabled == 1


def test_editing_or_importing_does_not_silently_reenable_disabled_links(db, confirm):
    confirm([row()], data_year=2026, data_month=9)
    mapping = db.query(ItemUrlMapping).one()
    mapping.is_enabled = 0
    db.commit()
    confirm([row()], data_year=2026, data_month=10)
    db.expire_all()
    saved = db.query(ItemUrlMapping).one()
    assert (saved.data_year, saved.data_month, saved.is_enabled) == (2026, 10, 0)


def test_manual_mapping_month_can_be_added_without_changing_status(client):
    with client.Session() as db:
        tv, _ = seed_data(db)
        db.commit()
        model_id = tv.id
    payload = {"platform": "jd", "item_id": "dated-manual", "model_id": model_id,
               "data_year": 2026, "data_month": 10}
    created = client.post("/api/url-mappings", json=payload)
    assert created.status_code == 200
    assert created.json()["is_enabled"] is True
    mapping_id = created.json()["id"]
    client.post("/api/url-mappings/bulk-status", json={"category_code": "TV", "include_ids": [mapping_id], "is_enabled": False})
    payload["data_month"] = 11
    edited = client.put(f"/api/url-mappings/{mapping_id}", json=payload)
    assert edited.status_code == 200
    assert edited.json()["is_enabled"] is False
    assert edited.json()["data_month"] == 11


@pytest.mark.parametrize("single", [False, True])
def test_disabled_url_is_not_used_by_either_matching_entry_point(db, single):
    model = _model(db)
    db.add(ItemUrlMapping(platform="jd", item_id="123", model_id=model.id, brand_code="SONY", is_enabled=0))
    job_id, result_id = _job(db, item_url="https://item.jd.com/123.html")
    if single:
        result = matcher.run_match_for_result(db, result_id, commit=False)
    else:
        matcher.run_match(db, job_id, commit=False)
        result = db.query(MatchResult).filter_by(clean_job_id=job_id).one()
    assert result.match_status == "pending"
    assert result.model_id is None
    ctx = matcher._load_match_context(db, "headphone", [("jd", "123")])
    assert ctx.url_map == ctx.url_brand_map == {}


def test_status_reads_bypass_warm_worker_cache(db, enabled_cache, monkeypatch):
    model = _model(db)
    db.add(ItemUrlMapping(platform="jd", item_id="123", model_id=model.id, brand_code="SONY"))
    db.commit()
    loads = []
    original = matcher._load_url_mapping_rows

    def load(*args):
        loads.append(True)
        return original(*args)

    monkeypatch.setattr(matcher, "_load_url_mapping_rows", load)
    keys = [("jd", "123")]
    assert matcher._build_url_maps(db, {model.id}, keys)[0] == {("jd", "123"): model.id}
    db.commit()
    for enabled in (False, True):
        with Session(db.get_bind()) as api_db:
            api_db.query(ItemUrlMapping).update({"is_enabled": int(enabled)})
            api_db.commit()
        url_map, brand_map = matcher._build_url_maps(db, {model.id}, keys)
        assert url_map == ({("jd", "123"): model.id} if enabled else {})
        assert brand_map == {}
        db.commit()
    assert len(loads) == 1, "Status toggles must work even when a worker reuses its raw mapping cache"


def test_disabling_mapping_does_not_change_historical_matching_or_existing_results(db):
    job_id, model_id = _seed(db, item_id="12345", month=202605)
    _add_history(db, item_id="12345", model_id=model_id)
    db.add(ItemUrlMapping(platform="jd", item_id="12345", model_id=model_id, is_enabled=0))
    db.commit()
    matcher.run_match(db, job_id)
    result = db.query(MatchResult).filter_by(clean_job_id=job_id).one()
    assert result.match_source == "historical" and result.model_id == model_id
    db.query(ItemUrlMapping).update({"is_enabled": 1})
    db.commit()
    db.refresh(result)
    assert result.match_source == "historical", "Toggling mappings must not rewrite existing results"
