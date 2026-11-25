"""筛选列表、计数与跨页删除使用相同的范围，并保留范围外的数据。"""
import pytest
from sqlalchemy.orm import Query as ORMQuery

from tests.test_url_mappings_api_permissions import client, seed_data
from app.models.schemas import Category, ItemUrlMapping, ModelRecord


@pytest.fixture
def filtered_client(client):
    with client.Session() as db:
        tv, ac = seed_data(db)
        db.add(ModelRecord(brand_code="JBL", brand_name="杰宝", model_code="BAR", category_code="TV"))
        db.flush()
        jbl = db.query(ModelRecord).filter_by(brand_code="JBL").one()
        rows = [
            ("target", "jd", tv.id, "STALE", "TV", 2026, 10),
            ("other-platform", "tmall", tv.id, "SONY", "TV", 2026, 10),
            ("other-brand", "jd", jbl.id, "JBL", "TV", 2026, 10),
            ("other-year", "jd", tv.id, "SONY", "TV", 2025, 10),
            ("other-month", "jd", tv.id, "SONY", "TV", 2026, 9),
            ("placeholder", "jd", None, "SONY", "TV", 2026, 10),
            # 显示为 AC，不能因型号归属 TV 被计入或删除。
            ("record-ac", "jd", tv.id, "SONY", "AC", 2026, 10),
            # 显示为 TV，应以记录品类而非型号品类判断权限及删除范围。
            ("record-tv", "jd", ac.id, "GREE", "TV", 2026, 10),
        ]
        db.add_all(ItemUrlMapping(
            item_id=item_id, platform=platform, model_id=model_id, brand_code=brand,
            category_code=category, data_year=year, data_month=month, source="manual",
        ) for item_id, platform, model_id, brand, category, year, month in rows)
        db.commit()
    return client


@pytest.mark.parametrize("filters", [
    {"platform": "jd"},
    {"brand": "sony"},
    {"brand": "索尼"},
    {"keyword": "placeholder"},
    {"keyword": "SONY"},
    {"keyword": "索尼"},
    {"keyword": "TV-1"},
    {"year": 2026},
    {"month": 10},
    {"platform": "jd", "brand": "sony", "year": 2026, "month": 10},
    {"platform": "jd", "brand": "索尼", "keyword": "target", "year": 2026, "month": 10},
    {"brand": "STALE"},
    {"keyword": "no-such-item"},
])
def test_filtered_delete_matches_list_and_count(filtered_client, filters):
    client = filtered_client
    params = {"category_code": "TV", **filters}
    listed = client.get("/api/url-mappings", params={**params, "page_size": 200})
    preview = client.get("/api/url-mappings/category-count", params=params)
    assert listed.status_code == preview.status_code == 200
    ids = {row["id"] for row in listed.json()["items"]}
    count = preview.json()["count"]
    assert count == listed.json()["total"] == len(ids)
    with client.Session() as db:
        original_ids = {row.id for row in db.query(ItemUrlMapping).all()}
        original_models = db.query(ModelRecord).count()

    result = client.post("/api/url-mappings/bulk-delete", json={**params, "expected_count": count})
    assert result.status_code == 200
    assert result.json()["deleted"] == count
    with client.Session() as db:
        assert {row.id for row in db.query(ItemUrlMapping).all()} == original_ids - ids
        assert db.query(ModelRecord).count() == original_models


def test_combined_filters_match_known_rows(filtered_client):
    params = {"category_code": "TV", "platform": "jd", "brand": "sony", "year": 2026, "month": 10}
    rows = filtered_client.get("/api/url-mappings", params=params).json()["items"]
    assert {row["item_id"] for row in rows} == {"target", "placeholder"}
    params["brand"] = "索尼"
    rows = filtered_client.get("/api/url-mappings", params=params).json()["items"]
    assert {row["item_id"] for row in rows} == {"target"}


def test_hidden_empty_mapping_is_not_deleted(client):
    with client.Session() as db:
        seed_data(db)
        db.add(ItemUrlMapping(platform="jd", item_id="empty", category_code="TV"))
        db.commit()
    params = {"category_code": "TV"}
    assert client.get("/api/url-mappings", params=params).json()["total"] == 1
    assert client.get("/api/url-mappings/category-count", params=params).json()["count"] == 1
    assert client.post("/api/url-mappings/bulk-delete", json={**params, "expected_count": 1}).json()["deleted"] == 1
    with client.Session() as db:
        assert db.query(ItemUrlMapping).filter_by(item_id="empty").one()


