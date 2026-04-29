# URL精确匹配系统 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add URL-based S0 matching that looks up each item's URL against an imported reference table, producing `url_matched` (auto-publish) or `text_only` (needs human review) statuses, with a full CRUD management page for the mapping table.

**Architecture:** New `item_url_mappings` table bootstrapped from Excel rawdata sheet; matcher prepends S0 URL lookup before existing S1-S4 text matching; `text_only` status replaces the current fallthrough `matched` for items whose URL exists in raw data but has no mapping entry; frontend adds a URL Mappings page and a tab-split pending review list.

**Tech Stack:** FastAPI, SQLAlchemy 2.x (ORM), Alembic (migration), openpyxl (Excel parse), pytest + SQLite (tests), React 18, TypeScript, Ant Design 5, ahooks

---

## File Map

| File | Change |
|---|---|
| `backend/alembic/versions/c3d4e5f6a7b8_add_item_url_mappings.py` | **Create** — Alembic migration |
| `backend/app/models/schemas.py` | **Modify** — add `ItemUrlMapping` ORM, `ItemUrlMappingIn/Out`, update `MatchSummary` |
| `backend/app/utils/__init__.py` | **Create** — empty init |
| `backend/app/utils/url_utils.py` | **Create** — `extract_item_id()` |
| `backend/app/api/url_mapping_api.py` | **Create** — CRUD + import endpoints |
| `backend/app/main.py` | **Modify** — register new router |
| `backend/app/services/matcher.py` | **Modify** — add S0 URL lookup |
| `backend/app/services/publisher.py` | **Modify** — add `url_matched` to WHERE clause |
| `backend/app/api/match_api.py` | **Modify** — summary counts `text_only`/`url_matched`, `list_pending` accepts `status` param |
| `backend/tests/test_url_matching.py` | **Create** — unit tests |
| `frontend/src/services/api.ts` | **Modify** — add url-mapping API functions, update `listPendingMatches` |
| `frontend/src/pages/UrlMappings/index.tsx` | **Create** — management page |
| `frontend/src/pages/Match/index.tsx` | **Modify** — new stats cards, tab split |
| `frontend/src/App.tsx` | **Modify** — register `/url-mappings` route |
| `frontend/src/components/Layout/index.tsx` | **Modify** — add nav item |

---

## Task 1: Alembic migration + ORM + Pydantic

**Files:**
- Create: `backend/alembic/versions/c3d4e5f6a7b8_add_item_url_mappings.py`
- Modify: `backend/app/models/schemas.py`

- [ ] **Step 1: Write the failing test for ORM shape**

```python
# backend/tests/test_url_matching.py
"""Tests for URL-based matching system"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.models.schemas import Base, ItemUrlMapping, ModelRecord

SQLITE_URL = "sqlite:///:memory:"
engine = create_engine(SQLITE_URL, connect_args={"check_same_thread": False}, poolclass=StaticPool)
Base.metadata.drop_all(bind=engine)
Base.metadata.create_all(bind=engine)
TestSession = sessionmaker(bind=engine)


def test_item_url_mapping_orm():
    """ItemUrlMapping ORM can be created and queried"""
    db = TestSession()
    model = ModelRecord(brand_code="BOSE", model_code="SB850", category_name="SOUNDBAR")
    db.add(model)
    db.flush()

    m = ItemUrlMapping(platform="jd", item_id="100045223280", model_id=model.id, price=1999.0)
    db.add(m)
    db.commit()

    found = db.query(ItemUrlMapping).filter_by(item_id="100045223280").first()
    assert found is not None
    assert found.platform == "jd"
    assert found.model_id == model.id
    assert float(found.price) == 1999.0
    db.close()
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd backend && python -m pytest tests/test_url_matching.py::test_item_url_mapping_orm -v
```
Expected: FAIL with `ImportError: cannot import name 'ItemUrlMapping'`

- [ ] **Step 3: Create Alembic migration**

```python
# backend/alembic/versions/c3d4e5f6a7b8_add_item_url_mappings.py
"""add item_url_mappings table

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-04-29
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, Sequence[str], None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'item_url_mappings',
        sa.Column('id',         sa.Integer(),      primary_key=True, autoincrement=True),
        sa.Column('platform',   sa.String(20),     nullable=False, comment='jd/tmall/taobao/suning'),
        sa.Column('item_id',    sa.String(50),     nullable=False, comment='从URL提取的商品ID'),
        sa.Column('model_id',   sa.Integer(),      nullable=False, comment='FK → models.id'),
        sa.Column('price',      sa.Numeric(10, 2), nullable=True,  comment='单价'),
        sa.Column('created_at', sa.DateTime(),     nullable=False, server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime(),     nullable=False, server_default=sa.text('NOW()'),
                  onupdate=sa.text('NOW()')),
        sa.UniqueConstraint('platform', 'item_id', name='uq_platform_item'),
        sa.ForeignKeyConstraint(['model_id'], ['models.id']),
    )
    op.create_index('idx_url_mappings_model', 'item_url_mappings', ['model_id'])


def downgrade() -> None:
    op.drop_index('idx_url_mappings_model', table_name='item_url_mappings')
    op.drop_table('item_url_mappings')
```

- [ ] **Step 4: Add ORM + Pydantic to schemas.py**

In `backend/app/models/schemas.py`, add after the `ModelAlias` class (before the Pydantic section):

```python
class ItemUrlMapping(Base):
    __tablename__ = "item_url_mappings"
    __table_args__ = (UniqueConstraint("platform", "item_id", name="uq_platform_item"),)

    id         = Column(Integer, primary_key=True, autoincrement=True)
    platform   = Column(String(20), nullable=False)
    item_id    = Column(String(50), nullable=False)
    model_id   = Column(Integer, ForeignKey("models.id"), nullable=False)
    price      = Column(Numeric(10, 2), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow,
                        onupdate=datetime.utcnow)

    model = relationship("ModelRecord")
```

Also add these Pydantic models (after `ModelAliasOut`):

```python
class ItemUrlMappingIn(BaseModel):
    platform: str
    item_id:  str
    model_id: int
    price:    Optional[float] = None


class ItemUrlMappingOut(BaseModel):
    id:         int
    platform:   str
    item_id:    str
    model_id:   int
    price:      Optional[float]
    brand_code: Optional[str] = None
    model_code: Optional[str] = None
    brand_name: Optional[str] = None
    model_name: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}
```

Update `MatchSummary` to add two new fields:

```python
class MatchSummary(BaseModel):
    clean_job_id: int
    total:      int
    url_matched: int = 0   # NEW
    matched:    int
    text_only:  int = 0    # NEW
    pending:    int
    confirmed:  int
    excluded:   int
    disabled:   int = 0
```

- [ ] **Step 5: Run test to verify it passes**

```bash
cd backend && python -m pytest tests/test_url_matching.py::test_item_url_mapping_orm -v
```
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/alembic/versions/c3d4e5f6a7b8_add_item_url_mappings.py backend/app/models/schemas.py backend/tests/test_url_matching.py
git commit -m "feat: ItemUrlMapping ORM + Alembic migration + MatchSummary new fields"
```

---

## Task 2: URL extraction utility

**Files:**
- Create: `backend/app/utils/__init__.py`
- Create: `backend/app/utils/url_utils.py`
- Modify: `backend/tests/test_url_matching.py`

- [ ] **Step 1: Write failing tests**

Append to `backend/tests/test_url_matching.py`:

```python
from app.utils.url_utils import extract_item_id


def test_extract_jd_url():
    assert extract_item_id("https://item.jd.com/100045223280.html") == ("jd", "100045223280")


def test_extract_jd_url_no_extension():
    """URL without .html should still parse"""
    assert extract_item_id("https://item.jd.com/100045223280") == ("jd", "100045223280")


def test_extract_tmall_url():
    assert extract_item_id("https://detail.tmall.com/item.htm?id=738271928") == ("tmall", "738271928")


def test_extract_taobao_url():
    assert extract_item_id("https://item.taobao.com/item.htm?id=655781234") == ("taobao", "655781234")


def test_extract_suning_url():
    assert extract_item_id("https://product.suning.com/0070171620/11498580.html") == ("suning", "11498580")


