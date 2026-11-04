"""品类清洗扩展字段（智能等）单元测试。"""
import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.categories_api import router as categories_router
from app.api.match_api import router as match_router
from app.core.auth_deps import get_current_user
from app.core.config import settings
from app.models.database import get_db
from app.models.schemas import (
    Category,
    CategoryCustomField,
    CleanJobRecord,
    MatchResult,
    ModelRecord,
    RawDataRecord,
)
from app.services.custom_fields import (
    get_review_fields,
    resolve_effective_values,
    set_manual_value,
)
from app.services.exporter import export_match_job


class DummyUser:
    def __init__(self, *, is_admin=1, category_permissions=None):
        self.is_admin = is_admin
        self.category_permissions = category_permissions


@pytest.fixture(autouse=True)
def export_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "EXPORT_DIR", str(tmp_path))


@pytest.fixture
def api_client(db):
    app = FastAPI()
    app.include_router(categories_router)
    app.include_router(match_router)

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: DummyUser()
    return TestClient(app)


def _seed(db, item_name="智能投影仪 4K"):
    cat = Category(code="projector", name="投影仪")
    db.add(cat)
    db.flush()
    field = CategoryCustomField(
        category_code="projector",
        field_key="is_smart",
        field_label="智能",
        field_type="enum",
        options="是,否",
        default_value="否",
        auto_keywords="智能",
        auto_value="是",
        required=0,
        export=1,
        sort_order=1,
        is_active=1,
    )
    db.add(field)
    model = ModelRecord(
        brand_code="brand-a",
        model_code="P1",
        category_code="projector",
        brand_name="品牌A",
        model_name="P1",
    )
    db.add(model)
    db.flush()
    raw = RawDataRecord(
        file_id=1,
        platform="jd",
        month=202501,
        item_id="item-1",
        item_name=item_name,
        brand_raw="品牌A",
        brand_std="brand-a",
        sales_qty=10,
        sales_amount=100.0,
        price=10.0,
    )
    db.add(raw)
    db.flush()
    job = CleanJobRecord(file_ids=[1], status="reviewing", category_code="projector")
    db.add(job)
    db.flush()
    mr = MatchResult(
        clean_job_id=job.id,
        raw_data_id=raw.id,
        model_id=model.id,
        match_status="matched",
        matched_by="auto",
        match_source="s1",
        is_disabled=0,
    )
    db.add(mr)
    db.commit()
    return job, raw, mr, model, field


def test_resolve_auto_and_default_values(db):
    job, raw, mr, _model, _field = _seed(db)
    values = resolve_effective_values(db, [{
        "match_result_id": mr.id,
        "category_code": "projector",
        "item_name": raw.item_name,
    }])
    assert values[mr.id]["is_smart"] == {"value": "是", "source": "auto"}

    raw.item_name = "普通投影仪"
    values = resolve_effective_values(db, [{
        "match_result_id": mr.id,
        "category_code": "projector",
        "item_name": raw.item_name,
    }])
    assert values[mr.id]["is_smart"] == {"value": "否", "source": "default"}


def test_manual_value_overrides_and_can_be_cleared(db):
    _job, raw, mr, _model, _field = _seed(db)
    set_manual_value(db, mr, "projector", "is_smart", "否")
    fields = get_review_fields(db, mr, "projector", raw.item_name)
    assert fields[0]["value"] == "否"
    assert fields[0]["source"] == "manual"

    set_manual_value(db, mr, "projector", "is_smart", None)
    fields = get_review_fields(db, mr, "projector", raw.item_name)
    assert fields[0]["value"] == "是"
    assert fields[0]["source"] == "auto"


def test_manual_value_rejects_invalid_enum(db):
    _job, _raw, mr, _model, _field = _seed(db)
    with pytest.raises(ValueError):
        set_manual_value(db, mr, "projector", "is_smart", "可能")


def test_review_detail_and_patch_custom_field(api_client, db):
    _job, raw, mr, _model, _field = _seed(db)

    detail = api_client.get(f"/api/match/items/{mr.id}/review-detail")
    assert detail.status_code == 200
    custom = detail.json()["custom_fields"]
    assert custom[0]["field_key"] == "is_smart"
    assert custom[0]["field_label"] == "智能"
    assert custom[0]["value"] == "是"
    assert custom[0]["source"] == "auto"

    updated = api_client.patch(
        f"/api/match/items/{mr.id}/custom-fields/is_smart",
        json={"value": "否"},
    )
    assert updated.status_code == 200
    assert updated.json()["custom_fields"][0]["value"] == "否"
    assert updated.json()["custom_fields"][0]["source"] == "manual"


def test_custom_field_config_crud(api_client, db):
    db.add(Category(code="projector", name="投影仪"))
    db.commit()

    created = api_client.post("/api/categories/custom-fields", json={
        "category_code": "projector",
        "field_key": "is_smart",
        "field_label": "智能",
        "field_type": "enum",
        "options": "是,否",
        "default_value": "否",
        "auto_keywords": "智能",
        "auto_value": "是",
        "required": False,
        "export": True,
        "sort_order": 1,
        "is_active": True,
    })
    assert created.status_code == 201
    field_id = created.json()["id"]

    listed = api_client.get("/api/categories/custom-fields", params={"category_code": "projector"})
    assert listed.status_code == 200
    assert listed.json()[0]["field_label"] == "智能"

    patched = api_client.patch(f"/api/categories/custom-fields/{field_id}", json={"default_value": "是"})
    assert patched.status_code == 200
    assert patched.json()["default_value"] == "是"

    deleted = api_client.delete(f"/api/categories/custom-fields/{field_id}")
    assert deleted.status_code == 204


def test_export_includes_custom_field_column(db):
    job, _raw, _mr, _model, _field = _seed(db)
    result = export_match_job(db, job.id)
    assert result
    sheet = pd.read_excel(result[0]["path"], sheet_name="投影仪-已处理")
    assert "智能" in sheet.columns
    assert sheet["智能"].iloc[0] == "是"
    cols = list(sheet.columns)
    assert cols.index("智能") == cols.index("型号") + 1
