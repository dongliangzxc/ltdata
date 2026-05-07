# 规则引擎可配置化（第一期）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将干扰词过滤、品牌写法标准化、显式型号匹配规则从硬编码迁移到数据库，并提供前端管理界面，让分析师无需开发介入即可自主维护规则。

**Architecture:** 在现有 S0-S4 匹配引擎前增加两个前置阶段：清洗时过滤干扰词并标准化品牌写法；匹配时新增 S0.5 显式规则层（优先级高于 S1-S4，无规则配置时行为不变）。新增 `rules_api.py` 路由统一管理所有规则表 CRUD。

**Tech Stack:** Python 3.11 / FastAPI / SQLAlchemy / Alembic / MySQL · React 18 / TypeScript / Ant Design

---

## 文件变更总览

| 操作 | 文件 | 说明 |
|------|------|------|
| 新建 | `backend/alembic/versions/d4e5f6a7b8c9_add_rules_engine_tables.py` | DB 迁移 |
| 修改 | `backend/app/models/schemas.py` | 新增 4 个 ORM 模型，2 个已有模型加字段 |
| 新建 | `backend/app/api/rules_api.py` | 规则管理全部 API |
| 修改 | `backend/app/main.py` | 注册 rules_api 路由 |
| 修改 | `backend/app/services/data_cleaner.py` | 干扰词过滤 + 品牌写法标准化 |
| 修改 | `backend/app/services/matcher.py` | S0.5 显式规则 + brand_identified 字段 |
| 新建 | `backend/tests/conftest.py` | pytest 测试 DB 配置 |
| 新建 | `backend/tests/test_data_cleaner.py` | 清洗服务测试 |
| 新建 | `backend/tests/test_matcher.py` | 匹配服务测试 |
| 修改 | `frontend/src/services/api.ts` | 新增规则相关 API 函数 |
| 新建 | `frontend/src/pages/Rules/index.tsx` | 规则管理页（4 个 Tab） |
| 修改 | `frontend/src/App.tsx` | 新增 /rules 路由 |
| 修改 | `frontend/src/components/Layout/index.tsx` | 导航栏加「规则管理」入口 |
| 修改 | `frontend/src/pages/Match/index.tsx` | 新增「未识别品牌」Tab |
| 修改 | `frontend/src/pages/Clean/index.tsx` | 结果卡片展示 filtered_count |

---

## Task 1: DB 迁移 + ORM 模型

**Files:**
- Create: `backend/alembic/versions/d4e5f6a7b8c9_add_rules_engine_tables.py`
- Modify: `backend/app/models/schemas.py`

- [ ] **Step 1: 创建 Alembic 迁移文件**

创建 `backend/alembic/versions/d4e5f6a7b8c9_add_rules_engine_tables.py`：

```python
"""add rules engine tables

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-05-07
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, Sequence[str], None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── noise_words ───────────────────────────────────────────
    op.create_table(
        'noise_words',
        sa.Column('id',          sa.Integer(),     primary_key=True, autoincrement=True),
        sa.Column('keyword',     sa.String(200),   nullable=False),
        sa.Column('match_field', sa.String(20),    nullable=False, server_default='item_name'),
        sa.Column('is_active',   sa.SmallInteger(),nullable=False, server_default='1'),
        sa.Column('created_by',  sa.String(50),    nullable=True),
        sa.Column('created_at',  sa.DateTime(),    nullable=False, server_default=sa.text('NOW()')),
        sa.UniqueConstraint('keyword', 'match_field', name='uq_noise_keyword_field'),
    )

    # ── filtered_items ────────────────────────────────────────
    op.create_table(
        'filtered_items',
        sa.Column('id',              sa.Integer(),     primary_key=True, autoincrement=True),
        sa.Column('raw_data_id',     sa.Integer(),     nullable=True),
        sa.Column('clean_job_id',    sa.Integer(),     nullable=True),
        sa.Column('matched_keyword', sa.String(200),   nullable=True),
        sa.Column('is_recovered',    sa.SmallInteger(),nullable=False, server_default='0'),
        sa.Column('recovered_at',    sa.DateTime(),    nullable=True),
        sa.Column('created_at',      sa.DateTime(),    nullable=False, server_default=sa.text('NOW()')),
        sa.ForeignKeyConstraint(['raw_data_id'],  ['raw_data.id']),
        sa.ForeignKeyConstraint(['clean_job_id'], ['clean_jobs.id']),
    )
    op.create_index('idx_filtered_items_job', 'filtered_items', ['clean_job_id'])

    # ── brand_aliases ─────────────────────────────────────────
    op.create_table(
        'brand_aliases',
        sa.Column('id',         sa.Integer(),     primary_key=True, autoincrement=True),
        sa.Column('alias_name', sa.String(200),   nullable=False, unique=True),
        sa.Column('brand_code', sa.String(100),   nullable=False),
        sa.Column('is_active',  sa.SmallInteger(),nullable=False, server_default='1'),
        sa.Column('created_by', sa.String(50),    nullable=True),
        sa.Column('created_at', sa.DateTime(),    nullable=False, server_default=sa.text('NOW()')),
    )

    # ── match_rules ───────────────────────────────────────────
    op.create_table(
        'match_rules',
        sa.Column('id',         sa.Integer(),     primary_key=True, autoincrement=True),
        sa.Column('keyword',    sa.String(200),   nullable=False, unique=True),
        sa.Column('match_type', sa.String(20),    nullable=False, server_default='contains'),
        sa.Column('model_id',   sa.Integer(),     nullable=False),
        sa.Column('priority',   sa.Integer(),     nullable=False, server_default='100'),
        sa.Column('is_active',  sa.SmallInteger(),nullable=False, server_default='1'),
        sa.Column('created_by', sa.String(50),    nullable=True),
        sa.Column('created_at', sa.DateTime(),    nullable=False, server_default=sa.text('NOW()')),
        sa.ForeignKeyConstraint(['model_id'], ['models.id']),
    )
    op.create_index('idx_match_rules_priority', 'match_rules', ['priority'])

    # ── 已有表字段扩展 ────────────────────────────────────────
    op.add_column('cleaned_data',  sa.Column('is_recovered',    sa.SmallInteger(), nullable=False, server_default='0'))
    op.add_column('match_results', sa.Column('brand_identified', sa.SmallInteger(), nullable=False, server_default='1'))
    op.add_column('clean_jobs',    sa.Column('row_filtered',     sa.Integer(),      nullable=False, server_default='0'))


def downgrade() -> None:
    op.drop_column('clean_jobs',    'row_filtered')
    op.drop_column('match_results', 'brand_identified')
    op.drop_column('cleaned_data',  'is_recovered')
    op.drop_index('idx_match_rules_priority', table_name='match_rules')
    op.drop_table('match_rules')
    op.drop_table('brand_aliases')
    op.drop_index('idx_filtered_items_job', table_name='filtered_items')
    op.drop_table('filtered_items')
    op.drop_table('noise_words')
```

- [ ] **Step 2: 在 schemas.py 添加 4 个新 ORM 模型**

在 `backend/app/models/schemas.py` 的 `# ─── 型号匹配结果 ───` 注释**之前**插入以下代码（放在 `ItemUrlMapping` 定义之后）：

```python
# ─────────────────────────── 规则引擎 ───────────────────────────

class NoiseWord(Base):
    __tablename__ = "noise_words"
    __table_args__ = (
        UniqueConstraint("keyword", "match_field", name="uq_noise_keyword_field"),
    )

    id          = Column(Integer, primary_key=True, index=True)
    keyword     = Column(String(200), nullable=False)
    match_field = Column(String(20),  default="item_name")  # item_name/shop_name/brand_raw
    is_active   = Column(SmallInteger, default=1)
    created_by  = Column(String(50))
    created_at  = Column(DateTime, default=datetime.utcnow)


class FilteredItem(Base):
    __tablename__ = "filtered_items"

    id              = Column(Integer, primary_key=True, index=True)
    raw_data_id     = Column(Integer, ForeignKey("raw_data.id"))
    clean_job_id    = Column(Integer, ForeignKey("clean_jobs.id"))
    matched_keyword = Column(String(200))
    is_recovered    = Column(SmallInteger, default=0)
    recovered_at    = Column(DateTime)
    created_at      = Column(DateTime, default=datetime.utcnow)


class BrandAlias(Base):
    __tablename__ = "brand_aliases"

    id          = Column(Integer, primary_key=True, index=True)
    alias_name  = Column(String(200), nullable=False, unique=True)
    brand_code  = Column(String(100), nullable=False)
    is_active   = Column(SmallInteger, default=1)
    created_by  = Column(String(50))
    created_at  = Column(DateTime, default=datetime.utcnow)


class MatchRule(Base):
    __tablename__ = "match_rules"

    id          = Column(Integer, primary_key=True, index=True)
    keyword     = Column(String(200), nullable=False, unique=True)
    match_type  = Column(String(20),  default="contains")  # contains/exact
    model_id    = Column(Integer, ForeignKey("models.id"), nullable=False)
    priority    = Column(Integer, default=100)
    is_active   = Column(SmallInteger, default=1)
    created_by  = Column(String(50))
    created_at  = Column(DateTime, default=datetime.utcnow)
```