def test_extract_unknown_url_returns_none():
    assert extract_item_id("https://www.amazon.com/dp/B08N5WRWNW") is None


def test_extract_none_returns_none():
    assert extract_item_id(None) is None


def test_extract_empty_returns_none():
    assert extract_item_id("") is None
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd backend && python -m pytest tests/test_url_matching.py::test_extract_jd_url tests/test_url_matching.py::test_extract_unknown_url_returns_none -v
```
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Create utils module**

```python
# backend/app/utils/__init__.py
```

```python
# backend/app/utils/url_utils.py
"""URL解析工具：从商品链接中提取 (platform, item_id)"""
import re
from urllib.parse import urlparse, parse_qs


def extract_item_id(url: str | None) -> tuple[str, str] | None:
    """
    从商品URL提取 (platform, item_id)。
    支持 JD / TMALL / TAOBAO / SUNING，其他平台返回 None。

    Examples:
        https://item.jd.com/100045223280.html  → ("jd", "100045223280")
        https://detail.tmall.com/item.htm?id=738271928  → ("tmall", "738271928")
        https://item.taobao.com/item.htm?id=655781234   → ("taobao", "655781234")
        https://product.suning.com/0070171620/11498580.html → ("suning", "11498580")
    """
    if not url:
        return None

    try:
        parsed = urlparse(url)
        host = parsed.netloc.lower()

        # JD: item.jd.com/{item_id}.html
        if "item.jd.com" in host:
            path = parsed.path.rstrip("/")
            filename = path.rsplit("/", 1)[-1]
            item_id = filename.replace(".html", "").strip()
            return ("jd", item_id) if item_id else None

        # TMALL: detail.tmall.com/item.htm?id={item_id}
        if "tmall.com" in host:
            qs = parse_qs(parsed.query)
            item_id_list = qs.get("id", [])
            return ("tmall", item_id_list[0]) if item_id_list else None

        # TAOBAO: item.taobao.com/item.htm?id={item_id}
        if "taobao.com" in host:
            qs = parse_qs(parsed.query)
            item_id_list = qs.get("id", [])
            return ("taobao", item_id_list[0]) if item_id_list else None

        # SUNING: product.suning.com/{shop_id}/{item_id}.html
        if "suning.com" in host:
            path = parsed.path.rstrip("/")
            filename = path.rsplit("/", 1)[-1]
            item_id = filename.replace(".html", "").strip()
            return ("suning", item_id) if item_id else None

    except Exception:
        pass

    return None
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd backend && python -m pytest tests/test_url_matching.py -k "extract" -v
```
Expected: 8 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/utils/__init__.py backend/app/utils/url_utils.py backend/tests/test_url_matching.py
git commit -m "feat: URL extraction utility (JD/TMALL/TAOBAO/SUNING)"
```

---

## Task 3: URL Mapping CRUD + Import API

**Files:**
- Create: `backend/app/api/url_mapping_api.py`
- Modify: `backend/app/main.py`
- Modify: `backend/tests/test_url_matching.py`

- [ ] **Step 1: Write failing tests**

Append to `backend/tests/test_url_matching.py`:

```python
from fastapi.testclient import TestClient
from passlib.context import CryptContext
from app.main import app
from app.models.database import get_db
from app.models.schemas import User as UserRecord

_pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")


def override_get_db():
    db = TestSession()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)


def _get_token():
    app.dependency_overrides[get_db] = override_get_db
    db = TestSession()
    user = db.query(UserRecord).filter_by(username="urltest").first()
    if not user:
        db.add(UserRecord(username="urltest", hashed_password=_pwd_ctx.hash("urltest123")))
        db.commit()
    db.close()
    r = client.post("/api/auth/login", json={"username": "urltest", "password": "urltest123"})
    return r.json()["data"]["access_token"]


def _seed_model(db, brand_code="BOSE", model_code="SB900") -> int:
    from app.models.schemas import ModelRecord
    m = db.query(ModelRecord).filter_by(brand_code=brand_code, model_code=model_code).first()
    if not m:
        m = ModelRecord(brand_code=brand_code, model_code=model_code, category_name="SOUNDBAR")
        db.add(m)
        db.commit()
    return m.id


def test_create_url_mapping():
    token = _get_token()
    headers = {"Authorization": f"Bearer {token}"}
    db = TestSession()
    model_id = _seed_model(db)
    db.close()

    r = client.post("/api/url-mappings", json={
        "platform": "jd", "item_id": "999000111", "model_id": model_id, "price": 1499.0
    }, headers=headers)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["platform"] == "jd"
    assert data["item_id"] == "999000111"
    assert data["model_id"] == model_id


def test_list_url_mappings():
    token = _get_token()
    headers = {"Authorization": f"Bearer {token}"}
    r = client.get("/api/url-mappings", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "total" in body
    assert "items" in body


def test_update_url_mapping():
    token = _get_token()
    headers = {"Authorization": f"Bearer {token}"}
    db = TestSession()
    model_id = _seed_model(db)
    mapping = ItemUrlMapping(platform="jd", item_id="update_test_777", model_id=model_id)
    db.add(mapping)
    db.commit()
    mid = mapping.id
    db.close()

    r = client.put(f"/api/url-mappings/{mid}",
                   json={"platform": "jd", "item_id": "update_test_777",
                         "model_id": model_id, "price": 888.0},
                   headers=headers)
    assert r.status_code == 200, r.text
    assert float(r.json()["price"]) == 888.0


def test_delete_url_mapping():
    token = _get_token()
    headers = {"Authorization": f"Bearer {token}"}
    db = TestSession()
    model_id = _seed_model(db)
    mapping = ItemUrlMapping(platform="jd", item_id="delete_test_555", model_id=model_id)
    db.add(mapping)
    db.commit()
    mid = mapping.id
    db.close()

    r = client.delete(f"/api/url-mappings/{mid}", headers=headers)
    assert r.status_code == 200, r.text

    db = TestSession()
    assert db.query(ItemUrlMapping).filter_by(id=mid).first() is None
    db.close()
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd backend && python -m pytest tests/test_url_matching.py::test_create_url_mapping -v
```
Expected: FAIL with 404 or ImportError (router not registered yet)

- [ ] **Step 3: Create url_mapping_api.py**

