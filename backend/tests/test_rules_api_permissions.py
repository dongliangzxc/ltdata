from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.correction_rules_api import router as correction_router
from app.api.rules_api import router as rules_router
from app.core.auth_deps import get_current_user
from app.models.database import Base, get_db
from app.models.schemas import AttrRule, Category, CorrectionRule, InterventionRule, ModelRecord, NoiseWord


class DummyUser:
    def __init__(self, *, is_admin=0, category_permissions=None):
        self.is_admin = is_admin
        self.category_permissions = category_permissions


def _correction_rule(category_code: str, *, name: str | None = None, priority: int = 1) -> CorrectionRule:
    return CorrectionRule(
        name=name or f"{category_code} rule",
        category_code=category_code,
        target="sales_qty",
        rule_type="multiply",
        value=1.2,
        priority=priority,
        is_active=1,
    )


def _correction_rule_payload(category_code: str, *, name: str | None = None) -> dict:
    return {
        "name": name or f"{category_code} rule",
        "category_code": category_code,
        "target": "sales_qty",
        "rule_type": "multiply",
        "value": 1.2,
        "priority": 1,
        "is_active": 1,
    }


def _client():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    current_user = {"value": DummyUser(category_permissions=["TV"])}

    app = FastAPI()
    app.include_router(rules_router)
    app.include_router(correction_router)

    def override_db():
        yield db

    def override_current_user():
        return current_user["value"]

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_current_user
    test_client = TestClient(app)
    test_client.db = db
    test_client.current_user = current_user
    return test_client


def _seed_categories(db):
    db.add_all([
        Category(code="TV", name="电视", sort_order=1),
        Category(code="projector", name="投影", sort_order=2),
    ])
    db.commit()


def test_intervention_rules_filter_by_category_permissions():
    client = _client()
    db = client.db
    _seed_categories(db)
    db.add_all([
        InterventionRule(name="tv rule", category_code="TV", action="filter", conditions={}, priority=1),
        InterventionRule(name="projector rule", category_code="projector", action="filter", conditions={}, priority=2),
    ])
    db.commit()

    response = client.get("/api/rules/intervention-rules")

    assert response.status_code == 200
    assert [rule["category_code"] for rule in response.json()] == ["TV"]


def test_intervention_rule_create_rejects_invisible_category():
    client = _client()
    _seed_categories(client.db)

    response = client.post("/api/rules/intervention-rules", json={
        "name": "projector rule",
        "category_code": "projector",
        "action": "filter",
        "priority": 1,
        "conditions": {},
    })

    assert response.status_code == 403
    assert response.json()["detail"] == "无权限访问该品类"


def test_noise_words_filter_by_category_permissions():
    client = _client()
    db = client.db
    _seed_categories(db)
    db.add_all([
        NoiseWord(keyword="tv noise", match_field="item_name", category_code="TV"),
        NoiseWord(keyword="projector noise", match_field="item_name", category_code="projector"),
    ])
    db.commit()

    response = client.get("/api/rules/noise-words")

    assert response.status_code == 200
    assert [row["category_code"] for row in response.json()] == ["TV"]


def test_noise_word_create_rejects_invisible_category():
    client = _client()
    _seed_categories(client.db)

    response = client.post("/api/rules/noise-words", json={
        "keyword": "projector noise",
        "match_field": "item_name",
        "category_code": "projector",
    })

    assert response.status_code == 403
    assert response.json()["detail"] == "无权限访问该品类"


def test_attr_rules_filter_by_category_permissions():
    client = _client()
    db = client.db
    _seed_categories(db)
    db.add_all([
        AttrRule(keyword="tv", attr_name="size", attr_value="55", category_code="TV", priority=1),
        AttrRule(keyword="projector", attr_name="lumens", attr_value="1000", category_code="projector", priority=2),
    ])
    db.commit()

    response = client.get("/api/rules/attr-rules")

    assert response.status_code == 200
    assert [rule["category_code"] for rule in response.json()] == ["TV"]


def test_attr_rule_create_rejects_invisible_category():
    client = _client()
    _seed_categories(client.db)

    response = client.post("/api/rules/attr-rules", json={
        "keyword": "projector",
        "match_type": "contains",
        "attr_name": "lumens",
        "attr_value": "1000",
        "category_code": "projector",
        "priority": 1,
    })

    assert response.status_code == 403
    assert response.json()["detail"] == "无权限访问该品类"


def test_attr_rule_delete_rejects_invisible_category():
    client = _client()
    db = client.db
    _seed_categories(db)
    rule = AttrRule(keyword="projector", attr_name="lumens", attr_value="1000", category_code="projector", priority=1)
    db.add(rule)
    db.commit()
    db.refresh(rule)

    response = client.delete(f"/api/rules/attr-rules/{rule.id}")

    assert response.status_code == 403
    assert response.json()["detail"] == "无权限访问该品类"


def test_match_rule_create_rejects_model_in_invisible_category():
    client = _client()
    db = client.db
    _seed_categories(db)
    model = ModelRecord(
        brand_code="brand_projector",
        model_code="model_projector",
        brand_name="投影品牌",
        model_name="投影型号",
        category_code="projector",
    )
    db.add(model)
    db.commit()
    db.refresh(model)

    response = client.post("/api/rules/match-rules", json={
        "keyword": "projector keyword",
        "match_type": "contains",
        "model_id": model.id,
        "priority": 1,
    })

    assert response.status_code == 403
    assert response.json()["detail"] == "无权限访问该品类"


def test_correction_rules_filter_by_category_permissions():
    client = _client()
    db = client.db
    _seed_categories(db)
    db.add_all([
        _correction_rule("TV", priority=1),
        _correction_rule("projector", priority=2),
    ])
    db.commit()

    response = client.get("/api/correction-rules")

    assert response.status_code == 200
    assert [rule["category_code"] for rule in response.json()] == ["TV"]


def test_correction_rule_create_rejects_invisible_category():
    client = _client()
    _seed_categories(client.db)

    response = client.post("/api/correction-rules", json={
        **_correction_rule_payload("projector"),
    })

    assert response.status_code == 403
    assert response.json()["detail"] == "无权限访问该品类"


def test_correction_rule_update_rejects_invisible_existing_category():
    client = _client()
    db = client.db
    _seed_categories(db)
    rule = _correction_rule("projector")
    db.add(rule)
    db.commit()
    db.refresh(rule)

    response = client.put(f"/api/correction-rules/{rule.id}", json={
        **_correction_rule_payload("projector", name="updated projector rule"),
    })

    assert response.status_code == 403
    assert response.json()["detail"] == "无权限访问该品类"


def test_intervention_rule_delete_rejects_invisible_category():
    client = _client()
    db = client.db
    _seed_categories(db)
    rule = InterventionRule(name="projector rule", category_code="projector", action="filter", conditions={}, priority=1)
    db.add(rule)
    db.commit()
    db.refresh(rule)

    response = client.delete(f"/api/rules/intervention-rules/{rule.id}")

    assert response.status_code == 403
    assert response.json()["detail"] == "无权限访问该品类"