- [ ] **Step 3: 给已有模型加字段**

在 `backend/app/models/schemas.py` 中：

1. `CleanedDataRecord` 末尾（`created_at` 行之后）加：
```python
    is_recovered = Column(SmallInteger, default=0)
```

2. `MatchResult` 的 `disable_reason` 行之后加：
```python
    brand_identified = Column(SmallInteger, default=1)
```

3. `CleanJobRecord` 的 `row_out` 行之后加：
```python
    row_filtered = Column(Integer, default=0)
```

4. `CleanJobOut` Pydantic 模型的 `row_out: int` 行之后加：
```python
    row_filtered: int = 0
```

- [ ] **Step 4: 执行迁移**

```bash
docker compose exec backend alembic upgrade head
```

预期输出：
```
INFO  [alembic.runtime.migration] Running upgrade c3d4e5f6a7b8 -> d4e5f6a7b8c9, add rules engine tables
```

- [ ] **Step 5: 验证表已创建**

```bash
docker compose exec db mysql -uluotu -pluotu123 luotu -e "SHOW TABLES LIKE '%noise%'; SHOW TABLES LIKE '%filtered%'; SHOW TABLES LIKE '%brand_alias%'; SHOW TABLES LIKE 'match_rules';"
```

预期：列出 `noise_words`、`filtered_items`、`brand_aliases`、`match_rules` 四张表。

- [ ] **Step 6: Commit**

```bash
git add backend/alembic/versions/d4e5f6a7b8c9_add_rules_engine_tables.py backend/app/models/schemas.py
git commit -m "feat: add rules engine ORM models and migration"
```

---

## Task 2: Rules API — CRUD 接口

**Files:**
- Create: `backend/app/api/rules_api.py`

- [ ] **Step 1: 创建 rules_api.py**

创建 `backend/app/api/rules_api.py`：