```python
# backend/app/api/url_mapping_api.py
"""URL→型号映射表 CRUD + Excel批量导入"""
from datetime import datetime
from typing import Optional
import io

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from sqlalchemy import or_
from sqlalchemy.orm import Session
import openpyxl

from app.models.database import get_db
from app.models.schemas import (
    ItemUrlMapping, ItemUrlMappingIn, ItemUrlMappingOut,
    ModelRecord, PaginatedResponse,
)
from app.utils.url_utils import extract_item_id

router = APIRouter(prefix="/api/url-mappings", tags=["url-mappings"])

# 渠道名称 → platform 规范值
_PLATFORM_MAP = {
    "JD": "jd", "京东": "jd",
    "TMALL": "tmall", "天猫": "tmall",
    "TAOBAO": "taobao", "淘宝": "taobao",
    "SUNING": "suning", "苏宁": "suning",
}


def _to_out(m: ItemUrlMapping) -> ItemUrlMappingOut:
    model = m.model
    return ItemUrlMappingOut(
        id=m.id,
        platform=m.platform,
        item_id=m.item_id,
        model_id=m.model_id,
        price=float(m.price) if m.price is not None else None,
        brand_code=model.brand_code if model else None,
        model_code=model.model_code if model else None,
        brand_name=model.brand_name if model else None,
        model_name=model.model_name if model else None,
        created_at=m.created_at,
    )


@router.post("/import")
def import_url_mappings(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """
    从 Excel rawdata sheet 批量导入 URL→型号 映射。
    期望列：渠道 / 网址 / 品牌码 / 型号码 / 单价
    采用 upsert（platform+item_id 冲突时更新 model_id 和 price）。
    """
    contents = file.file.read()
    wb = openpyxl.load_workbook(io.BytesIO(contents), read_only=True, data_only=True)

    # 优先找名为 rawdata 的 sheet，否则取第一个
    sheet = wb["rawdata"] if "rawdata" in wb.sheetnames else wb.active

    rows = list(sheet.iter_rows(values_only=True))
    if not rows:
        return {"imported": 0, "skipped": 0, "errors": []}

    # 构建列名→列索引映射（第一行为表头）
    header = [str(c).strip() if c is not None else "" for c in rows[0]]
    col = {name: idx for idx, name in enumerate(header)}

    required = {"渠道", "网址", "品牌码", "型号码"}
    missing = required - set(col.keys())
    if missing:
        raise HTTPException(400, detail=f"Excel 缺少必需列：{missing}")

    # 构建 (brand_code, model_code) → model_id 缓存
    all_models = db.query(ModelRecord).all()
    model_lookup: dict[tuple[str, str], int] = {
        (m.brand_code.upper().strip(), m.model_code.upper().strip()): m.id
        for m in all_models
    }

    imported = 0
    skipped = 0
    errors: list[str] = []

    for row_idx, row in enumerate(rows[1:], start=2):
        try:
            platform_raw = str(row[col["渠道"]] or "").strip().upper()
            platform = _PLATFORM_MAP.get(platform_raw)
            url = str(row[col["网址"]] or "").strip()
            brand_code = str(row[col["品牌码"]] or "").strip().upper()
            model_code = str(row[col["型号码"]] or "").strip().upper()
            price_raw = row[col["单价"]] if "单价" in col else None
            price = float(price_raw) if price_raw is not None else None
        except Exception as e:
            errors.append(f"第{row_idx}行解析错误：{e}")
            skipped += 1
            continue

        if not platform or not url or not brand_code or not model_code:
            skipped += 1
            continue

        url_info = extract_item_id(url)
        if not url_info or url_info[0] != platform:
            skipped += 1
            continue

        _, item_id = url_info
        model_id = model_lookup.get((brand_code, model_code))
        if not model_id:
            errors.append(f"第{row_idx}行：型号 [{brand_code}]{model_code} 不存在，已跳过")
            skipped += 1
            continue

        # Upsert
        existing = db.query(ItemUrlMapping).filter_by(
            platform=platform, item_id=item_id
        ).first()
        if existing:
            existing.model_id = model_id
            existing.price = price
            existing.updated_at = datetime.utcnow()
        else:
            db.add(ItemUrlMapping(
                platform=platform, item_id=item_id, model_id=model_id, price=price
            ))
        imported += 1

    db.commit()
    return {"imported": imported, "skipped": skipped, "errors": errors[:20]}


@router.get("", response_model=PaginatedResponse)
def list_url_mappings(
    keyword: Optional[str] = Query(None),
    platform: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
):
    q = db.query(ItemUrlMapping)
    if platform:
        q = q.filter(ItemUrlMapping.platform == platform)
    if keyword:
        kw = f"%{keyword}%"
        q = q.join(ModelRecord, ItemUrlMapping.model_id == ModelRecord.id).filter(
            or_(
                ItemUrlMapping.item_id.ilike(kw),
                ModelRecord.model_code.ilike(kw),
                ModelRecord.brand_code.ilike(kw),
            )
        )
    total = q.count()
    rows = q.order_by(ItemUrlMapping.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return PaginatedResponse(
        total=total, page=page, page_size=page_size,
        items=[_to_out(r) for r in rows],
    )


@router.post("", response_model=ItemUrlMappingOut)
def create_url_mapping(payload: ItemUrlMappingIn, db: Session = Depends(get_db)):
    if not db.query(ModelRecord).filter_by(id=payload.model_id).first():
        raise HTTPException(404, "型号不存在")
    existing = db.query(ItemUrlMapping).filter_by(
        platform=payload.platform, item_id=payload.item_id
    ).first()
    if existing:
        raise HTTPException(409, "该 platform+item_id 已存在，请使用编辑功能")
    m = ItemUrlMapping(
        platform=payload.platform,
        item_id=payload.item_id,
        model_id=payload.model_id,
        price=payload.price,
    )
    db.add(m)
    db.commit()
    db.refresh(m)
    return _to_out(m)


@router.put("/{mapping_id}", response_model=ItemUrlMappingOut)
def update_url_mapping(mapping_id: int, payload: ItemUrlMappingIn, db: Session = Depends(get_db)):
    m = db.query(ItemUrlMapping).filter_by(id=mapping_id).first()
    if not m:
        raise HTTPException(404, "映射记录不存在")
    if not db.query(ModelRecord).filter_by(id=payload.model_id).first():
        raise HTTPException(404, "型号不存在")
    m.platform = payload.platform
    m.item_id = payload.item_id
    m.model_id = payload.model_id
    m.price = payload.price
    m.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(m)
    return _to_out(m)


@router.delete("/{mapping_id}")
def delete_url_mapping(mapping_id: int, db: Session = Depends(get_db)):
    m = db.query(ItemUrlMapping).filter_by(id=mapping_id).first()
    if not m:
        raise HTTPException(404, "映射记录不存在")
    db.delete(m)
    db.commit()
    return {"deleted": True}
```

- [ ] **Step 4: Register router in main.py**

In `backend/app/main.py`, add to imports:
```python
from app.api import upload, rawdata, clean, export, metadata, models_api, match_api, publish_api, auth, workbench_api, url_mapping_api
```

Add after `app.include_router(workbench_api.router)`:
```python
app.include_router(url_mapping_api.router)
```

- [ ] **Step 5: Run tests**

```bash
cd backend && python -m pytest tests/test_url_matching.py::test_create_url_mapping tests/test_url_matching.py::test_list_url_mappings tests/test_url_matching.py::test_update_url_mapping tests/test_url_matching.py::test_delete_url_mapping -v
```
Expected: 4 tests PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/url_mapping_api.py backend/app/main.py backend/tests/test_url_matching.py
git commit -m "feat: URL mapping CRUD + import API"
```

---

## Task 4: Matcher S0 step

**Files:**
- Modify: `backend/app/services/matcher.py`
- Modify: `backend/tests/test_url_matching.py`

- [ ] **Step 1: Write failing tests**

Append to `backend/tests/test_url_matching.py`:

```python
from app.services.matcher import run_match
from app.models.schemas import (
    CleanedDataRecord, CleanJobRecord, UploadFileRecord, RawDataRecord,
)


def _seed_match_data(db, item_url: str, item_name: str, brand_raw: str, brand_code: str, model_code: str):
    """Seed minimal data for a single cleaned row with given URL."""
    model = db.query(ModelRecord).filter_by(brand_code=brand_code, model_code=model_code).first()
    if not model:
        model = ModelRecord(brand_code=brand_code, model_code=model_code, category_name="SOUNDBAR")
        db.add(model)
        db.flush()

    uf = UploadFileRecord(filename="t.xlsx", platform="jd", month_range="202601")
    db.add(uf)
    db.flush()

    rd = RawDataRecord(
        file_id=uf.id, platform="jd", month=202601, category_lv1="音频",
        item_id="testitem", item_name=item_name, brand_raw=brand_raw,
        item_url=item_url, price=999.0, sales_qty=1, sales_amount=999.0,
    )
    db.add(rd)
    db.flush()

    cj = CleanJobRecord(status="done", file_ids=[uf.id])
    db.add(cj)
    db.flush()

    cd = CleanedDataRecord(
        raw_data_id=rd.id, clean_job_id=cj.id,
        platform="jd", month=202601, category_lv1="音频",
        item_id="testitem", item_name=item_name, item_url=item_url,
        brand_raw=brand_raw, price=999.0, sales_qty=1, sales_amount=999.0,
    )
    db.add(cd)
    db.commit()
    return cj.id, model.id


def test_s0_url_match():
    """S0: item with URL in mapping table → url_matched"""
    from app.models.schemas import MatchResult, ItemUrlMapping
    db = TestSession()

    cj_id, model_id = _seed_match_data(
        db,
        item_url="https://item.jd.com/100045223280.html",
        item_name="完全不含型号的商品名称",
        brand_raw="BOSE",
        brand_code="BOSE",
        model_code="SB_S0_TEST",
    )
    # Add URL mapping
    db.add(ItemUrlMapping(platform="jd", item_id="100045223280", model_id=model_id))
    db.commit()

    stats = run_match(db, cj_id)
    results = db.query(MatchResult).filter_by(clean_job_id=cj_id).all()
    assert len(results) == 1
    assert results[0].match_status == "url_matched"
    assert results[0].match_source == "s0"
    assert results[0].model_id == model_id
    db.close()