def test_effective_category_prevents_cross_category_deletion(filtered_client):
    client = filtered_client
    listed = client.get("/api/url-mappings", params={"category_code": "TV"}).json()["items"]
    assert "record-ac" not in {row["item_id"] for row in listed}
    assert "record-tv" in {row["item_id"] for row in listed}
    client.post("/api/url-mappings/bulk-delete", json={"category_code": "TV"})
    with client.Session() as db:
        assert db.query(ItemUrlMapping).filter_by(item_id="record-ac").one()
        assert db.query(ItemUrlMapping).filter_by(item_id="record-tv").first() is None


def test_legacy_headphone_fallback_respects_explicit_record_category(client):
    client.current_user.is_admin = 1
    with client.Session() as db:
        seed_data(db)
        db.add(Category(code="headphone", name="耳机"))
        db.add_all([
            ItemUrlMapping(platform="jd", item_id="legacy", brand_code="SONY"),
            ItemUrlMapping(platform="jd", item_id="explicit-tv", brand_code="SONY", category_code="TV"),
        ])
        db.commit()
    params = {"category_code": "headphone", "brand": "SONY"}
    assert client.get("/api/url-mappings/category-count", params=params).json()["count"] == 1
    rows = client.get("/api/url-mappings", params=params).json()["items"]
    assert [row["item_id"] for row in rows] == ["legacy"]
    result = client.post("/api/url-mappings/bulk-delete", json={**params, "expected_count": 1})
    assert result.json()["deleted"] == 1
    with client.Session() as db:
        assert db.query(ItemUrlMapping).filter_by(item_id="explicit-tv").one()


def test_filtered_delete_blocks_invisible_category_and_missing_scope(filtered_client):
    client = filtered_client
    for suffix in ["", "/category-count"]:
        result = client.get("/api/url-mappings" + suffix, params={"category_code": "AC", "brand": "GREE"})
        assert result.status_code == (403 if suffix else 200)
        if not suffix:
            assert result.json()["total"] == 0
    for payload, status in [
        ({"category_code": "AC", "platform": "jd"}, 403),
        ({"platform": "jd"}, 422),
        ({"category_code": " "}, 422),
        ({"category_code": "TV", "brand_code": "SONY"}, 422),
        ({"category_code": "TV", "month": 13}, 422),
    ]:
        assert client.post("/api/url-mappings/bulk-delete", json=payload).status_code == status
    with client.Session() as db:
        assert db.query(ItemUrlMapping).count() == 10


def test_changed_count_requires_new_confirmation(filtered_client):
    params = {"category_code": "TV", "platform": "jd"}
    preview = filtered_client.get("/api/url-mappings/category-count", params=params).json()["count"]
    with filtered_client.Session() as db:
        db.add(ItemUrlMapping(platform="jd", item_id="new-item", brand_code="SONY", category_code="TV"))
        db.commit()
        total = db.query(ItemUrlMapping).count()
    response = filtered_client.post("/api/url-mappings/bulk-delete", json={**params, "expected_count": preview})
    assert response.status_code == 409
    with filtered_client.Session() as db:
        assert db.query(ItemUrlMapping).count() == total


def seed_many(client):
    with client.Session() as db:
        seed_data(db)
        db.add_all(ItemUrlMapping(
            platform="jd", item_id=f"batch-{i}", brand_code="SONY", category_code="TV", source="manual",
        ) for i in range(1005))
        db.commit()


def test_delete_all_pages_and_chunks(client):
    seed_many(client)
    params = {"category_code": "TV", "keyword": "batch-"}
    listed = client.get("/api/url-mappings", params=params).json()
    assert len(listed["items"]) == 20
    assert listed["total"] == 1005
    assert client.get("/api/url-mappings/category-count", params=params).json()["count"] == 1005
    response = client.post("/api/url-mappings/bulk-delete", json={**params, "expected_count": 1005})
    assert response.status_code == 200
    assert response.json()["deleted"] == 1005
    with client.Session() as db:
        assert {row.item_id for row in db.query(ItemUrlMapping).all()} == {"tv-item", "ac-item"}