```python
"""
规则引擎管理 API
- /api/rules/noise-words     干扰词库
- /api/rules/brand-aliases   品牌写法库
- /api/rules/match-rules     显式匹配规则
- /api/rules/filtered-items  干扰项存档（含恢复）
"""
from datetime import datetime
from typing import Optional

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.models.database import get_db
from app.models.schemas import (
    NoiseWord, FilteredItem, BrandAlias, MatchRule,
    RawDataRecord, CleanedDataRecord, ModelRecord,
)

router = APIRouter(prefix="/api/rules", tags=["rules"])


# ═══════════════════════════════════════════════════════════
# 干扰词库
# ═══════════════════════════════════════════════════════════

class NoiseWordIn(BaseModel):
    keyword: str
    match_field: str = "item_name"  # item_name / shop_name / brand_raw


@router.get("/noise-words")
def list_noise_words(db: Session = Depends(get_db)):
    rows = db.query(NoiseWord).order_by(NoiseWord.created_at.desc()).all()
    return [
        {"id": r.id, "keyword": r.keyword, "match_field": r.match_field,
         "is_active": r.is_active, "created_at": r.created_at}
        for r in rows
    ]


@router.post("/noise-words", status_code=201)
def create_noise_word(body: NoiseWordIn, db: Session = Depends(get_db)):
    if body.match_field not in ("item_name", "shop_name", "brand_raw"):
        raise HTTPException(400, "match_field 必须是 item_name / shop_name / brand_raw")
    existing = db.query(NoiseWord).filter(
        NoiseWord.keyword == body.keyword, NoiseWord.match_field == body.match_field
    ).first()
    if existing:
        raise HTTPException(400, "该关键词已存在")
    row = NoiseWord(keyword=body.keyword, match_field=body.match_field)
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "keyword": row.keyword, "match_field": row.match_field, "is_active": row.is_active}


@router.patch("/noise-words/{nw_id}")
def toggle_noise_word(nw_id: int, db: Session = Depends(get_db)):
    row = db.query(NoiseWord).filter(NoiseWord.id == nw_id).first()
    if not row:
        raise HTTPException(404, "干扰词不存在")
    row.is_active = 0 if row.is_active else 1
    db.commit()
    return {"id": row.id, "is_active": row.is_active}


@router.delete("/noise-words/{nw_id}", status_code=204)
def delete_noise_word(nw_id: int, db: Session = Depends(get_db)):
    row = db.query(NoiseWord).filter(NoiseWord.id == nw_id).first()
    if not row:
        raise HTTPException(404, "干扰词不存在")
    db.delete(row)
    db.commit()


# ═══════════════════════════════════════════════════════════
# 品牌写法库
# ═══════════════════════════════════════════════════════════

class BrandAliasIn(BaseModel):
    alias_name: str
    brand_code: str


@router.get("/brand-aliases")
def list_brand_aliases(db: Session = Depends(get_db)):
    rows = db.query(BrandAlias).order_by(BrandAlias.alias_name).all()
    return [
        {"id": r.id, "alias_name": r.alias_name, "brand_code": r.brand_code,
         "is_active": r.is_active, "created_at": r.created_at}
        for r in rows
    ]


@router.post("/brand-aliases", status_code=201)
def create_brand_alias(body: BrandAliasIn, db: Session = Depends(get_db)):
    if db.query(BrandAlias).filter(BrandAlias.alias_name == body.alias_name).first():
        raise HTTPException(400, "该写法已存在")
    row = BrandAlias(alias_name=body.alias_name.strip(), brand_code=body.brand_code.strip().upper())
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "alias_name": row.alias_name, "brand_code": row.brand_code}


@router.post("/brand-aliases/import")
async def import_brand_aliases(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Excel 批量导入，需两列：alias_name / brand_code"""
    try:
        df = pd.read_excel(file.file, dtype=str)
    except Exception as e:
        raise HTTPException(400, f"Excel 解析失败：{e}")

    df.columns = [c.strip().lower() for c in df.columns]
    if "alias_name" not in df.columns or "brand_code" not in df.columns:
        raise HTTPException(400, "Excel 必须包含列：alias_name、brand_code")

    imported, skipped = 0, 0
    for _, row in df.iterrows():
        alias = str(row["alias_name"]).strip()
        brand = str(row["brand_code"]).strip().upper()
        if not alias or not brand:
            skipped += 1
            continue
        existing = db.query(BrandAlias).filter(BrandAlias.alias_name == alias).first()
        if existing:
            existing.brand_code = brand  # 已存在则更新
        else:
            db.add(BrandAlias(alias_name=alias, brand_code=brand))
        imported += 1

    db.commit()
    return {"imported": imported, "skipped": skipped}


@router.delete("/brand-aliases/{ba_id}", status_code=204)
def delete_brand_alias(ba_id: int, db: Session = Depends(get_db)):
    row = db.query(BrandAlias).filter(BrandAlias.id == ba_id).first()
    if not row:
        raise HTTPException(404, "品牌写法不存在")
    db.delete(row)
    db.commit()


# ═══════════════════════════════════════════════════════════
# 显式匹配规则
# ═══════════════════════════════════════════════════════════

class MatchRuleIn(BaseModel):
    keyword: str
    match_type: str = "contains"  # contains / exact
    model_id: int
    priority: int = 100


class MatchRuleUpdate(BaseModel):
    keyword: Optional[str] = None
    match_type: Optional[str] = None
    model_id: Optional[int] = None
    priority: Optional[int] = None
    is_active: Optional[int] = None


@router.get("/match-rules")
def list_match_rules(db: Session = Depends(get_db)):
    rows = db.query(MatchRule, ModelRecord).join(
        ModelRecord, MatchRule.model_id == ModelRecord.id
    ).order_by(MatchRule.priority).all()
    return [
        {
            "id": mr.id, "keyword": mr.keyword, "match_type": mr.match_type,
            "model_id": mr.model_id, "priority": mr.priority, "is_active": mr.is_active,
            "brand_code": m.brand_code, "model_code": m.model_code,
            "model_name": m.model_name, "created_at": mr.created_at,
        }
        for mr, m in rows
    ]


@router.post("/match-rules", status_code=201)
def create_match_rule(body: MatchRuleIn, db: Session = Depends(get_db)):
    if body.match_type not in ("contains", "exact"):
        raise HTTPException(400, "match_type 必须是 contains 或 exact")
    if not db.query(ModelRecord).filter(ModelRecord.id == body.model_id).first():
        raise HTTPException(404, "型号不存在")
    if db.query(MatchRule).filter(MatchRule.keyword == body.keyword).first():
        raise HTTPException(400, "该关键词规则已存在")
    row = MatchRule(
        keyword=body.keyword.strip(),
        match_type=body.match_type,
        model_id=body.model_id,
        priority=body.priority,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "keyword": row.keyword, "match_type": row.match_type,
            "model_id": row.model_id, "priority": row.priority}


@router.patch("/match-rules/{rule_id}")
def update_match_rule(rule_id: int, body: MatchRuleUpdate, db: Session = Depends(get_db)):
    row = db.query(MatchRule).filter(MatchRule.id == rule_id).first()
    if not row:
        raise HTTPException(404, "规则不存在")
    if body.keyword is not None:
        row.keyword = body.keyword.strip()
    if body.match_type is not None:
        if body.match_type not in ("contains", "exact"):
            raise HTTPException(400, "match_type 必须是 contains 或 exact")
        row.match_type = body.match_type
    if body.model_id is not None:
        if not db.query(ModelRecord).filter(ModelRecord.id == body.model_id).first():
            raise HTTPException(404, "型号不存在")
        row.model_id = body.model_id
    if body.priority is not None:
        row.priority = body.priority
    if body.is_active is not None:
        row.is_active = body.is_active
    db.commit()
    return {"id": row.id, "keyword": row.keyword, "priority": row.priority, "is_active": row.is_active}


@router.delete("/match-rules/{rule_id}", status_code=204)
def delete_match_rule(rule_id: int, db: Session = Depends(get_db)):
    row = db.query(MatchRule).filter(MatchRule.id == rule_id).first()
    if not row:
        raise HTTPException(404, "规则不存在")
    db.delete(row)
    db.commit()


# ═══════════════════════════════════════════════════════════
# 干扰项存档
# ═══════════════════════════════════════════════════════════

@router.get("/filtered-items")
def list_filtered_items(
    clean_job_id: Optional[int] = Query(None),
    keyword: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    q = (
        db.query(FilteredItem, RawDataRecord)
        .join(RawDataRecord, FilteredItem.raw_data_id == RawDataRecord.id)
        .filter(FilteredItem.is_recovered == 0)
    )
    if clean_job_id:
        q = q.filter(FilteredItem.clean_job_id == clean_job_id)
    if keyword:
        q = q.filter(FilteredItem.matched_keyword.ilike(f"%{keyword}%"))

    total = q.count()
    rows = q.order_by(FilteredItem.id.desc()).offset((page - 1) * page_size).limit(page_size).all()

    items = [
        {
            "id": fi.id,
            "raw_data_id": fi.raw_data_id,
            "clean_job_id": fi.clean_job_id,
            "matched_keyword": fi.matched_keyword,
            "item_name": rd.item_name,
            "brand_raw": rd.brand_raw,
            "shop_name": rd.shop_name,
            "created_at": fi.created_at,
        }
        for fi, rd in rows
    ]
    return {"total": total, "page": page, "page_size": page_size, "items": items}


def _recover_one(fi: FilteredItem, db: Session) -> None:
    """将单条 filtered_item 恢复写回 cleaned_data，标记 is_recovered=1"""
    raw = db.query(RawDataRecord).filter(RawDataRecord.id == fi.raw_data_id).first()
    if not raw:
        raise HTTPException(404, f"raw_data_id={fi.raw_data_id} 不存在")

    db.add(CleanedDataRecord(
        raw_data_id=raw.id,
        clean_job_id=fi.clean_job_id,
        platform=raw.platform,
        month=raw.month,
        category_lv1=raw.category_lv1,
        category_lv2=raw.category_lv2,
        category_lv3=raw.category_lv3,
        category_lv4=raw.category_lv4,
        category_lv5=raw.category_lv5,
        item_id=raw.item_id,
        item_url=raw.item_url,
        item_name=raw.item_name,
        item_image=raw.item_image,
        ref_price=raw.ref_price,
        brand_raw=raw.brand_raw,
        shop_name=raw.shop_name,
        sales_qty=raw.sales_qty,
        sales_amount=raw.sales_amount,
        price=raw.price,
        brand_std=raw.brand_std or raw.brand_raw,
        model_std=raw.model_std,
        is_recovered=1,
    ))

    fi.is_recovered = 1
    fi.recovered_at = datetime.utcnow()


@router.post("/filtered-items/{fi_id}/recover")
def recover_filtered_item(fi_id: int, db: Session = Depends(get_db)):
    fi = db.query(FilteredItem).filter(FilteredItem.id == fi_id, FilteredItem.is_recovered == 0).first()
    if not fi:
        raise HTTPException(404, "干扰项不存在或已恢复")
    _recover_one(fi, db)
    db.commit()
    return {"recovered": 1}


class BatchRecoverIn(BaseModel):
    ids: list[int]


@router.post("/filtered-items/recover-batch")
def recover_filtered_items_batch(body: BatchRecoverIn, db: Session = Depends(get_db)):
    rows = db.query(FilteredItem).filter(
        FilteredItem.id.in_(body.ids), FilteredItem.is_recovered == 0
    ).all()
    for fi in rows:
        _recover_one(fi, db)
    db.commit()
    return {"recovered": len(rows)}
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/api/rules_api.py
git commit -m "feat: add rules_api with noise_words/brand_aliases/match_rules/filtered_items endpoints"
```

---

## Task 3: 注册路由

**Files:**
- Modify: `backend/app/main.py`

- [ ] **Step 1: 在 main.py 导入并注册**

在 `backend/app/main.py` 的现有 import 块末尾加：

```python
from app.api import rules_api
```

在 `app.include_router(url_mapping_api.router)` 行之后加：

```python
app.include_router(rules_api.router)
```

- [ ] **Step 2: 验证路由已注册**

```bash
docker compose restart backend
curl -s http://localhost:8000/openapi.json | python3 -c "import sys,json; paths=[p for p in json.load(sys.stdin)['paths'] if '/rules/' in p]; print('\n'.join(paths))"
```

预期：列出 `/api/rules/noise-words`、`/api/rules/brand-aliases` 等路径。

- [ ] **Step 3: Commit**

```bash
git add backend/app/main.py
git commit -m "feat: register rules_api router"
```

---

## Task 4: 测试框架 + 清洗服务测试

**Files:**
- Create: `backend/tests/conftest.py`
- Create: `backend/tests/test_data_cleaner.py`

- [ ] **Step 1: 创建 conftest.py**

创建 `backend/tests/conftest.py`：

```python
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.models.database import Base

TEST_DB_URL = "sqlite:///:memory:"


@pytest.fixture(scope="function")
def db():
    engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    Base.metadata.drop_all(engine)
```

- [ ] **Step 2: 写清洗服务测试（先让测试失败）**

创建 `backend/tests/test_data_cleaner.py`：