def test_text_only_when_url_not_in_map():
    """S1-S4 text match + URL exists in raw data but NOT in mapping → text_only"""
    from app.models.schemas import MatchResult, ModelAlias
    db = TestSession()

    # model with a distinctive name in the item_name
    model = ModelRecord(brand_code="EDIFIER_TX", model_code="EDIFIER_R1280", category_name="SOUNDBAR")
    db.add(model)
    db.flush()

    uf = UploadFileRecord(filename="t2.xlsx", platform="jd", month_range="202601")
    db.add(uf)
    db.flush()
    rd = RawDataRecord(
        file_id=uf.id, platform="jd", month=202601, category_lv1="音频",
        item_id="textonly_item", item_name="EDIFIER_R1280 蓝牙音箱",
        brand_raw="EDIFIER_TX",
        item_url="https://item.jd.com/777999888.html",  # NOT in url_map
        price=500.0, sales_qty=2, sales_amount=1000.0,
    )
    db.add(rd)
    db.flush()
    cj = CleanJobRecord(status="done", file_ids=[uf.id])
    db.add(cj)
    db.flush()
    cd = CleanedDataRecord(
        raw_data_id=rd.id, clean_job_id=cj.id,
        platform="jd", month=202601, category_lv1="音频",
        item_id="textonly_item", item_name="EDIFIER_R1280 蓝牙音箱",
        item_url="https://item.jd.com/777999888.html",
        brand_raw="EDIFIER_TX", price=500.0, sales_qty=2, sales_amount=1000.0,
    )
    db.add(cd)
    db.commit()

    stats = run_match(db, cj.id)
    results = db.query(MatchResult).filter_by(clean_job_id=cj.id).all()
    assert len(results) == 1
    assert results[0].match_status == "text_only", f"Expected text_only, got {results[0].match_status}"
    db.close()


def test_matched_when_no_url():
    """Text match with no URL in raw data → matched (not text_only)"""
    from app.models.schemas import MatchResult
    db = TestSession()

    model = ModelRecord(brand_code="SENNHSR", model_code="MOMENTUM_S3", category_name="SOUNDBAR")
    db.add(model)
    db.flush()

    uf = UploadFileRecord(filename="t3.xlsx", platform="jd", month_range="202601")
    db.add(uf)
    db.flush()
    rd = RawDataRecord(
        file_id=uf.id, platform="jd", month=202601, category_lv1="音频",
        item_id="nourl_item", item_name="MOMENTUM_S3 蓝牙音箱",
        brand_raw="SENNHSR",
        item_url=None,   # No URL
        price=500.0, sales_qty=2, sales_amount=1000.0,
    )
    db.add(rd)
    db.flush()
    cj = CleanJobRecord(status="done", file_ids=[uf.id])
    db.add(cj)
    db.flush()
    cd = CleanedDataRecord(
        raw_data_id=rd.id, clean_job_id=cj.id,
        platform="jd", month=202601, category_lv1="音频",
        item_id="nourl_item", item_name="MOMENTUM_S3 蓝牙音箱",
        item_url=None,
        brand_raw="SENNHSR", price=500.0, sales_qty=2, sales_amount=1000.0,
    )
    db.add(cd)
    db.commit()

    run_match(db, cj.id)
    results = db.query(MatchResult).filter_by(clean_job_id=cj.id).all()
    assert len(results) == 1
    assert results[0].match_status == "matched"
    db.close()
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd backend && python -m pytest tests/test_url_matching.py::test_s0_url_match -v
```
Expected: FAIL — result has `match_status == "matched"` not `"url_matched"` (S0 not implemented yet)

- [ ] **Step 3: Update matcher.py**

Replace the entire `run_match` function in `backend/app/services/matcher.py`. The imports at the top need `ItemUrlMapping`:

```python
from app.models.schemas import CleanedDataRecord, ModelRecord, ModelAlias, MatchResult, ItemUrlMapping
from app.utils.url_utils import extract_item_id
```

In `run_match`, add URL map preload right after deleting old results:

```python
def run_match(db: Session, clean_job_id: int, progress_cb=None) -> dict:
    # ── 删除旧结果（支持重跑）────────────────────────────────────
    db.query(MatchResult).filter(MatchResult.clean_job_id == clean_job_id).delete(
        synchronize_session=False
    )

    # ── S0: 预加载 URL 映射表 ─────────────────────────────────────
    # key=(platform, item_id), value=model_id
    url_map: dict[tuple[str, str], int] = {}
    for um in db.query(ItemUrlMapping).all():
        url_map[(um.platform, um.item_id)] = um.model_id

    # ── 构建内存索引（S1-S4 用）──────────────────────────────────
    # ... (rest of existing index building code unchanged) ...
```

Then in the per-row loop, add S0 check at the very beginning (before `if row.brand_raw:`):

```python
    for i, row in enumerate(cleaned_rows):
        item_upper = _norm(row.item_name)

        # ── S0: URL精确匹配 ────────────────────────────────────
        url_info = extract_item_id(row.item_url) if row.item_url else None
        if url_info:
            platform, item_id = url_info
            url_model_id = url_map.get((platform, item_id))
            if url_model_id:
                results.append(MatchResult(
                    clean_job_id=clean_job_id,
                    raw_data_id=row.raw_data_id,
                    model_id=url_model_id,
                    match_status="url_matched",
                    matched_by="auto",
                    match_source="s0",
                ))
                matched_count += 1
                # 批量保存并触发 progress_cb（保持原有 batch 逻辑）
                if len(results) >= BATCH:
                    db.bulk_save_objects(results)
                    db.commit()
                    if progress_cb:
                        progress_cb(i + 1, total, matched_count)
                    results = []
                continue  # 跳过 S1-S4

        # ── S1-S4 文本匹配（原有逻辑不变）─────────────────────
        best_model: ModelRecord | None = None
        brand_identified = False
        match_source: str | None = None

        # S1 ... S2 ... S3 ... S4 ... (unchanged)

        if best_model:
            # url_info 不为 None 意味着 URL 存在但不在映射表 → 需人工审核
            status = "text_only" if url_info else "matched"
            results.append(MatchResult(
                clean_job_id=clean_job_id,
                raw_data_id=row.raw_data_id,
                model_id=best_model.id,
                match_status=status,
                matched_by="auto",
                match_source=match_source,
            ))
            matched_count += 1
        else:
            results.append(MatchResult(
                clean_job_id=clean_job_id,
                raw_data_id=row.raw_data_id,
                model_id=None,
                match_status="pending",
                matched_by="auto",
                match_source=None,
            ))
```

The complete updated `matcher.py` (with all S1-S4 logic unchanged, only the additions above):

```python
"""
型号匹配引擎

匹配步骤（依次降级）：
  S0: item_url 精确查 item_url_mappings 表 → 直接命中，跳过文本匹配
  S1: brand_raw → 精确/包含匹配 brand_code / brand_name → 在候选组里找 model_code/model_name/alias
  S2: item_name 中包含 brand_code → 在对应品牌组找 model_code/model_name/alias
  S3: item_name 中包含 brand_name（≥2字符）→ 在对应品牌组找 model_code/model_name/alias
  S4: 兜底 — model_code（≥5字符）直接出现在 item_name 中（不检查别名，避免短别名误匹配）

同优先级多候选时取 model_code 最长的，减少短码误匹配。
支持重复执行：先删旧结果再写入。

text_only：S1-S4 文本命中，但 item_url 存在且不在 url_map → 需人工补录 URL 映射
"""
from sqlalchemy.orm import Session
from app.models.schemas import CleanedDataRecord, ModelRecord, ModelAlias, MatchResult, ItemUrlMapping
from app.utils.url_utils import extract_item_id


def _norm(s: str | None) -> str:
    return (s or "").upper().strip()