def test_partial_chunk_failure_rolls_back_all_deletes(client, monkeypatch):
    seed_many(client)
    original_delete = ORMQuery.delete
    calls = 0

    def failing_delete(self, *args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("模拟第二批失败")
        return original_delete(self, *args, **kwargs)

    monkeypatch.setattr(ORMQuery, "delete", failing_delete)
    with pytest.raises(RuntimeError, match="模拟第二批失败"):
        client.post("/api/url-mappings/bulk-delete", json={"category_code": "TV", "keyword": "batch-"})
    with client.Session() as db:
        assert db.query(ItemUrlMapping).count() == 1007


def test_default_all_with_exclusions_across_pages(client):
    seed_many(client)
    filters = {"category_code": "TV", "keyword": "batch-"}
    first = client.get("/api/url-mappings", params=filters).json()["items"]
    second = client.get("/api/url-mappings", params={**filters, "page": 2}).json()["items"]
    keep_ids = [first[0]["id"], second[0]["id"]]
    # 已失效或不属于当前范围的排除 ID 不应被错误地从数量中扣除。
    with client.Session() as db:
        outside_id = db.query(ItemUrlMapping).filter_by(item_id="ac-item").one().id
    excluded = [*keep_ids, keep_ids[0], outside_id, 999999]
    preview = client.get("/api/url-mappings/category-count", params={**filters, "exclude_ids": excluded})
    assert preview.status_code == 200
    assert preview.json()["count"] == 1003
    result = client.post("/api/url-mappings/bulk-delete", json={**filters, "exclude_ids": excluded, "expected_count": 1003})
    assert result.status_code == 200
    assert result.json()["deleted"] == 1003
    with client.Session() as db:
        assert db.query(ItemUrlMapping).count() == 4
        assert {row.id for row in db.query(ItemUrlMapping).filter(ItemUrlMapping.item_id.like("batch-%")).all()} == set(keep_ids)


def test_explicit_selection_is_intersected_with_filters_and_permissions(filtered_client):
    client = filtered_client
    with client.Session() as db:
        ids = {row.item_id: row.id for row in db.query(ItemUrlMapping).all()}
    chosen = [ids["target"], ids["placeholder"], ids["other-platform"], ids["other-brand"], ids["ac-item"], 999999, ids["target"]]
    filters = {"category_code": "TV", "platform": "jd", "brand": "sony"}
    preview = client.get("/api/url-mappings/category-count", params={**filters, "include_ids": chosen})
    assert preview.status_code == 200
    assert preview.json()["count"] == 2
    response = client.post("/api/url-mappings/bulk-delete", json={**filters, "include_ids": chosen, "expected_count": 2})
    assert response.status_code == 200
    assert response.json()["deleted"] == 2
    with client.Session() as db:
        remaining = {row.item_id for row in db.query(ItemUrlMapping).all()}
        assert remaining == set(ids) - {"target", "placeholder"}


def test_empty_explicit_selection_deletes_nothing(filtered_client):
    response = filtered_client.post("/api/url-mappings/bulk-delete", json={"category_code": "TV", "include_ids": [], "expected_count": 0})
    assert response.status_code == 200
    assert response.json()["deleted"] == 0
    with filtered_client.Session() as db:
        assert db.query(ItemUrlMapping).count() == 10


@pytest.mark.parametrize("selection", [
    {"include_ids": [0]},
    {"exclude_ids": [-1]},
    {"include_ids": ["invalid"]},
    {"include_ids": [1], "exclude_ids": [2]},
    {"include_ids": [], "exclude_ids": [2]},
])
def test_invalid_or_ambiguous_selection_rejected(filtered_client, selection):
    response = filtered_client.post("/api/url-mappings/bulk-delete", json={"category_code": "TV", **selection})
    assert response.status_code == 422
    with filtered_client.Session() as db:
        assert db.query(ItemUrlMapping).count() == 10


def test_selection_preview_and_delete_both_reject_invisible_category(filtered_client):
    with filtered_client.Session() as db:
        outside_id = db.query(ItemUrlMapping).filter_by(item_id="ac-item").one().id
    params = {"category_code": "AC", "include_ids": [outside_id]}
    assert filtered_client.get("/api/url-mappings/category-count", params=params).status_code == 403
    assert filtered_client.post("/api/url-mappings/bulk-delete", json=params).status_code == 403


def test_selection_count_change_requires_confirmation(filtered_client):
    with filtered_client.Session() as db:
        target = db.query(ItemUrlMapping).filter_by(item_id="target").one().id
    filters = {"category_code": "TV", "include_ids": [target]}
    assert filtered_client.get("/api/url-mappings/category-count", params=filters).json()["count"] == 1
    with filtered_client.Session() as db:
        db.query(ItemUrlMapping).filter_by(id=target).delete()
        db.commit()
    response = filtered_client.post("/api/url-mappings/bulk-delete", json={**filters, "expected_count": 1})
    assert response.status_code == 409
    with filtered_client.Session() as db:
        assert db.query(ItemUrlMapping).count() == 9