```python
"""
测试 data_cleaner.run_clean 的干扰词过滤和品牌写法标准化逻辑。
"""
import pytest
from app.models.schemas import (
    UploadFileRecord, RawDataRecord, CleanJobRecord,
    NoiseWord, BrandAlias, FilteredItem, CleanedDataRecord,
)
from app.services.data_cleaner import run_clean


def _make_raw(db, file_id, item_name, brand_raw="SONY", shop_name="测试店铺"):
    r = RawDataRecord(
        file_id=file_id, platform="jd", month=202507,
        item_name=item_name, brand_raw=brand_raw, shop_name=shop_name,
        item_id=str(id(item_name)), sales_qty=10, price=500,
    )
    db.add(r)
    db.flush()
    return r


def _make_job(db, file_id):
    job = CleanJobRecord(file_ids=[file_id], rules={}, status="done", row_in=0, row_out=0)
    db.add(job)
    db.flush()
    return job


def _make_file(db):
    f = UploadFileRecord(filename="test.xlsx", platform="jd", month_range="202507", row_count=0)
    db.add(f)
    db.flush()
    return f


# ── 干扰词过滤 ──────────────────────────────────────────────

def test_noise_word_filters_matching_item(db):
    """命中干扰词的商品不进入 cleaned_data，进入 filtered_items"""
    f = _make_file(db)
    raw = _make_raw(db, f.id, "索尼HT-A7000 配件包装")
    db.add(NoiseWord(keyword="配件", match_field="item_name"))
    job = _make_job(db, f.id)
    db.commit()

    run_clean(db, job.id, [f.id], {"dedup": True})

    assert db.query(CleanedDataRecord).count() == 0
    fi = db.query(FilteredItem).first()
    assert fi is not None
    assert fi.raw_data_id == raw.id
    assert fi.matched_keyword == "配件"


def test_noise_word_inactive_does_not_filter(db):
    """禁用的干扰词不起作用"""
    f = _make_file(db)
    _make_raw(db, f.id, "索尼HT-A7000 配件包装")
    db.add(NoiseWord(keyword="配件", match_field="item_name", is_active=0))
    job = _make_job(db, f.id)
    db.commit()

    run_clean(db, job.id, [f.id], {"dedup": True})

    assert db.query(CleanedDataRecord).count() == 1
    assert db.query(FilteredItem).count() == 0


def test_noise_word_shop_name_field(db):
    """match_field=shop_name 时匹配店铺名称"""
    f = _make_file(db)
    _make_raw(db, f.id, "索尼HT-A7000", shop_name="官方旗舰店")
    db.add(NoiseWord(keyword="官方旗舰", match_field="shop_name"))
    job = _make_job(db, f.id)
    db.commit()

    run_clean(db, job.id, [f.id], {"dedup": True})

    assert db.query(CleanedDataRecord).count() == 0
    assert db.query(FilteredItem).count() == 1


# ── 品牌写法标准化 ──────────────────────────────────────────

def test_brand_alias_sets_brand_std(db):
    """brand_raw 命中 brand_aliases 时，brand_std 被覆盖为标准品牌码"""
    f = _make_file(db)
    _make_raw(db, f.id, "索尼HT-A7000", brand_raw="索尼")
    db.add(BrandAlias(alias_name="索尼", brand_code="SONY"))
    job = _make_job(db, f.id)
    db.commit()

    run_clean(db, job.id, [f.id], {"dedup": True})

    cleaned = db.query(CleanedDataRecord).first()
    assert cleaned is not None
    assert cleaned.brand_std == "SONY"


def test_brand_alias_case_insensitive(db):
    """品牌写法匹配不区分大小写"""
    f = _make_file(db)
    _make_raw(db, f.id, "博士SoundBar", brand_raw="bose")
    db.add(BrandAlias(alias_name="BOSE", brand_code="BOSE"))
    job = _make_job(db, f.id)
    db.commit()

    run_clean(db, job.id, [f.id], {"dedup": True})

    cleaned = db.query(CleanedDataRecord).first()
    assert cleaned.brand_std == "BOSE"


def test_no_alias_keeps_original_brand_std(db):
    """没有匹配的 brand_alias 时，brand_std 保持原有逻辑（brand_raw 填充）"""
    f = _make_file(db)
    _make_raw(db, f.id, "某品牌音箱", brand_raw="未知品牌")
    job = _make_job(db, f.id)
    db.commit()

    run_clean(db, job.id, [f.id], {"dedup": True})

    cleaned = db.query(CleanedDataRecord).first()
    assert cleaned.brand_std == "未知品牌"


# ── row_filtered 计数 ────────────────────────────────────────

def test_row_filtered_count_in_job(db):
    """CleanJobRecord.row_filtered 记录被过滤的行数"""
    f = _make_file(db)
    _make_raw(db, f.id, "配件A")
    _make_raw(db, f.id, "正常商品B")
    db.add(NoiseWord(keyword="配件", match_field="item_name"))
    job = _make_job(db, f.id)
    db.commit()

    run_clean(db, job.id, [f.id], {"dedup": True})

    db.refresh(job)
    assert job.row_filtered == 1
    assert job.row_out == 1
```

- [ ] **Step 3: 运行测试确认失败**

```bash
docker compose exec backend python -m pytest tests/test_data_cleaner.py -v 2>&1 | head -30
```

预期：多个 `FAILED` —— `run_clean` 还不支持干扰词和品牌写法逻辑。

- [ ] **Step 4: Commit 测试文件**

```bash
git add backend/tests/
git commit -m "test: add data_cleaner tests (currently failing)"
```

---

## Task 5: 改造 data_cleaner.py

**Files:**
- Modify: `backend/app/services/data_cleaner.py`

- [ ] **Step 1: 替换 run_clean 实现**

将 `backend/app/services/data_cleaner.py` 全部内容替换为：

```python
"""
数据清洗服务：
1. 干扰词过滤（noise_words）→ 命中写入 filtered_items，跳过
2. 品牌写法标准化（brand_aliases）→ brand_raw 查表覆盖 brand_std
3. 去重（同 item_id + month + shop_name 保留第一条）
4. brand_std 兜底补全（无匹配时用 brand_raw）
"""
from sqlalchemy.orm import Session
from app.models.schemas import (
    RawDataRecord, CleanedDataRecord, CleanJobRecord,
    NoiseWord, FilteredItem, BrandAlias,
)


def _load_noise_words(db: Session) -> list[tuple[str, str]]:
    """返回 [(keyword_upper, match_field), ...] 只取 active"""
    rows = db.query(NoiseWord).filter(NoiseWord.is_active == 1).all()
    return [(r.keyword.upper(), r.match_field) for r in rows]


def _load_brand_alias_map(db: Session) -> dict[str, str]:
    """返回 {alias_name_upper: brand_code} 只取 active"""
    rows = db.query(BrandAlias).filter(BrandAlias.is_active == 1).all()
    return {r.alias_name.upper(): r.brand_code for r in rows}


def _check_noise(item_name: str | None, shop_name: str | None, brand_raw: str | None,
                 noise_words: list[tuple[str, str]]) -> str | None:
    """若命中干扰词返回该关键词，否则返回 None"""
    field_map = {
        "item_name": (item_name or "").upper(),
        "shop_name": (shop_name or "").upper(),
        "brand_raw": (brand_raw or "").upper(),
    }
    for keyword, field in noise_words:
        if keyword in field_map.get(field, ""):
            return keyword
    return None


def run_clean(db: Session, clean_job_id: int, file_ids: list[int], rules: dict) -> int:
    """执行清洗逻辑，返回写入 cleaned_data 的行数"""
    dedup: bool = rules.get("dedup", True)

    # ── 加载规则表 ─────────────────────────────────────────────
    noise_words = _load_noise_words(db)
    brand_alias_map = _load_brand_alias_map(db)

    records = db.query(RawDataRecord).filter(RawDataRecord.file_id.in_(file_ids)).all()

    cleaned: list[CleanedDataRecord] = []
    filtered: list[FilteredItem] = []
    seen_keys: set = set()

    for r in records:
        # ── Step 1: 干扰词过滤 ───────────────────────────────────
        hit_keyword = _check_noise(r.item_name, r.shop_name, r.brand_raw, noise_words)
        if hit_keyword is not None:
            filtered.append(FilteredItem(
                raw_data_id=r.id,
                clean_job_id=clean_job_id,
                matched_keyword=hit_keyword,
            ))
            continue

        # ── Step 2: 去重 ─────────────────────────────────────────
        if dedup:
            key = (r.item_id, r.month, r.shop_name)
            if key in seen_keys:
                continue
            seen_keys.add(key)

        # ── Step 3: 品牌写法标准化 ───────────────────────────────
        brand_std = r.brand_std  # 原始已有标准品牌码（上传时从 Excel 读取）
        if r.brand_raw:
            alias_hit = brand_alias_map.get(r.brand_raw.upper())
            if alias_hit:
                brand_std = alias_hit
        if not brand_std:
            brand_std = r.brand_raw  # 兜底

        cleaned.append(CleanedDataRecord(
            raw_data_id=r.id,
            clean_job_id=clean_job_id,
            platform=r.platform,
            month=r.month,
            category_lv1=r.category_lv1,
            category_lv2=r.category_lv2,
            category_lv3=r.category_lv3,
            category_lv4=r.category_lv4,
            category_lv5=r.category_lv5,
            item_id=r.item_id,
            item_url=r.item_url,
            item_name=r.item_name,
            item_image=r.item_image,
            ref_price=r.ref_price,
            brand_raw=r.brand_raw,
            shop_name=r.shop_name,
            sales_qty=r.sales_qty,
            sales_amount=r.sales_amount,
            price=r.price,
            brand_std=brand_std,
            model_std=r.model_std,
        ))

    # ── 批量写入 ──────────────────────────────────────────────
    if filtered:
        db.bulk_save_objects(filtered)
    if cleaned:
        db.bulk_save_objects(cleaned)

    # ── 更新 job 统计 ─────────────────────────────────────────
    job = db.query(CleanJobRecord).filter(CleanJobRecord.id == clean_job_id).first()
    if job:
        job.row_in = len(records)
        job.row_out = len(cleaned)
        job.row_filtered = len(filtered)

    db.commit()
    return len(cleaned)
```