def run_match(db: Session, clean_job_id: int, progress_cb=None) -> dict:
    """
    progress_cb(processed: int, total: int, matched: int) — 每批次调用一次
    """
    # ── 删除旧结果（支持重跑）────────────────────────────────────
    db.query(MatchResult).filter(MatchResult.clean_job_id == clean_job_id).delete(
        synchronize_session=False
    )

    # ── S0: 预加载 URL 映射表 ─────────────────────────────────────
    url_map: dict[tuple[str, str], int] = {}
    for um in db.query(ItemUrlMapping).all():
        url_map[(um.platform, um.item_id)] = um.model_id

    # ── 构建内存索引（S1-S4）─────────────────────────────────────
    all_models = db.query(ModelRecord).all()

    brand_code_index: dict[str, list[ModelRecord]] = {}
    for m in all_models:
        key = _norm(m.brand_code)
        if key:
            brand_code_index.setdefault(key, []).append(m)

    brand_name_index: dict[str, list[ModelRecord]] = {}
    for m in all_models:
        key = _norm(m.brand_name)
        if len(key) >= 2:
            brand_name_index.setdefault(key, []).append(m)

    long_code_models = [m for m in all_models if len(_norm(m.model_code)) >= 5]

    alias_map: dict[int, list[str]] = {}
    for a in db.query(ModelAlias).all():
        alias_map.setdefault(a.model_id, []).append(_norm(a.alias_code))

    brand_raw_cache: dict[str, list[ModelRecord]] = {}

    def _candidates_by_brand_raw(brand_raw: str) -> list[ModelRecord]:
        if brand_raw in brand_raw_cache:
            return brand_raw_cache[brand_raw]
        bu = _norm(brand_raw)
        result: list[ModelRecord] = []
        seen: set[int] = set()

        def _add(lst: list[ModelRecord]):
            for m in lst:
                if m.id not in seen:
                    result.append(m)
                    seen.add(m.id)

        if bu in brand_code_index:
            _add(brand_code_index[bu])
        if bu in brand_name_index:
            _add(brand_name_index[bu])
        if not result:
            for bc, grp in brand_code_index.items():
                if bc and bc in bu:
                    _add(grp)
        if not result:
            for bn, grp in brand_name_index.items():
                if len(bn) >= 2 and bn in bu:
                    _add(grp)

        brand_raw_cache[brand_raw] = result
        return result

    def _best(candidates: list[ModelRecord], item_upper: str, allow_alias: bool = True) -> ModelRecord | None:
        best: ModelRecord | None = None
        best_len = 0
        for m in candidates:
            mc = _norm(m.model_code)
            mn = _norm(m.model_name)
            hit_len = 0

            if mc and mc in item_upper:
                hit_len = len(mc)
            elif mn and len(mn) >= 3 and mn in item_upper:
                hit_len = len(mn)
            elif allow_alias:
                for alias in alias_map.get(m.id, []):
                    if alias and len(alias) >= 4 and alias in item_upper:
                        hit_len = len(alias)
                        break

            if hit_len > best_len:
                best = m
                best_len = hit_len
        return best

    # ── 加载清洗数据 ──────────────────────────────────────────────
    cleaned_rows = (
        db.query(CleanedDataRecord)
        .filter(CleanedDataRecord.clean_job_id == clean_job_id)
        .all()
    )

    results: list[MatchResult] = []
    matched_count = 0
    BATCH = 500
    total = len(cleaned_rows)

    for i, row in enumerate(cleaned_rows):
        item_upper = _norm(row.item_name)

        # ── S0: URL精确匹配 ────────────────────────────────────
        url_info = extract_item_id(row.item_url) if row.item_url else None
        if url_info:
            platform, item_id = url_info
            url_model_id = url_map.get((platform, item_id))
            if url_model_id:
                results.append(MatchResult(
                    clean_job_id=clean_job_id,
                    raw_data_id=row.raw_data_id,
                    model_id=url_model_id,
                    match_status="url_matched",
                    matched_by="auto",
                    match_source="s0",
                ))
                matched_count += 1
                if len(results) >= BATCH:
                    db.bulk_save_objects(results)
                    db.commit()
                    if progress_cb:
                        progress_cb(i + 1, total, matched_count)
                    results = []
                continue  # 跳过 S1-S4

        # ── S1-S4 文本匹配 ─────────────────────────────────────
        best_model: ModelRecord | None = None
        brand_identified = False
        match_source: str | None = None

        # S1
        if row.brand_raw:
            brand_identified = True
            candidates = _candidates_by_brand_raw(row.brand_raw)
            if candidates:
                m = _best(candidates, item_upper)
                if m:
                    best_model = m
                    match_source = "s1"

        # S2
        if best_model is None:
            for bc, grp in brand_code_index.items():
                if bc and bc in item_upper:
                    brand_identified = True
                    m = _best(grp, item_upper)
                    if m:
                        if len(_norm(m.model_code)) > len(_norm(best_model.model_code) if best_model else ""):
                            best_model = m
                            match_source = "s2"

        # S3
        if best_model is None:
            for bn, grp in brand_name_index.items():
                if len(bn) >= 2 and bn in item_upper:
                    brand_identified = True
                    m = _best(grp, item_upper)
                    if m:
                        if len(_norm(m.model_code)) > len(_norm(best_model.model_code) if best_model else ""):
                            best_model = m
                            match_source = "s3"

        # S4
        if best_model is None and not brand_identified:
            best_model = _best(long_code_models, item_upper, allow_alias=False)
            if best_model:
                match_source = "s4"

        if best_model:
            # url_info 不为 None → URL存在但不在映射表 → 需人工审核
            status = "text_only" if url_info else "matched"
            results.append(MatchResult(
                clean_job_id=clean_job_id,
                raw_data_id=row.raw_data_id,
                model_id=best_model.id,
                match_status=status,
                matched_by="auto",
                match_source=match_source,
            ))
            matched_count += 1
        else:
            results.append(MatchResult(
                clean_job_id=clean_job_id,
                raw_data_id=row.raw_data_id,
                model_id=None,
                match_status="pending",
                matched_by="auto",
                match_source=None,
            ))

        if len(results) >= BATCH:
            db.bulk_save_objects(results)
            db.commit()
            if progress_cb:
                progress_cb(i + 1, total, matched_count)
            results = []

    if results:
        db.bulk_save_objects(results)
        db.commit()

    return {"total": total, "matched": matched_count, "pending": total - matched_count}
```

- [ ] **Step 4: Run matcher tests**

```bash
cd backend && python -m pytest tests/test_url_matching.py::test_s0_url_match tests/test_url_matching.py::test_text_only_when_url_not_in_map tests/test_url_matching.py::test_matched_when_no_url -v
```
Expected: 3 tests PASS

- [ ] **Step 5: Run all existing tests to confirm no regression**

```bash
cd backend && python -m pytest tests/ -v
```
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/matcher.py backend/tests/test_url_matching.py
git commit -m "feat: matcher S0 URL lookup — url_matched / text_only status"
```

---

## Task 5: Publisher + Match API updates

**Files:**
- Modify: `backend/app/services/publisher.py`
- Modify: `backend/app/api/match_api.py`
- Modify: `backend/tests/test_url_matching.py`

- [ ] **Step 1: Write failing tests**

Append to `backend/tests/test_url_matching.py`:

```python
def test_publisher_includes_url_matched():
    """url_matched rows are published; text_only rows are skipped"""
    from app.models.schemas import (
        MatchResult, UploadFileRecord, RawDataRecord, CleanJobRecord,
    )
    from app.models.analytics_db import AnalyticsBase, analytics_engine, AnalyticsSession
    from app.services.publisher import run_publish

    AnalyticsBase.metadata.create_all(bind=analytics_engine)

    db = TestSession()
    model = db.query(ModelRecord).first() or ModelRecord(
        brand_code="PUB_TEST", model_code="PUB_MODEL", category_name="SOUNDBAR"
    )
    if not model.id:
        db.add(model)
        db.flush()

    uf = UploadFileRecord(filename="pub.xlsx", platform="jd", month_range="202601")
    db.add(uf)
    db.flush()

    rd1 = RawDataRecord(file_id=uf.id, platform="jd", month=202601, category_lv1="音频",
                        item_id="pub1", item_name="pub item 1", brand_raw="PUB_TEST",
                        price=500.0, sales_qty=1, sales_amount=500.0)
    rd2 = RawDataRecord(file_id=uf.id, platform="jd", month=202601, category_lv1="音频",
                        item_id="pub2", item_name="pub item 2", brand_raw="PUB_TEST",
                        price=300.0, sales_qty=1, sales_amount=300.0)
    db.add_all([rd1, rd2])
    db.flush()

    cj = CleanJobRecord(status="done", file_ids=[uf.id])
    db.add(cj)
    db.flush()

    mr1 = MatchResult(clean_job_id=cj.id, raw_data_id=rd1.id,
                      model_id=model.id, match_status="url_matched", is_disabled=0)
    mr2 = MatchResult(clean_job_id=cj.id, raw_data_id=rd2.id,
                      model_id=model.id, match_status="text_only", is_disabled=0)
    db.add_all([mr1, mr2])
    db.commit()

    analytics_db = AnalyticsSession()
    try:
        result = run_publish(db, analytics_db, cj.id)
        assert result["published_count"] == 1, \
            f"Should publish url_matched only, got {result['published_count']}"
    finally:
        db.close()
        analytics_db.close()


def test_summary_includes_url_matched_and_text_only():
    """GET /api/match/{cj_id}/summary returns url_matched and text_only counts"""
    token = _get_token()
    headers = {"Authorization": f"Bearer {token}"}
    from app.models.schemas import MatchResult, CleanJobRecord, UploadFileRecord, RawDataRecord

    db = TestSession()
    model = db.query(ModelRecord).first()
    uf = UploadFileRecord(filename="sum.xlsx", platform="jd", month_range="202601")
    db.add(uf); db.flush()
    cj = CleanJobRecord(status="done", file_ids=[uf.id])
    db.add(cj); db.flush()

    rd1 = RawDataRecord(file_id=uf.id, platform="jd", month=202601, category_lv1="音频",
                        item_id="s1", item_name="s1", brand_raw="X", price=1.0,
                        sales_qty=1, sales_amount=1.0)
    rd2 = RawDataRecord(file_id=uf.id, platform="jd", month=202601, category_lv1="音频",
                        item_id="s2", item_name="s2", brand_raw="X", price=1.0,
                        sales_qty=1, sales_amount=1.0)
    db.add_all([rd1, rd2]); db.flush()

    db.add(MatchResult(clean_job_id=cj.id, raw_data_id=rd1.id,
                       model_id=model.id, match_status="url_matched"))
    db.add(MatchResult(clean_job_id=cj.id, raw_data_id=rd2.id,
                       model_id=model.id, match_status="text_only"))
    db.commit()
    cj_id = cj.id
    db.close()

    r = client.get(f"/api/match/{cj_id}/summary", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["url_matched"] == 1, f"url_matched should be 1: {body}"
    assert body["text_only"] == 1, f"text_only should be 1: {body}"


def test_list_text_only():
    """GET /api/match/{cj_id}/pending?status=text_only returns text_only rows"""
    token = _get_token()
    headers = {"Authorization": f"Bearer {token}"}
    from app.models.schemas import MatchResult, CleanJobRecord, UploadFileRecord, RawDataRecord

    db = TestSession()
    model = db.query(ModelRecord).first()
    uf = UploadFileRecord(filename="to.xlsx", platform="jd", month_range="202601")
    db.add(uf); db.flush()
    cj = CleanJobRecord(status="done", file_ids=[uf.id])
    db.add(cj); db.flush()
    rd = RawDataRecord(file_id=uf.id, platform="jd", month=202601, category_lv1="音频",
                       item_id="to1", item_name="test text only item", brand_raw="X",
                       price=1.0, sales_qty=1, sales_amount=1.0)
    db.add(rd); db.flush()
    db.add(MatchResult(clean_job_id=cj.id, raw_data_id=rd.id,
                       model_id=model.id, match_status="text_only"))
    db.commit()
    cj_id = cj.id
    db.close()

    r = client.get(f"/api/match/{cj_id}/pending", params={"status": "text_only"}, headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["total"] >= 1
    assert all(item["match_status"] == "text_only" for item in body["items"])
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd backend && python -m pytest tests/test_url_matching.py::test_publisher_includes_url_matched tests/test_url_matching.py::test_summary_includes_url_matched_and_text_only -v
```
Expected: FAIL

- [ ] **Step 3: Update publisher.py — add url_matched to WHERE clause**

In `backend/app/services/publisher.py`, update the SQL at line 68:

```python
        WHERE mr.clean_job_id = :clean_job_id
          AND mr.match_status IN ('url_matched', 'matched', 'confirmed')
          AND mr.is_disabled = 0
```

- [ ] **Step 4: Update match_api.py — summary + list_pending**

In `get_match_summary`, update the return statement to include the new counts:

```python
@router.get("/{clean_job_id}/summary", response_model=MatchSummary)
def get_match_summary(clean_job_id: int, db: Session = Depends(get_db)):
    """查看某次清洗任务的匹配统计，无记录时返回全零（不报错）"""
    rows = db.query(MatchResult).filter(MatchResult.clean_job_id == clean_job_id).all()
    if not rows:
        return MatchSummary(
            clean_job_id=clean_job_id,
            total=0, url_matched=0, matched=0, text_only=0,
            pending=0, confirmed=0, excluded=0, disabled=0,
        )

    total = len(rows)
    status_count: dict[str, int] = {}
    for r in rows:
        status_count[r.match_status] = status_count.get(r.match_status, 0) + 1

    disabled_count = sum(1 for r in rows if r.is_disabled == 1)

    return MatchSummary(
        clean_job_id=clean_job_id,
        total=total,
        url_matched=status_count.get("url_matched", 0),
        matched=status_count.get("matched", 0),
        text_only=status_count.get("text_only", 0),
        pending=status_count.get("pending", 0),
        confirmed=status_count.get("confirmed", 0),
        excluded=status_count.get("excluded", 0),
        disabled=disabled_count,
    )
```

In `list_pending`, add a `status` query param (defaults to `"pending"`):

```python
@router.get("/{clean_job_id}/pending", response_model=PaginatedResponse)
def list_pending(
    clean_job_id: int,
    keyword: Optional[str] = Query(None),
    status: str = Query("pending"),       # NEW — also accepts "text_only"
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """分页查询待确认条目，status=pending 或 text_only"""
    allowed_statuses = {"pending", "text_only"}
    if status not in allowed_statuses:
        status = "pending"

    q = (
        db.query(MatchResult, RawDataRecord)
        .join(RawDataRecord, MatchResult.raw_data_id == RawDataRecord.id)
        .filter(
            MatchResult.clean_job_id == clean_job_id,
            MatchResult.match_status == status,
        )
    )
    if keyword:
        q = q.filter(RawDataRecord.item_name.ilike(f"%{keyword}%"))

    total = q.count()
    rows = q.offset((page - 1) * page_size).limit(page_size).all()

    items = []
    for mr, rd in rows:
        items.append(MatchResultOut(
            id=mr.id,
            clean_job_id=mr.clean_job_id,
            raw_data_id=mr.raw_data_id,
            model_id=mr.model_id,
            match_status=mr.match_status,
            matched_by=mr.matched_by,
            item_name=rd.item_name,
            brand_raw=rd.brand_raw,
            model_code=None,
            brand_code=None,
        ))

    return PaginatedResponse(total=total, page=page, page_size=page_size, items=items)
```

Also update the `avg_price_disable` endpoint — add `url_matched` to the `match_status.in_()` filter so URL-matched rows can also be bulk-disabled:

```python
MatchResult.match_status.in_(["url_matched", "matched", "confirmed"]),
```

- [ ] **Step 5: Run all tests**

```bash
cd backend && python -m pytest tests/ -v
```
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/publisher.py backend/app/api/match_api.py backend/tests/test_url_matching.py
git commit -m "feat: publisher + summary + list_pending support url_matched/text_only"
```

---

## Task 6: Frontend API layer

**Files:**
- Modify: `frontend/src/services/api.ts`

- [ ] **Step 1: Add URL mapping API functions**

Append to `frontend/src/services/api.ts`:

```typescript
// ─── URL Mappings ───────────────────────────────────────────
export const importUrlMappings = (formData: FormData) =>
  api.post('/url-mappings/import', formData, { headers: { 'Content-Type': 'multipart/form-data' } })

export const listUrlMappings = (params: Record<string, unknown>) =>
  api.get('/url-mappings', { params })