- [ ] **Step 2: 运行测试确认通过**

```bash
docker compose exec backend python -m pytest tests/test_data_cleaner.py -v
```

预期：所有测试 `PASSED`。

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/data_cleaner.py
git commit -m "feat: data_cleaner supports noise_words filtering and brand_aliases standardization"
```

---

## Task 6: 改造 matcher.py（S0.5 + brand_identified）

**Files:**
- Create: `backend/tests/test_matcher.py`
- Modify: `backend/app/services/matcher.py`

- [ ] **Step 1: 写 matcher 测试（先让失败）**

创建 `backend/tests/test_matcher.py`：

```python
"""
测试 matcher.run_match 的 S0.5 显式规则和 brand_identified 字段。
"""
from app.models.schemas import (
    UploadFileRecord, RawDataRecord, CleanJobRecord, CleanedDataRecord,
    ModelRecord, MatchResult, MatchRule,
)
from app.services.matcher import run_match


def _setup_base(db):
    """创建最小可用的 model + cleaned_data"""
    model = ModelRecord(brand_code="SONY", model_code="HT-A7000", brand_name="Sony")
    db.add(model)
    f = UploadFileRecord(filename="t.xlsx", platform="jd", month_range="202507", row_count=1)
    db.add(f)
    db.flush()

    raw = RawDataRecord(
        file_id=f.id, platform="jd", month=202507,
        item_name="索尼 HT-A7000 回音壁", brand_raw="索尼",
        item_id="001", sales_qty=5, price=3999,
    )
    db.add(raw)
    db.flush()

    job = CleanJobRecord(file_ids=[f.id], rules={}, status="done", row_in=1, row_out=1)
    db.add(job)
    db.flush()

    cleaned = CleanedDataRecord(
        raw_data_id=raw.id, clean_job_id=job.id,
        platform="jd", month=202507,
        item_name="索尼 HT-A7000 回音壁", brand_raw="索尼",
        item_id="001", sales_qty=5, price=3999, brand_std="SONY",
    )
    db.add(cleaned)
    db.commit()
    return model, job


def test_s05_contains_rule_matches(db):
    """S0.5 contains 规则命中时 match_source 为 s0.5"""
    model, job = _setup_base(db)
    db.add(MatchRule(keyword="HT-A7000", match_type="contains", model_id=model.id, priority=10))
    db.commit()

    run_match(db, job.id)

    result = db.query(MatchResult).filter(MatchResult.clean_job_id == job.id).first()
    assert result is not None
    assert result.match_source == "s0.5"
    assert result.model_id == model.id
    assert result.match_status == "matched"


def test_s05_exact_rule_requires_full_match(db):
    """S0.5 exact 规则只在 item_name 完全等于关键词时命中"""
    model, job = _setup_base(db)
    # exact 规则，但 item_name 只是包含，不完全等于
    db.add(MatchRule(keyword="HT-A7000", match_type="exact", model_id=model.id, priority=10))
    db.commit()

    run_match(db, job.id)

    result = db.query(MatchResult).filter(MatchResult.clean_job_id == job.id).first()
    # 不应命中 exact 规则（item_name 是"索尼 HT-A7000 回音壁"，不等于"HT-A7000"）
    assert result.match_source != "s0.5"


def test_s05_inactive_rule_ignored(db):
    """禁用的规则不参与匹配"""
    model, job = _setup_base(db)
    db.add(MatchRule(keyword="HT-A7000", match_type="contains", model_id=model.id, priority=10, is_active=0))
    db.commit()

    run_match(db, job.id)

    result = db.query(MatchResult).filter(MatchResult.clean_job_id == job.id).first()
    assert result.match_source != "s0.5"


def test_brand_identified_false_when_brand_unknown(db):
    """品牌完全无法识别时 brand_identified=0"""
    model = ModelRecord(brand_code="SONY", model_code="HT-A7000", brand_name="Sony")
    db.add(model)
    f = UploadFileRecord(filename="t.xlsx", platform="jd", month_range="202507", row_count=1)
    db.add(f)
    db.flush()

    raw = RawDataRecord(
        file_id=f.id, platform="jd", month=202507,
        item_name="未知品牌音箱XY999", brand_raw="未知品牌",
        item_id="002", sales_qty=1, price=99,
    )
    db.add(raw)
    db.flush()

    job = CleanJobRecord(file_ids=[f.id], rules={}, status="done", row_in=1, row_out=1)
    db.add(job)
    db.flush()

    cleaned = CleanedDataRecord(
        raw_data_id=raw.id, clean_job_id=job.id,
        platform="jd", month=202507,
        item_name="未知品牌音箱XY999", brand_raw="未知品牌",
        item_id="002", sales_qty=1, price=99, brand_std="未知品牌",
    )
    db.add(cleaned)
    db.commit()

    run_match(db, job.id)

    result = db.query(MatchResult).filter(MatchResult.clean_job_id == job.id).first()
    assert result.brand_identified == 0
```

- [ ] **Step 2: 运行测试确认失败**

```bash
docker compose exec backend python -m pytest tests/test_matcher.py -v 2>&1 | head -20
```

预期：`FAILED`。

- [ ] **Step 3: 更新 matcher.py 添加 S0.5 和 brand_identified**

在 `backend/app/services/matcher.py` 中做以下改动：

**a) 在 import 行加入 MatchRule：**

```python
from app.models.schemas import CleanedDataRecord, ModelRecord, ModelAlias, MatchResult, ItemUrlMapping, MatchRule
```

**b) 在 `run_match` 函数内，`# ── S0: 预加载 URL 映射表` 代码块之后，`# ── 构建内存索引` 之前，插入 S0.5 规则预加载：**

```python
    # ── S0.5: 预加载显式匹配规则（按 priority 升序）────────────────
    explicit_rules = (
        db.query(MatchRule)
        .filter(MatchRule.is_active == 1)
        .order_by(MatchRule.priority)
        .all()
    )
```

**c) 在 `for i, row in enumerate(cleaned_rows):` 循环内，`# ── S0: URL精确匹配` 代码块末尾的 `continue` 之后，`# ── S1-S4 文本匹配` 注释之前，插入 S0.5 逻辑：**

```python
        # ── S0.5: 显式规则匹配 ─────────────────────────────────
        s05_model_id: int | None = None
        for rule in explicit_rules:
            kw = rule.keyword.upper()
            if rule.match_type == "exact":
                if item_upper == kw:
                    s05_model_id = rule.model_id
                    break
            else:  # contains
                if kw in item_upper:
                    s05_model_id = rule.model_id
                    break

        if s05_model_id is not None:
            status = "text_only" if url_info else "matched"
            results.append(MatchResult(
                clean_job_id=clean_job_id,
                raw_data_id=row.raw_data_id,
                model_id=s05_model_id,
                match_status=status,
                matched_by="auto",
                match_source="s0.5",
                brand_identified=1,
            ))
            matched_count += 1
            if len(results) >= BATCH:
                db.bulk_save_objects(results)
                db.commit()
                if progress_cb:
                    progress_cb(i + 1, total, matched_count)
                results = []
            continue  # 跳过 S1-S4
```