export const createUrlMapping = (data: { platform: string; item_id: string; model_id: number; price?: number }) =>
  api.post('/url-mappings', data)

export const updateUrlMapping = (id: number, data: { platform: string; item_id: string; model_id: number; price?: number }) =>
  api.put(`/url-mappings/${id}`, data)

export const deleteUrlMapping = (id: number) =>
  api.delete(`/url-mappings/${id}`)
```

Update `listPendingMatches` to accept a `status` param:

```typescript
export const listPendingMatches = (clean_job_id: number, params?: Record<string, unknown>) =>
  api.get(`/match/${clean_job_id}/pending`, { params })
```

(This function signature is unchanged — callers already pass `params` as an object. The frontend will pass `status: 'text_only'` via params when needed.)

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd frontend && npx tsc --noEmit
```
Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add frontend/src/services/api.ts
git commit -m "feat: frontend API functions for URL mappings"
```

---

## Task 7: URL Mappings management page

**Files:**
- Create: `frontend/src/pages/UrlMappings/index.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/Layout/index.tsx`

- [ ] **Step 1: Create page**

```tsx
// frontend/src/pages/UrlMappings/index.tsx
import { useState } from 'react'
import {
  Card, Table, Button, Input, Select, Space, Typography,
  Modal, Form, InputNumber, Upload, message, Popconfirm, Tag,
} from 'antd'
import { PlusOutlined, UploadOutlined, EditOutlined, DeleteOutlined } from '@ant-design/icons'
import { useRequest } from 'ahooks'
import {
  listUrlMappings, createUrlMapping, updateUrlMapping,
  deleteUrlMapping, importUrlMappings, listModels,
} from '../../services/api'

const { Text } = Typography

type UrlMapping = {
  id: number
  platform: string
  item_id: string
  model_id: number
  price: number | null
  brand_code: string | null
  model_code: string | null
  brand_name: string | null
  model_name: string | null
}

type ModelOption = {
  id: number
  brand_code: string
  model_code: string
  brand_name: string | null
  model_name: string | null
}

const PLATFORM_OPTIONS = [
  { value: 'jd', label: '京东 (JD)' },
  { value: 'tmall', label: '天猫 (TMALL)' },
  { value: 'taobao', label: '淘宝 (TAOBAO)' },
  { value: 'suning', label: '苏宁 (SUNING)' },
]

export default function UrlMappingsPage() {
  const [keyword, setKeyword] = useState('')
  const [platform, setPlatform] = useState<string | undefined>()
  const [page, setPage] = useState(1)
  const [modalOpen, setModalOpen] = useState(false)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [form] = Form.useForm()
  const [saving, setSaving] = useState(false)
  const [importing, setImporting] = useState(false)

  const { data: modelsData } = useRequest(
    () => listModels({ page: 1, page_size: 500 }).then(r => r.data)
  )
  const modelOptions: ModelOption[] = modelsData?.items ?? []

  const { data, loading, refresh } = useRequest(
    () => listUrlMappings({ keyword: keyword || undefined, platform: platform || undefined, page, page_size: 20 }).then(r => r.data),
    { refreshDeps: [keyword, platform, page] }
  )

  const openCreate = () => {
    setEditingId(null)
    form.resetFields()
    setModalOpen(true)
  }

  const openEdit = (record: UrlMapping) => {
    setEditingId(record.id)
    form.setFieldsValue({
      platform: record.platform,
      item_id: record.item_id,
      model_id: record.model_id,
      price: record.price,
    })
    setModalOpen(true)
  }

  const handleSave = async () => {
    const values = await form.validateFields()
    setSaving(true)
    try {
      if (editingId) {
        await updateUrlMapping(editingId, values)
        message.success('已更新')
      } else {
        await createUrlMapping(values)
        message.success('已新增')
      }
      setModalOpen(false)
      refresh()
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async (id: number) => {
    await deleteUrlMapping(id)
    message.success('已删除')
    refresh()
  }

  const handleImport = async (file: File) => {
    setImporting(true)
    const fd = new FormData()
    fd.append('file', file)
    try {
      const res = await importUrlMappings(fd)
      const { imported, skipped, errors } = res.data
      message.success(`导入完成：写入 ${imported} 条，跳过 ${skipped} 条`)
      if (errors?.length) {
        message.warning(`部分行有问题：${errors.slice(0, 3).join('；')}`, 8)
      }
      refresh()
    } finally {
      setImporting(false)
    }
    return false  // prevent default upload
  }

  const columns = [
    {
      title: '平台', dataIndex: 'platform', width: 80,
      render: (v: string) => <Tag color={v === 'jd' ? 'blue' : 'orange'}>{v.toUpperCase()}</Tag>
    },
    { title: 'item_id', dataIndex: 'item_id', width: 160 },
    {
      title: '品牌码', dataIndex: 'brand_code', width: 100,
      render: (v: string | null) => v ?? '-'
    },
    {
      title: '型号码', dataIndex: 'model_code', width: 160,
      render: (v: string | null) => v ? <Text code>{v}</Text> : '-'
    },
    {
      title: '品牌名', dataIndex: 'brand_name', width: 120,
      render: (v: string | null) => v ?? '-'
    },
    {
      title: '单价', dataIndex: 'price', width: 90,
      render: (v: number | null) => v != null ? `¥${v}` : '-'
    },
    {
      title: '操作', width: 120, fixed: 'right' as const,
      render: (_: unknown, record: UrlMapping) => (
        <Space size={4}>
          <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(record)}>编辑</Button>
          <Popconfirm title="确认删除？" onConfirm={() => handleDelete(record.id)}>
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      )
    },
  ]

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Card>
        <Space wrap>
          <Input.Search
            placeholder="搜索 item_id / 型号码 / 品牌码"
            allowClear
            style={{ width: 280 }}
            onSearch={v => { setKeyword(v); setPage(1) }}
          />
          <Select
            placeholder="平台筛选"
            allowClear
            style={{ width: 160 }}
            options={PLATFORM_OPTIONS}
            onChange={v => { setPlatform(v); setPage(1) }}
          />
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新增</Button>
          <Upload
            accept=".xlsx,.xls"
            showUploadList={false}
            beforeUpload={handleImport}
          >
            <Button icon={<UploadOutlined />} loading={importing}>导入 Excel</Button>
          </Upload>
        </Space>
      </Card>

      <Card>
        <Table
          dataSource={data?.items ?? []}
          columns={columns}
          rowKey="id"
          size="small"
          loading={loading}
          scroll={{ x: 900 }}
          pagination={{
            current: page,
            pageSize: 20,
            total: data?.total ?? 0,
            onChange: setPage,
            showTotal: t => `共 ${t} 条`,
          }}
        />
      </Card>

      <Modal
        title={editingId ? '编辑映射' : '新增映射'}
        open={modalOpen}
        onOk={handleSave}
        onCancel={() => setModalOpen(false)}
        confirmLoading={saving}
        destroyOnClose
      >
        <Form form={form} layout="vertical">
          <Form.Item name="platform" label="平台" rules={[{ required: true }]}>
            <Select options={PLATFORM_OPTIONS} />
          </Form.Item>
          <Form.Item name="item_id" label="item_id" rules={[{ required: true }]}>
            <Input placeholder="如：100045223280" />
          </Form.Item>
          <Form.Item name="model_id" label="型号" rules={[{ required: true }]}>
            <Select
              showSearch
              placeholder="搜索品牌/型号码"
              filterOption={(input, option) =>
                (option?.label as string ?? '').toLowerCase().includes(input.toLowerCase())
              }
              options={modelOptions.map(m => ({
                value: m.id,
                label: `[${m.brand_code}] ${m.model_code}${m.model_name ? ' ' + m.model_name : ''}`,
              }))}
            />
          </Form.Item>
          <Form.Item name="price" label="单价（元）">
            <InputNumber min={0} precision={2} style={{ width: '100%' }} />
          </Form.Item>
        </Form>
      </Modal>
    </Space>
  )
}
```

- [ ] **Step 2: Register route in App.tsx**

Add import and route:

```tsx
import UrlMappingsPage from './pages/UrlMappings'
```

Add route inside the protected routes:
```tsx
<Route path="/url-mappings" element={<UrlMappingsPage />} />
```

- [ ] **Step 3: Add nav item in Layout/index.tsx**

Import the icon and add nav item. In the imports add:
```tsx
import { LinkOutlined } from '@ant-design/icons'
```

In `menuItems`, add after `型号管理`:
```tsx
{ key: '/url-mappings', icon: <LinkOutlined />, label: 'URL映射管理' },
```

- [ ] **Step 4: Verify TypeScript compiles**

```bash
cd frontend && npx tsc --noEmit
```
Expected: No errors

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/UrlMappings/index.tsx frontend/src/App.tsx frontend/src/components/Layout/index.tsx
git commit -m "feat: URL mappings management page (/url-mappings)"
```