**d) 改造 S1-S4 部分：在变量 `brand_identified = False` 初始化之后，在写入 `MatchResult` 时加入 `brand_identified` 字段。**

将 S1-S4 文本匹配段中的 `brand_identified` 变量改为追踪：

```python
        # ── S1-S4 文本匹配 ─────────────────────────────────────
        best_model: ModelRecord | None = None
        brand_identified = False  # 已有，不变
        match_source: str | None = None
```

在最后写入 `MatchResult` 的两处（matched 和 pending），分别加 `brand_identified` 字段：

```python
        if best_model:
            status = "text_only" if url_info else "matched"
            results.append(MatchResult(
                clean_job_id=clean_job_id,
                raw_data_id=row.raw_data_id,
                model_id=best_model.id,
                match_status=status,
                matched_by="auto",
                match_source=match_source,
                brand_identified=1 if brand_identified else 0,  # ← 新增
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
                brand_identified=1 if brand_identified else 0,  # ← 新增
            ))
```

- [ ] **Step 4: 运行测试确认通过**

```bash
docker compose exec backend python -m pytest tests/test_matcher.py -v
```

预期：所有测试 `PASSED`。

- [ ] **Step 5: 运行全部测试确认无回归**

```bash
docker compose exec backend python -m pytest tests/ -v
```

预期：全部 `PASSED`。

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/matcher.py backend/tests/test_matcher.py
git commit -m "feat: matcher adds S0.5 explicit rules and brand_identified field"
```

---

## Task 7: 前端 api.ts 新增函数

**Files:**
- Modify: `frontend/src/services/api.ts`

- [ ] **Step 1: 在 api.ts 末尾追加规则相关 API 函数**

```typescript
// ─── Rules - Noise Words ────────────────────────────────────
export const listNoiseWords = () =>
  api.get('/rules/noise-words')

export const createNoiseWord = (payload: { keyword: string; match_field: string }) =>
  api.post('/rules/noise-words', payload)

export const toggleNoiseWord = (id: number) =>
  api.patch(`/rules/noise-words/${id}`)

export const deleteNoiseWord = (id: number) =>
  api.delete(`/rules/noise-words/${id}`)

// ─── Rules - Brand Aliases ──────────────────────────────────
export const listBrandAliases = () =>
  api.get('/rules/brand-aliases')

export const createBrandAlias = (payload: { alias_name: string; brand_code: string }) =>
  api.post('/rules/brand-aliases', payload)

export const importBrandAliases = (formData: FormData) =>
  api.post('/rules/brand-aliases/import', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })

export const deleteBrandAlias = (id: number) =>
  api.delete(`/rules/brand-aliases/${id}`)

// ─── Rules - Match Rules ────────────────────────────────────
export const listMatchRules = () =>
  api.get('/rules/match-rules')

export const createMatchRule = (payload: {
  keyword: string; match_type: string; model_id: number; priority: number
}) => api.post('/rules/match-rules', payload)

export const updateMatchRule = (id: number, payload: Record<string, unknown>) =>
  api.patch(`/rules/match-rules/${id}`, payload)

export const deleteMatchRule = (id: number) =>
  api.delete(`/rules/match-rules/${id}`)

// ─── Rules - Filtered Items ─────────────────────────────────
export const listFilteredItems = (params: Record<string, unknown>) =>
  api.get('/rules/filtered-items', { params })

export const recoverFilteredItem = (id: number) =>
  api.post(`/rules/filtered-items/${id}/recover`)

export const recoverFilteredItemsBatch = (ids: number[]) =>
  api.post('/rules/filtered-items/recover-batch', { ids })
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/services/api.ts
git commit -m "feat: add rules API functions to api.ts"
```

---

## Task 8: 前端规则管理页面

**Files:**
- Create: `frontend/src/pages/Rules/index.tsx`

- [ ] **Step 1: 创建 Rules 页面**

创建 `frontend/src/pages/Rules/index.tsx`：

```tsx
import { useState } from 'react'
import {
  Tabs, Card, Table, Button, Input, Select, Space, Popconfirm,
  Upload, Modal, Form, InputNumber, Tag, message, Alert,
} from 'antd'
import {
  PlusOutlined, DeleteOutlined, UploadOutlined,
  CheckCircleOutlined, StopOutlined,
} from '@ant-design/icons'
import { useRequest } from 'ahooks'
import {
  listNoiseWords, createNoiseWord, toggleNoiseWord, deleteNoiseWord,
  listBrandAliases, createBrandAlias, importBrandAliases, deleteBrandAlias,
  listMatchRules, createMatchRule, updateMatchRule, deleteMatchRule,
  listFilteredItems, recoverFilteredItem, recoverFilteredItemsBatch,
  listCleanJobs, listModels,
} from '../../services/api'