---

## Task 8: Match page — stats cards + tab split

**Files:**
- Modify: `frontend/src/pages/Match/index.tsx`

- [ ] **Step 1: Update MatchSummary type**

In the `MatchSummary` type definition at the top of the file, add:

```tsx
type MatchSummary = {
  clean_job_id: number
  total: number
  url_matched: number   // NEW
  matched: number
  text_only: number     // NEW
  pending: number
  confirmed: number
  excluded: number
  disabled: number
}
```

- [ ] **Step 2: Add activeTab state and update useRequest**

Add after the existing state declarations:

```tsx
const [activeTab, setActiveTab] = useState<'pending' | 'text_only'>('text_only')
```

Update the `pendingData` useRequest to pass `status` param and react to `activeTab`:

```tsx
const { data: pendingData, loading: pendingLoading, refresh: refreshPending } = useRequest(
  () => listPendingMatches(selectedJobId!, {
    keyword: keyword || undefined,
    page,
    page_size: 20,
    status: activeTab,
  }).then(r => r.data),
  {
    ready: selectedJobId != null && summary != null && (summary.pending > 0 || summary.text_only > 0),
    refreshDeps: [selectedJobId, keyword, page, activeTab],
  }
)
```

- [ ] **Step 3: Update statistics card**

Replace the existing statistics `<Row>` block (the one with Statistic components) with:

```tsx
{summary && summary.total > 0 && (
  <Card>
    <Row gutter={16}>
      <Col span={3}><Statistic title="总条数" value={summary.total} /></Col>
      <Col span={3}><Statistic title="URL匹配" value={summary.url_matched} valueStyle={{ color: '#389e0d' }} /></Col>
      <Col span={3}><Statistic title="文本匹配" value={summary.matched} valueStyle={{ color: '#3f8600' }} /></Col>
      <Col span={3}><Statistic title="URL待审" value={summary.text_only} valueStyle={{ color: '#d48806' }} /></Col>
      <Col span={3}><Statistic title="待确认" value={summary.pending} valueStyle={{ color: '#d46b08' }} /></Col>
      <Col span={3}><Statistic title="已人工确认" value={summary.confirmed} valueStyle={{ color: '#1677ff' }} /></Col>
      <Col span={2}><Statistic title="已排除" value={summary.excluded} valueStyle={{ color: '#cf1322' }} /></Col>
      <Col span={2}><Statistic title="已禁用" value={summary.disabled ?? 0} valueStyle={{ color: '#faad14' }} /></Col>
      <Col span={3}>
        <Statistic
          title="匹配率"
          value={summary.total ? Math.round(
            (summary.url_matched + summary.matched + summary.confirmed) / summary.total * 100
          ) : 0}
          suffix="%"
          valueStyle={{ color: '#3f8600' }}
        />
      </Col>
    </Row>
  </Card>
)}
```

- [ ] **Step 4: Replace pending Card with tab-split version**

Replace the existing `{summary && summary.pending > 0 && (<Card ...>)}` block with:

```tsx
{summary && (summary.pending > 0 || summary.text_only > 0) && (
  <Card
    title={
      <Space>
        <span>待处理条目</span>
        <span style={{ fontSize: 12, color: '#8c8c8c' }}>
          URL待审 {summary.text_only} 条 · 待确认 {summary.pending} 条
        </span>
      </Space>
    }
    extra={
      <Input.Search
        placeholder="搜索宝贝名称"
        allowClear
        style={{ width: 220 }}
        onSearch={v => { setKeyword(v); setPage(1) }}
      />
    }
  >
    <Tabs
      activeKey={activeTab}
      onChange={key => {
        setActiveTab(key as 'pending' | 'text_only')
        setPage(1)
        setKeyword('')
      }}
      items={[
        {
          key: 'text_only',
          label: (
            <span>
              URL待审
              {summary.text_only > 0 && (
                <span style={{
                  marginLeft: 6, background: '#d48806', color: '#fff',
                  borderRadius: 10, padding: '0 6px', fontSize: 11,
                }}>
                  {summary.text_only}
                </span>
              )}
            </span>
          ),
          children: null,
        },
        {
          key: 'pending',
          label: (
            <span>
              待确认
              {summary.pending > 0 && (
                <span style={{
                  marginLeft: 6, background: '#d46b08', color: '#fff',
                  borderRadius: 10, padding: '0 6px', fontSize: 11,
                }}>
                  {summary.pending}
                </span>
              )}
            </span>
          ),
          children: null,
        },
      ]}
    />
    <Table
      dataSource={pendingData?.items ?? []}
      columns={pendingColumns}
      rowKey="id"
      size="small"
      loading={pendingLoading}
      scroll={{ x: 800 }}
      pagination={{
        current: page,
        pageSize: 20,
        total: pendingData?.total ?? 0,
        onChange: setPage,
        showTotal: t => `共 ${t} 条`,
      }}
    />
  </Card>
)}
```

Add `Tabs` to the antd import line at the top:
```tsx
import {
  Card, Select, Button, Table, Tag, Space, Typography, Input, Tabs,
  message, Row, Col, Statistic, Tooltip, Progress, Alert, Popconfirm, InputNumber
} from 'antd'
```

Also update the two helper text cards at the bottom to reflect the new summary shape:

```tsx
{summary && summary.total === 0 && (
  <Card>
    <Text type="secondary">该任务尚未执行匹配，请点击「执行匹配」开始匹配。</Text>
  </Card>
)}

{summary && summary.total > 0 && summary.pending === 0 && summary.text_only === 0 && (
  <Card>
    <Text type="secondary">暂无待处理条目，可点击「发布到分析库」发布已匹配结果。</Text>
  </Card>
)}
```

- [ ] **Step 5: Update avg_price_disable filter**

In `match_api.py`, the `avg_price_disable` endpoint's `match_status.in_()` was already updated in Task 5 to include `url_matched`. Verify it's there:

```python
MatchResult.match_status.in_(["url_matched", "matched", "confirmed"]),
```

- [ ] **Step 6: Verify TypeScript compiles**

```bash
cd frontend && npx tsc --noEmit
```
Expected: No errors

- [ ] **Step 7: Run all backend tests one final time**

```bash
cd backend && python -m pytest tests/ -v
```
Expected: All tests PASS

- [ ] **Step 8: Commit**

```bash
git add frontend/src/pages/Match/index.tsx
git commit -m "feat: Match page — URL统计卡片 + text_only/pending Tab审核分流"
```

---

## Self-Review

### Spec coverage

| Spec requirement | Task |
|---|---|
| 新建 `item_url_mappings` 参考表 | Task 1 |
| Excel rawdata sheet 批量导入 | Task 3 |
| 平台 CRUD 管理界面 | Task 7 |
| 匹配引擎 S0 步骤 | Task 4 |
| `text_only` 新状态 | Task 4 + 5 |
| 发布条件更新（含 `url_matched`） | Task 5 |
| Match 页 `text_only` Tab | Task 8 |
| 统计卡片 `url_matched` / `text_only` 计数 | Task 5 (API) + Task 8 (UI) |
| `avg_price_disable` 包含 `url_matched` | Task 5 |

### Placeholder scan

无 TBD/TODO/placeholder。

### Type consistency

- `MatchSummary.url_matched` / `text_only` 在 Task 1 (schemas.py)、Task 5 (API return)、Task 8 (TS type) 三处一致
- `match_source="s0"` 在 Task 4 matcher 和 test 中一致
- `listPendingMatches` 的 `status` 参数在 Task 6 (api.ts) 和 Task 8 (page usage) 一致