// ══════════════════════════════════════════════
// Tab 1: 干扰词库
// ══════════════════════════════════════════════
function NoiseWordTab() {
  const [keyword, setKeyword] = useState('')
  const [matchField, setMatchField] = useState('item_name')
  const [adding, setAdding] = useState(false)
  const { data, loading, refresh } = useRequest(() => listNoiseWords().then(r => r.data))

  const handleAdd = async () => {
    if (!keyword.trim()) { message.warning('请输入关键词'); return }
    setAdding(true)
    try {
      await createNoiseWord({ keyword: keyword.trim(), match_field: matchField })
      message.success('添加成功')
      setKeyword('')
      refresh()
    } finally { setAdding(false) }
  }

  const columns = [
    { title: '关键词', dataIndex: 'keyword', ellipsis: true },
    { title: '匹配字段', dataIndex: 'match_field', width: 120,
      render: (v: string) => ({ item_name: '商品名称', shop_name: '店铺名称', brand_raw: '原始品牌' }[v] ?? v) },
    { title: '状态', dataIndex: 'is_active', width: 80,
      render: (v: number) => v ? <Tag color="green">启用</Tag> : <Tag color="default">禁用</Tag> },
    {
      title: '操作', width: 120,
      render: (_: unknown, row: { id: number; is_active: number }) => (
        <Space size={4}>
          <Button size="small" icon={row.is_active ? <StopOutlined /> : <CheckCircleOutlined />}
            onClick={async () => { await toggleNoiseWord(row.id); refresh() }}>
            {row.is_active ? '禁用' : '启用'}
          </Button>
          <Popconfirm title="确认删除？" onConfirm={async () => { await deleteNoiseWord(row.id); refresh() }}>
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      <Alert type="info" showIcon message="命中干扰词的商品将被移入「干扰项存档」，不进入清洗数据。支持禁用（不删除），方便排查误过滤。" />
      <Space wrap>
        <Input placeholder="输入干扰关键词" value={keyword} onChange={e => setKeyword(e.target.value)}
          onPressEnter={handleAdd} style={{ width: 220 }} />
        <Select value={matchField} onChange={setMatchField} style={{ width: 130 }}
          options={[
            { value: 'item_name', label: '商品名称' },
            { value: 'shop_name', label: '店铺名称' },
            { value: 'brand_raw', label: '原始品牌' },
          ]} />
        <Button type="primary" icon={<PlusOutlined />} loading={adding} onClick={handleAdd}>添加</Button>
      </Space>
      <Table dataSource={data ?? []} columns={columns} rowKey="id" size="small" loading={loading}
        pagination={{ pageSize: 20, showTotal: t => `共 ${t} 条` }} />
    </Space>
  )
}

// ══════════════════════════════════════════════
// Tab 2: 品牌写法库
// ══════════════════════════════════════════════
function BrandAliasTab() {
  const [aliasName, setAliasName] = useState('')
  const [brandCode, setBrandCode] = useState('')
  const [adding, setAdding] = useState(false)
  const { data, loading, refresh } = useRequest(() => listBrandAliases().then(r => r.data))

  const handleAdd = async () => {
    if (!aliasName.trim() || !brandCode.trim()) { message.warning('请填写写法和品牌码'); return }
    setAdding(true)
    try {
      await createBrandAlias({ alias_name: aliasName.trim(), brand_code: brandCode.trim() })
      message.success('添加成功')
      setAliasName(''); setBrandCode('')
      refresh()
    } finally { setAdding(false) }
  }

  const handleImport = async (file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    try {
      const res = await importBrandAliases(fd)
      message.success(`导入完成：${res.data.imported} 条，跳过 ${res.data.skipped} 条`)
      refresh()
    } catch { /* handled by interceptor */ }
    return false
  }

  const columns = [
    { title: '原始写法', dataIndex: 'alias_name' },
    { title: '标准品牌码', dataIndex: 'brand_code', width: 140 },
    {
      title: '操作', width: 80,
      render: (_: unknown, row: { id: number }) => (
        <Popconfirm title="确认删除？" onConfirm={async () => { await deleteBrandAlias(row.id); refresh() }}>
          <Button size="small" danger icon={<DeleteOutlined />} />
        </Popconfirm>
      ),
    },
  ]

  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      <Alert type="info" showIcon message="清洗时 brand_raw 命中写法后自动替换为标准品牌码，提升后续匹配准确率。" />
      <Space wrap>
        <Input placeholder="原始写法（如：索尼）" value={aliasName} onChange={e => setAliasName(e.target.value)}
          style={{ width: 180 }} />
        <Input placeholder="标准品牌码（如：SONY）" value={brandCode} onChange={e => setBrandCode(e.target.value)}
          style={{ width: 180 }} onPressEnter={handleAdd} />
        <Button type="primary" icon={<PlusOutlined />} loading={adding} onClick={handleAdd}>添加</Button>
        <Upload beforeUpload={handleImport} showUploadList={false} accept=".xlsx,.xls">
          <Button icon={<UploadOutlined />}>Excel 批量导入</Button>
        </Upload>
      </Space>
      <Table dataSource={data ?? []} columns={columns} rowKey="id" size="small" loading={loading}
        pagination={{ pageSize: 20, showTotal: t => `共 ${t} 条` }} />
    </Space>
  )
}

// ══════════════════════════════════════════════
// Tab 3: 匹配规则
// ══════════════════════════════════════════════
function MatchRuleTab() {
  const [modalOpen, setModalOpen] = useState(false)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [form] = Form.useForm()
  const { data, loading, refresh } = useRequest(() => listMatchRules().then(r => r.data))
  const { data: modelsData } = useRequest(() => listModels({ page: 1, page_size: 500 }).then(r => r.data))
  const modelOptions = (modelsData?.items ?? []).map((m: { id: number; brand_code: string; model_code: string; model_name: string | null }) => ({
    value: m.id,
    label: `[${m.brand_code}] ${m.model_code}${m.model_name ? ' ' + m.model_name : ''}`,
  }))

  const openCreate = () => { setEditingId(null); form.resetFields(); setModalOpen(true) }
  const openEdit = (row: { id: number; keyword: string; match_type: string; model_id: number; priority: number }) => {
    setEditingId(row.id)
    form.setFieldsValue({ keyword: row.keyword, match_type: row.match_type, model_id: row.model_id, priority: row.priority })
    setModalOpen(true)
  }

  const handleSubmit = async () => {
    const vals = await form.validateFields()
    if (editingId) {
      await updateMatchRule(editingId, vals)
      message.success('更新成功')
    } else {
      await createMatchRule(vals)
      message.success('添加成功')
    }
    setModalOpen(false)
    refresh()
  }

  const columns = [
    { title: '优先级', dataIndex: 'priority', width: 80, sorter: (a: { priority: number }, b: { priority: number }) => a.priority - b.priority },
    { title: '关键词', dataIndex: 'keyword', ellipsis: true },
    { title: '匹配方式', dataIndex: 'match_type', width: 100,
      render: (v: string) => <Tag color={v === 'exact' ? 'blue' : 'cyan'}>{v === 'exact' ? '精准' : '包含'}</Tag> },
    { title: '品牌码', dataIndex: 'brand_code', width: 100 },
    { title: '型号码', dataIndex: 'model_code', width: 120 },
    { title: '状态', dataIndex: 'is_active', width: 80,
      render: (v: number) => v ? <Tag color="green">启用</Tag> : <Tag color="default">禁用</Tag> },
    {
      title: '操作', width: 130,
      render: (_: unknown, row: { id: number; keyword: string; match_type: string; model_id: number; priority: number; is_active: number }) => (
        <Space size={4}>
          <Button size="small" onClick={() => openEdit(row)}>编辑</Button>
          <Button size="small" onClick={async () => {
            await updateMatchRule(row.id, { is_active: row.is_active ? 0 : 1 }); refresh()
          }}>{row.is_active ? '禁用' : '启用'}</Button>
          <Popconfirm title="确认删除？" onConfirm={async () => { await deleteMatchRule(row.id); refresh() }}>
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <>
      <Space direction="vertical" size={12} style={{ width: '100%' }}>
        <Alert type="info" showIcon
          message="S0.5 层：优先级数字越小越先执行。命中后直接出结果，跳过 S1-S4 算法。建议关键词长度 ≥ 5 字符（使用「精准」模式除外）。" />
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新增规则</Button>
        <Table dataSource={data ?? []} columns={columns} rowKey="id" size="small" loading={loading}
          pagination={{ pageSize: 20, showTotal: t => `共 ${t} 条` }} />
      </Space>

      <Modal title={editingId ? '编辑规则' : '新增规则'} open={modalOpen}
        onOk={handleSubmit} onCancel={() => setModalOpen(false)} okText="保存" cancelText="取消">
        <Form form={form} layout="vertical" style={{ marginTop: 8 }}>
          <Form.Item label="关键词" name="keyword" rules={[{ required: true, message: '请输入关键词' }]}>
            <Input placeholder="在商品名称中匹配的关键词" />
          </Form.Item>
          <Form.Item label="匹配方式" name="match_type" initialValue="contains">
            <Select options={[{ value: 'contains', label: '包含（商品名称包含该词）' }, { value: 'exact', label: '精准（商品名称完全等于该词）' }]} />
          </Form.Item>
          <Form.Item label="目标型号" name="model_id" rules={[{ required: true, message: '请选择型号' }]}>
            <Select showSearch placeholder="搜索品牌/型号码" options={modelOptions}
              filterOption={(input, option) =>
                (option?.label as string ?? '').toLowerCase().includes(input.toLowerCase())} />
          </Form.Item>
          <Form.Item label="优先级" name="priority" initialValue={100}>
            <InputNumber min={1} max={9999} style={{ width: '100%' }} />
          </Form.Item>
        </Form>
      </Modal>
    </>
  )
}

// ══════════════════════════════════════════════
// Tab 4: 干扰项存档
// ══════════════════════════════════════════════
function FilteredItemTab() {
  const [jobId, setJobId] = useState<number | undefined>()
  const [keyword, setKeyword] = useState('')
  const [page, setPage] = useState(1)
  const [selectedIds, setSelectedIds] = useState<number[]>([])

  const { data: jobsData } = useRequest(() => listCleanJobs().then(r => r.data))
  const { data, loading, refresh } = useRequest(
    () => listFilteredItems({ clean_job_id: jobId, keyword: keyword || undefined, page, page_size: 20 }).then(r => r.data),
    { refreshDeps: [jobId, keyword, page] }
  )

  const handleRecover = async (id: number) => {
    await recoverFilteredItem(id)
    message.success('已恢复')
    refresh()
  }

  const handleBatchRecover = async () => {
    if (!selectedIds.length) { message.warning('请先勾选数据'); return }
    await recoverFilteredItemsBatch(selectedIds)
    message.success(`已恢复 ${selectedIds.length} 条`)
    setSelectedIds([])
    refresh()
  }

  const columns = [
    { title: '商品名称', dataIndex: 'item_name', ellipsis: true },
    { title: '原始品牌', dataIndex: 'brand_raw', width: 120 },
    { title: '触发词', dataIndex: 'matched_keyword', width: 150 },
    { title: '清洗任务', dataIndex: 'clean_job_id', width: 90 },
    {
      title: '操作', width: 80,
      render: (_: unknown, row: { id: number }) => (
        <Button size="small" type="link" onClick={() => handleRecover(row.id)}>恢复</Button>
      ),
    },
  ]

  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      <Alert type="warning" showIcon message="恢复后数据将重新进入清洗数据集，可在匹配页对其执行型号匹配。" />
      <Space wrap>
        <Select allowClear placeholder="筛选清洗任务" style={{ width: 200 }}
          value={jobId} onChange={v => { setJobId(v); setPage(1) }}
          options={(jobsData ?? []).map((j: { id: number; created_at: string }) => ({
            value: j.id, label: `任务 #${j.id}（${new Date(j.created_at).toLocaleDateString('zh-CN')}）`
          }))} />
        <Input.Search placeholder="搜索触发词" allowClear style={{ width: 200 }}
          onSearch={v => { setKeyword(v); setPage(1) }} />
        <Button onClick={handleBatchRecover} disabled={!selectedIds.length}>
          批量恢复（{selectedIds.length}）
        </Button>
      </Space>
      <Table
        dataSource={data?.items ?? []} columns={columns} rowKey="id" size="small" loading={loading}
        rowSelection={{ selectedRowKeys: selectedIds, onChange: keys => setSelectedIds(keys as number[]) }}
        pagination={{ current: page, total: data?.total ?? 0, pageSize: 20,
          onChange: setPage, showTotal: t => `共 ${t} 条` }}
      />
    </Space>
  )
}

// ══════════════════════════════════════════════
// 主页面
// ══════════════════════════════════════════════
export default function RulesPage() {
  const [activeTab, setActiveTab] = useState('noise')

  return (
    <Card>
      <Tabs
        activeKey={activeTab}
        onChange={setActiveTab}
        items={[
          { key: 'noise',    label: '干扰词库',   children: <NoiseWordTab /> },
          { key: 'brand',    label: '品牌写法库', children: <BrandAliasTab /> },
          { key: 'rules',    label: '匹配规则',   children: <MatchRuleTab /> },
          { key: 'filtered', label: '干扰项存档', children: <FilteredItemTab /> },
        ]}
      />
    </Card>
  )
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/pages/Rules/index.tsx
git commit -m "feat: add Rules management page with 4 tabs"
```

---

## Task 9: 前端路由 + 导航

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/Layout/index.tsx`

- [ ] **Step 1: App.tsx 新增路由**

在 `frontend/src/App.tsx` 中：

在 import 块加：
```tsx
import RulesPage from './pages/Rules'
```

在 `<Route path="/clean" element={<CleanPage />} />` 行之后加：
```tsx
<Route path="/rules" element={<RulesPage />} />
```

- [ ] **Step 2: Layout 导航加入口**

在 `frontend/src/components/Layout/index.tsx` 中：

在 import 的图标列表加 `FilterOutlined`：
```tsx
import {
  ...
  FilterOutlined,
} from '@ant-design/icons'
```

在 `menuItems` 数组的 `{ key: '/clean', ... }` 之后插入：
```tsx
  { key: '/rules', icon: <FilterOutlined />, label: '规则管理' },
```

- [ ] **Step 3: 验证页面可访问**

```bash
# 前端已启动的情况下访问
open http://localhost:5173/rules
```

预期：显示「规则管理」页面，4 个 Tab 正常渲染，列表为空。

- [ ] **Step 4: Commit**

```bash
git add frontend/src/App.tsx frontend/src/components/Layout/index.tsx
git commit -m "feat: add /rules route and navigation entry"
```

---

## Task 10: Match 页面新增「未识别品牌」Tab

**Files:**
- Modify: `frontend/src/pages/Match/index.tsx`

- [ ] **Step 1: 更新 listPendingMatches 类型和 API 调用**

`match/index.tsx` 中 `activeTab` 的类型声明从：
```tsx
const [activeTab, setActiveTab] = useState<'pending' | 'text_only'>('text_only')
```
改为：
```tsx
const [activeTab, setActiveTab] = useState<'pending' | 'text_only' | 'unidentified_brand'>('text_only')
```

- [ ] **Step 2: 在 `listPendingMatches` 请求的 `ready` 条件中加入 unidentified_brand**

将：
```tsx
  ready: selectedJobId != null && summary != null && (summary.pending > 0 || summary.text_only > 0),
```
改为：
```tsx
  ready: selectedJobId != null && summary != null &&
    (summary.pending > 0 || summary.text_only > 0 || (summary.unidentified_brand ?? 0) > 0),
```

- [ ] **Step 3: 在 MatchSummary 类型和 summary stats card 加 unidentified_brand**

`MatchSummary` 类型加：
```tsx
  unidentified_brand?: number
```

统计卡片的 `已禁用` Col 之后加：
```tsx
<Col span={3}>
  <Statistic
    title="未识别品牌"
    value={summary?.unidentified_brand ?? 0}
    valueStyle={{ color: '#722ed1' }}
  />
</Col>
```

- [ ] **Step 4: 添加「未识别品牌」Tab**

在 `Tabs` 的 `items` 数组首部加：
```tsx
{
  key: 'unidentified_brand',
  label: (
    <span>
      未识别品牌
      {(summary?.unidentified_brand ?? 0) > 0 && (
        <span style={{
          marginLeft: 6, background: '#722ed1', color: '#fff',
          borderRadius: 10, padding: '0 6px', fontSize: 11,
        }}>
          {summary?.unidentified_brand}
        </span>
      )}
    </span>
  ),
  children: null,
},
```

Tab 内容区（`<Table>` 上方）加提示 Banner：
```tsx
{activeTab === 'unidentified_brand' && (
  <Alert
    type="warning"
    showIcon
    style={{ marginBottom: 12 }}
    message={
      <span>
        以下商品的品牌在系统中未能识别，建议先前往「规则管理 → 品牌写法库」补充写法后重新执行匹配，效率高于逐条人工确认。
        <Button type="link" size="small" onClick={() => window.open('/rules', '_blank')}>前往规则管理 →</Button>
      </span>
    }
  />
)}
```

- [ ] **Step 5: 后端补充 unidentified_brand 统计**

在 `backend/app/api/match_api.py` 的 `get_match_summary` 函数中，`disabled_count` 计算之后加：

```python
    unidentified_brand_count = sum(1 for r in rows if r.brand_identified == 0 and r.match_status == "pending")
```

并在 `return MatchSummary(...)` 中加：
```python
        unidentified_brand=unidentified_brand_count,
```

同时在 `backend/app/models/schemas.py` 的 `MatchSummary` Pydantic 模型加：
```python
    unidentified_brand: int = 0
```

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/Match/index.tsx backend/app/api/match_api.py backend/app/models/schemas.py
git commit -m "feat: match page adds unidentified_brand tab and stats"
```

---

## Task 11: Clean 页面展示 filtered_count

**Files:**
- Modify: `frontend/src/pages/Clean/index.tsx`

- [ ] **Step 1: 找到清洗结果卡片，加 filtered_count 显示**

在 `frontend/src/pages/Clean/index.tsx` 中找到展示 `row_in` / `row_out` 的统计卡片区域，加第三个统计项：

```tsx
<Col span={6}>
  <Statistic
    title="被过滤（干扰词）"
    value={job.row_filtered ?? 0}
    valueStyle={{ color: '#d48806' }}
    suffix={
      (job.row_filtered ?? 0) > 0
        ? <a style={{ fontSize: 12, marginLeft: 4 }}
            onClick={() => window.open(`/rules?tab=filtered&job_id=${job.id}`, '_blank')}>
            查看 →
          </a>
        : null
    }
  />
</Col>
```

如果 `CleanJob` 类型中没有 `row_filtered`，在该文件的类型定义中加：
```tsx
row_filtered?: number
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/pages/Clean/index.tsx
git commit -m "feat: clean page shows filtered_count with link to filtered items"
```

---

## Task 12: 端到端验证

- [ ] **Step 1: 重启服务，运行全量测试**

```bash
docker compose restart backend
docker compose exec backend python -m pytest tests/ -v
```

预期：所有测试 `PASSED`，无报错。

- [ ] **Step 2: 手动验证干扰词流程**

```bash
# 1. 添加干扰词
curl -s -X POST http://localhost:8000/api/rules/noise-words \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -d '{"keyword": "配件", "match_field": "item_name"}' | python3 -m json.tool

# 2. 对已有数据执行清洗，确认 filtered_count > 0
# 3. 在 /rules?tab=filtered 页面确认干扰项可见
# 4. 点击恢复，确认数据回到 cleaned_data
```

- [ ] **Step 3: 手动验证匹配规则流程**

```bash
# 1. 在 /rules?tab=rules 添加一条规则
# 2. 对清洗数据重新执行匹配
# 3. 在 /match 确认该商品 match_source = s0.5
```

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "feat: rules engine phase 1 complete - noise words, brand aliases, match rules, filtered items"
```
