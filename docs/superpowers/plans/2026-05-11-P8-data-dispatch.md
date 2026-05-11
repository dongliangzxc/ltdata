# P8 数据分发 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在原始数据上传后，提供「数据分发」功能，按预设规则将数据自动打标分配到各品类桶；清洗阶段可按品类过滤数据源，支持多分析师按品类独立工作。

**Architecture:** 新增三张表（`dispatch_rules` / `dispatch_batches` / `dispatch_items`）存储规则与分发结果；`clean_jobs` 表加两列关联分发批次和品类；后端新增 `dispatch_api.py` 并修改 `data_cleaner.py`；前端新增 `Dispatch` 页面并修改 `Clean` 页面增加品类选择器。

**Tech Stack:** Python/FastAPI, SQLAlchemy ORM, Alembic migrations, React 18, Ant Design 5, ahooks `useRequest`, TypeScript

---

## File Map

| 文件 | 操作 | 说明 |
|---|---|---|
| `backend/alembic/versions/p8a1b2c3d4e5_dispatch.py` | 新建 | 3张新表 + clean_jobs 加2列 |
| `backend/app/models/schemas.py` | 修改 | 新增 DispatchRule / DispatchBatch / DispatchItem ORM + Pydantic；CleanJobRecord 加2列 |
| `backend/app/api/dispatch_api.py` | 新建 | 7个接口：run/batches/stats/rules CRUD |
| `backend/app/api/clean.py` | 修改 | run_clean_job 接受可选 dispatch 参数 |
| `backend/app/services/data_cleaner.py` | 修改 | run_clean 支持 dispatch_items 过滤数据源 |
| `backend/app/main.py` | 修改 | 注册 dispatch_api router |
| `sql/init.sql` | 修改 | 新增3张表；clean_jobs 加2列 |
| `frontend/src/services/api.ts` | 修改 | 新增 dispatch 相关函数；修改 runCleanJob 签名 |
| `frontend/src/pages/Dispatch/index.tsx` | 新建 | 分发管理（Tab1）+ 规则管理（Tab2） |
| `frontend/src/pages/Clean/index.tsx` | 修改 | 选文件后检查分发批次，显示品类选择器 |
| `frontend/src/App.tsx` | 修改 | 注册 `/dispatch` 路由 |
| `frontend/src/components/Layout/index.tsx` | 修改 | 菜单加「数据分发」项 |

---

## Task 1: Alembic Migration

**Files:**
- Create: `backend/alembic/versions/p8a1b2c3d4e5_dispatch.py`

- [ ] **Step 1: 写 migration 文件**

```python
"""P8 — data dispatch tables

Revision ID: p8a1b2c3d4e5
Revises: p7a1b2c3d4e5
Create Date: 2026-05-11
"""
from alembic import op
import sqlalchemy as sa

revision = 'p8a1b2c3d4e5'
down_revision = 'p7a1b2c3d4e5'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'dispatch_rules',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('category_code', sa.String(50), nullable=False),
        sa.Column('platform', sa.String(50), nullable=True),
        sa.Column('field', sa.String(50), nullable=False),
        sa.Column('match_type', sa.String(20), nullable=False),
        sa.Column('value', sa.String(200), nullable=False),
        sa.Column('item_name_keyword', sa.String(200), nullable=True),
        sa.Column('priority', sa.Integer, nullable=False, server_default='100'),
        sa.Column('is_active', sa.Boolean, nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
    )
    op.create_index('ix_dispatch_rules_category_code', 'dispatch_rules', ['category_code'])
    op.create_index('ix_dispatch_rules_priority', 'dispatch_rules', ['priority'])

    op.create_table(
        'dispatch_batches',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('file_id', sa.Integer, sa.ForeignKey('upload_files.id'), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='running'),
        sa.Column('total_rows', sa.Integer, nullable=True),
        sa.Column('dispatched_rows', sa.Integer, nullable=True),
        sa.Column('unmatched_rows', sa.Integer, nullable=True),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
        sa.Column('finished_at', sa.DateTime, nullable=True),
    )
    op.create_index('ix_dispatch_batches_file_id', 'dispatch_batches', ['file_id'])

    op.create_table(
        'dispatch_items',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('batch_id', sa.Integer, sa.ForeignKey('dispatch_batches.id', ondelete='CASCADE'), nullable=False),
        sa.Column('raw_data_id', sa.Integer, sa.ForeignKey('raw_data.id', ondelete='CASCADE'), nullable=False),
        sa.Column('category_code', sa.String(50), nullable=False),
        sa.Column('matched_rule_id', sa.Integer, nullable=True),
        sa.UniqueConstraint('batch_id', 'raw_data_id', name='uq_dispatch_items_batch_row'),
    )
    op.create_index('ix_dispatch_items_batch_id', 'dispatch_items', ['batch_id'])
    op.create_index('ix_dispatch_items_category_code', 'dispatch_items', ['category_code'])

    op.add_column('clean_jobs', sa.Column('dispatch_batch_id', sa.Integer, nullable=True))
    op.add_column('clean_jobs', sa.Column('dispatch_category_code', sa.String(50), nullable=True))


def downgrade():
    op.drop_column('clean_jobs', 'dispatch_category_code')
    op.drop_column('clean_jobs', 'dispatch_batch_id')
    op.drop_index('ix_dispatch_items_category_code', table_name='dispatch_items')
    op.drop_index('ix_dispatch_items_batch_id', table_name='dispatch_items')
    op.drop_table('dispatch_items')
    op.drop_index('ix_dispatch_batches_file_id', table_name='dispatch_batches')
    op.drop_table('dispatch_batches')
    op.drop_index('ix_dispatch_rules_priority', table_name='dispatch_rules')
    op.drop_index('ix_dispatch_rules_category_code', table_name='dispatch_rules')
    op.drop_table('dispatch_rules')
```

- [ ] **Step 2: 验证 migration 文件语法**

```bash
cd backend
python -c "import alembic.versions.p8a1b2c3d4e5_dispatch; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/alembic/versions/p8a1b2c3d4e5_dispatch.py
git commit -m "feat(p8): add alembic migration for dispatch tables"
```

---

## Task 2: ORM Models + Pydantic Schemas

**Files:**
- Modify: `backend/app/models/schemas.py`

- [ ] **Step 1: 在 schemas.py 中追加 ORM 模型**

在文件末尾（所有现有 ORM 之后）追加：

```python
# ─── P8: Dispatch Tables ──────────────────────────────────────

class DispatchRule(Base):
    __tablename__ = "dispatch_rules"

    id = Column(Integer, primary_key=True, index=True)
    category_code = Column(String(50), nullable=False, index=True)
    platform = Column(String(50), nullable=True)
    field = Column(String(50), nullable=False)
    match_type = Column(String(20), nullable=False)
    value = Column(String(200), nullable=False)
    item_name_keyword = Column(String(200), nullable=True)
    priority = Column(Integer, nullable=False, default=100)
    is_active = Column(SmallInteger, nullable=False, default=1)
    created_at = Column(DateTime, default=datetime.utcnow)


class DispatchBatch(Base):
    __tablename__ = "dispatch_batches"

    id = Column(Integer, primary_key=True, index=True)
    file_id = Column(Integer, ForeignKey("upload_files.id"), nullable=False)
    status = Column(String(20), nullable=False, default="running")
    total_rows = Column(Integer, nullable=True)
    dispatched_rows = Column(Integer, nullable=True)
    unmatched_rows = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)

    file = relationship("UploadFileRecord")
    items = relationship("DispatchItem", back_populates="batch", cascade="all, delete-orphan")


class DispatchItem(Base):
    __tablename__ = "dispatch_items"

    id = Column(Integer, primary_key=True, index=True)
    batch_id = Column(Integer, ForeignKey("dispatch_batches.id", ondelete="CASCADE"), nullable=False, index=True)
    raw_data_id = Column(Integer, ForeignKey("raw_data.id", ondelete="CASCADE"), nullable=False)
    category_code = Column(String(50), nullable=False, index=True)
    matched_rule_id = Column(Integer, nullable=True)

    batch = relationship("DispatchBatch", back_populates="items")
```

- [ ] **Step 2: 修改 CleanJobRecord，添加两列**

找到 `CleanJobRecord` 类（第 59-71 行），在 `row_filtered` 列之后、`created_at` 之前插入：

```python
    dispatch_batch_id = Column(Integer, nullable=True)
    dispatch_category_code = Column(String(50), nullable=True)
```

最终 `CleanJobRecord` 的列顺序为：
```python
class CleanJobRecord(Base):
    __tablename__ = "clean_jobs"

    id = Column(Integer, primary_key=True, index=True)
    file_ids = Column(JSON)
    rules = Column(JSON)
    status = Column(String(20), default="done")
    row_in = Column(Integer, default=0)
    row_out = Column(Integer, default=0)
    row_filtered = Column(Integer, default=0)
    dispatch_batch_id = Column(Integer, nullable=True)
    dispatch_category_code = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    cleaned_data = relationship("CleanedDataRecord", back_populates="job", cascade="all, delete-orphan")
```

- [ ] **Step 3: 追加 Pydantic schemas**

在文件末尾追加（在 ORM 新增之后）：

```python
# ─── P8: Dispatch Pydantic Schemas ───────────────────────────

class DispatchRuleIn(BaseModel):
    category_code: str
    platform: Optional[str] = None
    field: str
    match_type: str
    value: str
    item_name_keyword: Optional[str] = None
    priority: int = 100
    is_active: bool = True


class DispatchRuleOut(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    category_code: str
    platform: Optional[str]
    field: str
    match_type: str
    value: str
    item_name_keyword: Optional[str]
    priority: int
    is_active: int
    created_at: Optional[datetime]


class DispatchBatchOut(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    file_id: int
    status: str
    total_rows: Optional[int]
    dispatched_rows: Optional[int]
    unmatched_rows: Optional[int]
    created_at: Optional[datetime]
    finished_at: Optional[datetime]
```

- [ ] **Step 4: 确认 schemas.py 导入正常**

```bash
cd backend
python -c "from app.models.schemas import DispatchRule, DispatchBatch, DispatchItem, DispatchRuleIn, DispatchRuleOut, DispatchBatchOut; print('OK')"
```

Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/schemas.py
git commit -m "feat(p8): add DispatchRule/Batch/Item ORM models and Pydantic schemas; add dispatch cols to CleanJobRecord"
```

---

## Task 3: dispatch_api.py — 7个接口

**Files:**
- Create: `backend/app/api/dispatch_api.py`

- [ ] **Step 1: 写 dispatch_api.py**

```python
"""
数据分发 API
POST /run           — 对指定 file_id 执行分发
GET  /batches       — 列出所有分发批次
GET  /batches/{id}/stats — 某批次各品类行数明细
GET  /rules         — 规则列表（支持 platform / category_code 过滤）
POST /rules         — 新增规则
PUT  /rules/{id}    — 修改规则
DELETE /rules/{id}  — 删除规则
"""
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.models.database import get_db
from app.models.schemas import (
    DispatchRule, DispatchBatch, DispatchItem,
    DispatchRuleIn, DispatchRuleOut, DispatchBatchOut,
    RawDataRecord, UploadFileRecord,
)

router = APIRouter(prefix="/api/dispatch", tags=["dispatch"])


def _field_value(row: RawDataRecord, field: str) -> str:
    """从 raw_data 行取指定字段值，返回空字符串如果字段不存在"""
    field_map = {
        "category_lv0": row.category_lv0,
        "category_lv1": row.category_lv1,
        "category_lv2": row.category_lv2,
        "category_lv3": row.category_lv3,
        "item_name": row.item_name,
    }
    return (field_map.get(field) or "")


def _rule_matches(row: RawDataRecord, rule: DispatchRule) -> bool:
    """判断一条规则是否命中该行"""
    val = _field_value(row, rule.field)
    if rule.match_type == "contains":
        main_match = rule.value in val
    elif rule.match_type == "equals":
        main_match = val == rule.value
    else:
        main_match = False

    if not main_match:
        return False

    if rule.item_name_keyword:
        return rule.item_name_keyword in (row.item_name or "")

    return True


@router.post("/run", response_model=DispatchBatchOut)
def run_dispatch(payload: dict, db: Session = Depends(get_db)):
    """对指定 file_id 执行分发，返回新建的 batch"""
    file_id: int = payload.get("file_id")
    if not file_id:
        raise HTTPException(status_code=400, detail="file_id 不能为空")

    file_record = db.query(UploadFileRecord).filter(UploadFileRecord.id == file_id).first()
    if not file_record:
        raise HTTPException(status_code=404, detail="文件不存在")

    platform = (file_record.platform or "").lower()

    # 1. 创建 batch
    batch = DispatchBatch(file_id=file_id, status="running")
    db.add(batch)
    db.flush()

    # 2. 取该文件所有 raw_data 行
    rows = db.query(RawDataRecord).filter(RawDataRecord.file_id == file_id).all()
    total_rows = len(rows)

    # 3. 取匹配平台（或 platform IS NULL）的 active 规则，按 priority ASC
    rules = (
        db.query(DispatchRule)
        .filter(
            DispatchRule.is_active == 1,
            (DispatchRule.platform == None) | (DispatchRule.platform == platform),
        )
        .order_by(DispatchRule.priority, DispatchRule.id)
        .all()
    )

    # 4. 逐行匹配
    dispatched_rows = 0
    unmatched_rows = 0
    items_to_insert: list[DispatchItem] = []

    for row in rows:
        matched = False
        for rule in rules:
            if _rule_matches(row, rule):
                items_to_insert.append(DispatchItem(
                    batch_id=batch.id,
                    raw_data_id=row.id,
                    category_code=rule.category_code,
                    matched_rule_id=rule.id,
                ))
                dispatched_rows += 1
                matched = True
                break
        if not matched:
            unmatched_rows += 1

    db.bulk_save_objects(items_to_insert)

    # 5. 更新 batch
    batch.status = "done"
    batch.total_rows = total_rows
    batch.dispatched_rows = dispatched_rows
    batch.unmatched_rows = unmatched_rows
    batch.finished_at = datetime.utcnow()
    db.commit()
    db.refresh(batch)
    return batch


@router.get("/batches", response_model=list[DispatchBatchOut])
def list_batches(
    file_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    """列出所有分发批次，可按 file_id 过滤"""
    q = db.query(DispatchBatch)
    if file_id:
        q = q.filter(DispatchBatch.file_id == file_id)
    return q.order_by(DispatchBatch.created_at.desc()).all()


@router.get("/batches/{batch_id}/stats")
def get_batch_stats(batch_id: int, db: Session = Depends(get_db)):
    """某批次各品类行数明细"""
    batch = db.query(DispatchBatch).filter(DispatchBatch.id == batch_id).first()
    if not batch:
        raise HTTPException(status_code=404, detail="批次不存在")

    from sqlalchemy import func
    rows = (
        db.query(DispatchItem.category_code, func.count(DispatchItem.id).label("count"))
        .filter(DispatchItem.batch_id == batch_id)
        .group_by(DispatchItem.category_code)
        .all()
    )
    return {
        "batch_id": batch_id,
        "total_rows": batch.total_rows,
        "dispatched_rows": batch.dispatched_rows,
        "unmatched_rows": batch.unmatched_rows,
        "categories": [{"category_code": r.category_code, "count": r.count} for r in rows],
    }


@router.get("/rules", response_model=list[DispatchRuleOut])
def list_rules(
    platform: Optional[str] = Query(None),
    category_code: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    q = db.query(DispatchRule)
    if platform:
        q = q.filter(DispatchRule.platform == platform)
    if category_code:
        q = q.filter(DispatchRule.category_code == category_code)
    return q.order_by(DispatchRule.priority, DispatchRule.id).all()


@router.post("/rules", response_model=DispatchRuleOut)
def create_rule(body: DispatchRuleIn, db: Session = Depends(get_db)):
    rule = DispatchRule(**body.model_dump())
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


@router.put("/rules/{rule_id}", response_model=DispatchRuleOut)
def update_rule(rule_id: int, body: DispatchRuleIn, db: Session = Depends(get_db)):
    rule = db.query(DispatchRule).filter(DispatchRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="规则不存在")
    for k, v in body.model_dump().items():
        setattr(rule, k, v)
    db.commit()
    db.refresh(rule)
    return rule


@router.delete("/rules/{rule_id}")
def delete_rule(rule_id: int, db: Session = Depends(get_db)):
    rule = db.query(DispatchRule).filter(DispatchRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="规则不存在")
    db.delete(rule)
    db.commit()
    return {"message": "已删除"}
```

- [ ] **Step 2: 注册 router 到 main.py**

读取 `backend/app/main.py`，找到 router include 的位置，添加：

```python
from app.api.dispatch_api import router as dispatch_router
# ...
app.include_router(dispatch_router)
```

- [ ] **Step 3: 验证接口可导入**

```bash
cd backend
python -c "from app.api.dispatch_api import router; print('routes:', [r.path for r in router.routes])"
```

Expected: 打印出包含 `/api/dispatch/run`、`/api/dispatch/batches`、`/api/dispatch/rules` 等路由

- [ ] **Step 4: Commit**

```bash
git add backend/app/api/dispatch_api.py backend/app/main.py
git commit -m "feat(p8): add dispatch_api with run/batches/stats/rules CRUD endpoints"
```

---

## Task 4: 修改 data_cleaner.py — 支持 dispatch 过滤

**Files:**
- Modify: `backend/app/services/data_cleaner.py`

- [ ] **Step 1: 修改 run_clean 函数签名和数据源选取逻辑**

找到 `run_clean` 函数定义（第 41 行），将其改为：

```python
def run_clean(
    db: Session,
    clean_job_id: int,
    file_ids: list[int],
    rules: dict,
    dispatch_batch_id: int | None = None,
    dispatch_category_code: str | None = None,
) -> int:
    """执行清洗逻辑，返回写入 cleaned_data 的行数"""
    dedup: bool = rules.get("dedup", True)

    # ── 加载规则表 ─────────────────────────────────────────────
    noise_words = _load_noise_words(db)
    brand_alias_map = _load_brand_alias_map(db)

    # ── 数据源选取 ─────────────────────────────────────────────
    if dispatch_batch_id and dispatch_category_code:
        from app.models.schemas import DispatchItem
        raw_data_ids = (
            db.query(DispatchItem.raw_data_id)
            .filter(
                DispatchItem.batch_id == dispatch_batch_id,
                DispatchItem.category_code == dispatch_category_code,
            )
            .subquery()
        )
        records = db.query(RawDataRecord).filter(RawDataRecord.id.in_(raw_data_ids)).all()
    else:
        records = db.query(RawDataRecord).filter(RawDataRecord.file_id.in_(file_ids)).all()
```

其余逻辑（Step 1 干扰词过滤、Step 2 去重、Step 3 品牌标准化、bulk_save_objects）保持不变。

- [ ] **Step 2: 验证 data_cleaner.py 导入正常**

```bash
cd backend
python -c "from app.services.data_cleaner import run_clean; import inspect; print(inspect.signature(run_clean))"
```

Expected: `(db: Session, clean_job_id: int, file_ids: list[int], rules: dict, dispatch_batch_id: int | None = None, dispatch_category_code: str | None = None) -> int`

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/data_cleaner.py
git commit -m "feat(p8): data_cleaner supports dispatch_batch_id + dispatch_category_code filtering"
```

---

## Task 5: 修改 clean.py — 接受 dispatch 参数

**Files:**
- Modify: `backend/app/api/clean.py`

- [ ] **Step 1: 修改 run_clean_job 接受可选 dispatch 参数**

将 `run_clean_job` 函数中的 payload 解析部分和 `CleanJobRecord` 创建部分改为：

```python
@router.post("/run", response_model=CleanJobOut)
def run_clean_job(payload: dict, db: Session = Depends(get_db)):
    """
    执行数据清洗任务。
    payload: {
      "file_ids": [1,2],
      "rules": { "dedup": true },
      "dispatch_batch_id": 1,          // 可选
      "dispatch_category_code": "SPK"  // 可选
    }
    """
    file_ids: list[int] = payload.get("file_ids", [])
    rules: dict = payload.get("rules", {"dedup": True})
    dispatch_batch_id: int | None = payload.get("dispatch_batch_id")
    dispatch_category_code: str | None = payload.get("dispatch_category_code")

    if not file_ids:
        raise HTTPException(status_code=400, detail="file_ids 不能为空")

    # 统计输入行数
    from app.models.schemas import RawDataRecord, DispatchItem
    if dispatch_batch_id and dispatch_category_code:
        raw_data_ids = (
            db.query(DispatchItem.raw_data_id)
            .filter(
                DispatchItem.batch_id == dispatch_batch_id,
                DispatchItem.category_code == dispatch_category_code,
            )
            .subquery()
        )
        row_in = db.query(RawDataRecord).filter(RawDataRecord.id.in_(raw_data_ids)).count()
    else:
        row_in = db.query(RawDataRecord).filter(RawDataRecord.file_id.in_(file_ids)).count()

    # 创建 job 记录
    job = CleanJobRecord(
        file_ids=file_ids,
        rules=rules,
        status="processing",
        row_in=row_in,
        row_out=0,
        dispatch_batch_id=dispatch_batch_id,
        dispatch_category_code=dispatch_category_code,
    )
    db.add(job)
    db.flush()

    try:
        row_out = run_clean(db, job.id, file_ids, rules, dispatch_batch_id, dispatch_category_code)
        job.row_out = row_out
        job.status = "done"
        db.commit()
        db.refresh(job)
    except Exception as e:
        job.status = "error"
        db.commit()
        raise HTTPException(status_code=500, detail=f"清洗失败: {str(e)}")

    return job
```

`list_clean_jobs` 和 `preview_clean_job` 不变。

- [ ] **Step 2: 验证 clean.py 导入正常**

```bash
cd backend
python -c "from app.api.clean import router; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/app/api/clean.py
git commit -m "feat(p8): clean API accepts optional dispatch_batch_id and dispatch_category_code"
```

---

## Task 6: sql/init.sql — 新增表

**Files:**
- Modify: `sql/init.sql`

- [ ] **Step 1: 在 init.sql 末尾追加三张表和 clean_jobs 的列**

在 `-- ============================================================` 末尾或文件末尾追加：

```sql
-- ── P8: Dispatch Tables ──────────────────────────────────────

CREATE TABLE IF NOT EXISTS dispatch_rules (
    id               INT AUTO_INCREMENT PRIMARY KEY,
    category_code    VARCHAR(50)  NOT NULL,
    platform         VARCHAR(50),
    field            VARCHAR(50)  NOT NULL,
    match_type       VARCHAR(20)  NOT NULL,
    value            VARCHAR(200) NOT NULL,
    item_name_keyword VARCHAR(200),
    priority         INT          NOT NULL DEFAULT 100,
    is_active        TINYINT      NOT NULL DEFAULT 1,
    created_at       DATETIME     DEFAULT CURRENT_TIMESTAMP,
    INDEX ix_dispatch_rules_category_code (category_code),
    INDEX ix_dispatch_rules_priority (priority)
);

CREATE TABLE IF NOT EXISTS dispatch_batches (
    id               INT AUTO_INCREMENT PRIMARY KEY,
    file_id          INT          NOT NULL,
    status           VARCHAR(20)  NOT NULL DEFAULT 'running',
    total_rows       INT,
    dispatched_rows  INT,
    unmatched_rows   INT,
    created_at       DATETIME     DEFAULT CURRENT_TIMESTAMP,
    finished_at      DATETIME,
    CONSTRAINT fk_db_file FOREIGN KEY (file_id) REFERENCES upload_files(id),
    INDEX ix_dispatch_batches_file_id (file_id)
);

CREATE TABLE IF NOT EXISTS dispatch_items (
    id               INT AUTO_INCREMENT PRIMARY KEY,
    batch_id         INT          NOT NULL,
    raw_data_id      INT          NOT NULL,
    category_code    VARCHAR(50)  NOT NULL,
    matched_rule_id  INT,
    UNIQUE KEY uq_dispatch_items_batch_row (batch_id, raw_data_id),
    CONSTRAINT fk_di_batch FOREIGN KEY (batch_id) REFERENCES dispatch_batches(id) ON DELETE CASCADE,
    CONSTRAINT fk_di_raw   FOREIGN KEY (raw_data_id) REFERENCES raw_data(id) ON DELETE CASCADE,
    INDEX ix_dispatch_items_batch_id (batch_id),
    INDEX ix_dispatch_items_category_code (category_code)
);

-- clean_jobs 加 dispatch 列（如已存在则忽略）
ALTER TABLE clean_jobs
    ADD COLUMN IF NOT EXISTS dispatch_batch_id      INT  NULL,
    ADD COLUMN IF NOT EXISTS dispatch_category_code VARCHAR(50) NULL;

UPDATE alembic_version SET version_num = 'p8a1b2c3d4e5';
```

- [ ] **Step 2: Commit**

```bash
git add sql/init.sql
git commit -m "feat(p8): update init.sql with dispatch tables and clean_jobs dispatch cols"
```

---

## Task 7: api.ts — 新增 dispatch 函数

**Files:**
- Modify: `frontend/src/services/api.ts`

- [ ] **Step 1: 在 api.ts 末尾追加 dispatch 相关函数**

在现有 Clean 函数块之后，追加：

```typescript
// ─── Dispatch ──────────────────────────────────────────────
export const runDispatch = (fileId: number) =>
  api.post('/dispatch/run', { file_id: fileId })

export const listDispatchBatches = (params?: Record<string, unknown>) =>
  api.get('/dispatch/batches', { params })

export const getDispatchBatchStats = (batchId: number) =>
  api.get(`/dispatch/batches/${batchId}/stats`)

export const listDispatchRules = (params?: Record<string, unknown>) =>
  api.get('/dispatch/rules', { params })

export const createDispatchRule = (data: unknown) =>
  api.post('/dispatch/rules', data)

export const updateDispatchRule = (id: number, data: unknown) =>
  api.put(`/dispatch/rules/${id}`, data)

export const deleteDispatchRule = (id: number) =>
  api.delete(`/dispatch/rules/${id}`)
```

- [ ] **Step 2: 修改 runCleanJob 签名，支持可选 dispatch 参数**

将现有：
```typescript
export const runCleanJob = (payload: { file_ids: number[]; rules: Record<string, unknown> }) =>
  api.post('/clean/run', payload)
```

改为：
```typescript
export const runCleanJob = (payload: {
  file_ids: number[]
  rules: Record<string, unknown>
  dispatch_batch_id?: number
  dispatch_category_code?: string
}) =>
  api.post('/clean/run', payload)
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/services/api.ts
git commit -m "feat(p8): add dispatch API functions to api.ts; update runCleanJob signature"
```

---

## Task 8: 新建 Dispatch 页面

**Files:**
- Create: `frontend/src/pages/Dispatch/index.tsx`

- [ ] **Step 1: 写 Dispatch 页面**

```tsx
import { useState } from 'react'
import {
  Tabs, Table, Button, Tag, Space, Modal, Form, Select,
  Input, InputNumber, Switch, message, Descriptions, Typography
} from 'antd'
import {
  PlayCircleOutlined, PlusOutlined, EditOutlined, DeleteOutlined
} from '@ant-design/icons'
import { useRequest } from 'ahooks'
import {
  listUploadFiles, listDispatchBatches, runDispatch,
  getDispatchBatchStats, listDispatchRules,
  createDispatchRule, updateDispatchRule, deleteDispatchRule
} from '../../services/api'
import { useCategoryOptions } from '../../hooks/useCategoryOptions'

const { Text } = Typography

// ─── Types ───────────────────────────────────────────────────
interface UploadFile {
  id: number; filename: string; platform: string; month_range: string; row_count: number
}
interface DispatchBatch {
  id: number; file_id: number; status: string
  total_rows: number | null; dispatched_rows: number | null; unmatched_rows: number | null
  created_at: string; finished_at: string | null
}
interface CategoryStat { category_code: string; count: number }
interface DispatchRule {
  id: number; category_code: string; platform: string | null
  field: string; match_type: string; value: string
  item_name_keyword: string | null; priority: number; is_active: number
}

// ─── Tab 1: 分发管理 ──────────────────────────────────────────
function DispatchManagementTab() {
  const [runningIds, setRunningIds] = useState<Set<number>>(new Set())
  const [statsVisible, setStatsVisible] = useState(false)
  const [statsData, setStatsData] = useState<{ batch: DispatchBatch; categories: CategoryStat[] } | null>(null)

  const { data: files } = useRequest(() => listUploadFiles().then(r => r.data as UploadFile[]))
  const { data: batches, refresh: refreshBatches } = useRequest(
    () => listDispatchBatches().then(r => r.data as DispatchBatch[])
  )

  // 构建 file_id → latest done batch 映射
  const batchByFile = (batches ?? []).reduce<Record<number, DispatchBatch>>((acc, b) => {
    if (b.status === 'done') {
      if (!acc[b.file_id] || b.id > acc[b.file_id].id) acc[b.file_id] = b
    }
    return acc
  }, {})

  const handleRun = async (fileId: number) => {
    setRunningIds(prev => new Set(prev).add(fileId))
    try {
      await runDispatch(fileId)
      message.success('分发完成')
      refreshBatches()
    } finally {
      setRunningIds(prev => { const s = new Set(prev); s.delete(fileId); return s })
    }
  }

  const handleShowStats = async (batch: DispatchBatch) => {
    const res = await getDispatchBatchStats(batch.id)
    setStatsData({ batch, categories: res.data.categories })
    setStatsVisible(true)
  }

  const columns = [
    { title: 'ID', dataIndex: 'id', width: 60 },
    { title: '文件名', dataIndex: 'filename', ellipsis: true },
    {
      title: '平台', dataIndex: 'platform', width: 80,
      render: (v: string) => <Tag color="blue">{v}</Tag>
    },
    { title: '月份范围', dataIndex: 'month_range', width: 120 },
    { title: '数据量', dataIndex: 'row_count', width: 80 },
    {
      title: '分发状态', width: 180,
      render: (_: unknown, row: UploadFile) => {
        const batch = batchByFile[row.id]
        if (runningIds.has(row.id)) return <Tag color="processing">分发中...</Tag>
        if (!batch) return <Tag>未分发</Tag>
        return (
          <Space direction="vertical" size={0}>
            <Tag color="green">已分发</Tag>
            <Text type="secondary" style={{ fontSize: 12 }}>
              {new Date(batch.finished_at!).toLocaleString('zh-CN')}
            </Text>
          </Space>
        )
      }
    },
    {
      title: '操作', width: 160,
      render: (_: unknown, row: UploadFile) => {
        const batch = batchByFile[row.id]
        return (
          <Space>
            <Button
              type="link" size="small" icon={<PlayCircleOutlined />}
              loading={runningIds.has(row.id)}
              onClick={() => handleRun(row.id)}
            >
              {batch ? '重新分发' : '执行分发'}
            </Button>
            {batch && (
              <Button type="link" size="small" onClick={() => handleShowStats(batch)}>
                查看明细
              </Button>
            )}
          </Space>
        )
      }
    },
  ]

  return (
    <>
      <Table
        rowKey="id"
        dataSource={files ?? []}
        columns={columns}
        size="small"
        pagination={{ pageSize: 20 }}
      />
      <Modal
        title="分发明细"
        open={statsVisible}
        onCancel={() => setStatsVisible(false)}
        footer={null}
        width={480}
      >
        {statsData && (
          <>
            <Descriptions size="small" column={3} style={{ marginBottom: 12 }}>
              <Descriptions.Item label="总行数">{statsData.batch.total_rows}</Descriptions.Item>
              <Descriptions.Item label="已分发">{statsData.batch.dispatched_rows}</Descriptions.Item>
              <Descriptions.Item label="未命中">{statsData.batch.unmatched_rows}</Descriptions.Item>
            </Descriptions>
            <Table
              size="small"
              rowKey="category_code"
              dataSource={statsData.categories}
              pagination={false}
              columns={[
                { title: '品类', dataIndex: 'category_code' },
                { title: '行数', dataIndex: 'count', width: 80 },
              ]}
            />
          </>
        )}
      </Modal>
    </>
  )
}

// ─── Tab 2: 分发规则 ──────────────────────────────────────────
const FIELD_OPTIONS = [
  { value: 'category_lv0', label: 'Lv0类目' },
  { value: 'category_lv1', label: 'Lv1类目' },
  { value: 'category_lv2', label: 'Lv2类目' },
  { value: 'category_lv3', label: 'Lv3类目' },
  { value: 'item_name', label: '商品名称' },
]
const MATCH_TYPE_OPTIONS = [
  { value: 'contains', label: '包含' },
  { value: 'equals', label: '精准' },
]
const PLATFORM_OPTIONS = [
  { value: 'jd', label: '京东' },
  { value: 'tmall', label: '天猫' },
]

function DispatchRulesTab() {
  const [filterPlatform, setFilterPlatform] = useState<string | undefined>()
  const [filterCategory, setFilterCategory] = useState<string | undefined>()
  const [modalOpen, setModalOpen] = useState(false)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [form] = Form.useForm()
  const { options: categoryOptions } = useCategoryOptions()

  const { data: rules, refresh } = useRequest(
    () => listDispatchRules({
      ...(filterPlatform ? { platform: filterPlatform } : {}),
      ...(filterCategory ? { category_code: filterCategory } : {}),
    }).then(r => r.data as DispatchRule[]),
    { refreshDeps: [filterPlatform, filterCategory] }
  )

  const openCreate = () => {
    setEditingId(null)
    form.resetFields()
    form.setFieldsValue({ priority: 100, is_active: true })
    setModalOpen(true)
  }

  const openEdit = (rule: DispatchRule) => {
    setEditingId(rule.id)
    form.setFieldsValue({ ...rule, is_active: rule.is_active === 1 })
    setModalOpen(true)
  }

  const handleDelete = async (id: number) => {
    await deleteDispatchRule(id)
    message.success('已删除')
    refresh()
  }

  const handleSubmit = async () => {
    const vals = await form.validateFields()
    const payload = { ...vals, platform: vals.platform || null, item_name_keyword: vals.item_name_keyword || null }
    if (editingId) {
      await updateDispatchRule(editingId, payload)
      message.success('已更新')
    } else {
      await createDispatchRule(payload)
      message.success('已新增')
    }
    setModalOpen(false)
    refresh()
  }

  const columns = [
    { title: '品类', dataIndex: 'category_code', width: 100 },
    {
      title: '平台', dataIndex: 'platform', width: 80,
      render: (v: string | null) => v ? <Tag color="blue">{v}</Tag> : <Text type="secondary">不限</Text>
    },
    {
      title: '字段', dataIndex: 'field', width: 100,
      render: (v: string) => FIELD_OPTIONS.find(o => o.value === v)?.label ?? v
    },
    {
      title: '匹配方式', dataIndex: 'match_type', width: 80,
      render: (v: string) => MATCH_TYPE_OPTIONS.find(o => o.value === v)?.label ?? v
    },
    { title: '匹配值', dataIndex: 'value' },
    { title: 'AND条件', dataIndex: 'item_name_keyword', width: 120, render: (v: string | null) => v ?? '-' },
    { title: '优先级', dataIndex: 'priority', width: 70 },
    {
      title: '启用', dataIndex: 'is_active', width: 60,
      render: (v: number) => <Tag color={v ? 'green' : 'default'}>{v ? '是' : '否'}</Tag>
    },
    {
      title: '操作', width: 100,
      render: (_: unknown, row: DispatchRule) => (
        <Space size={4}>
          <Button type="link" size="small" icon={<EditOutlined />} onClick={() => openEdit(row)}>编辑</Button>
          <Button type="link" size="small" danger icon={<DeleteOutlined />}
            onClick={() => Modal.confirm({ title: '确认删除该规则？', onOk: () => handleDelete(row.id) })}>
            删除
          </Button>
        </Space>
      )
    },
  ]

  return (
    <>
      <Space style={{ marginBottom: 12 }}>
        <Select
          placeholder="平台筛选" allowClear style={{ width: 120 }}
          options={PLATFORM_OPTIONS}
          onChange={v => setFilterPlatform(v || undefined)}
        />
        <Select
          placeholder="品类筛选" allowClear style={{ width: 140 }}
          options={categoryOptions}
          onChange={v => setFilterCategory(v || undefined)}
        />
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新增规则</Button>
      </Space>
      <Table rowKey="id" dataSource={rules ?? []} columns={columns} size="small" pagination={{ pageSize: 20 }} />

      <Modal
        title={editingId ? '编辑规则' : '新增规则'}
        open={modalOpen}
        onOk={handleSubmit}
        onCancel={() => setModalOpen(false)}
        width={520}
      >
        <Form form={form} layout="vertical">
          <Form.Item name="category_code" label="目标品类" rules={[{ required: true }]}>
            <Select options={categoryOptions} placeholder="选择品类" />
          </Form.Item>
          <Form.Item name="platform" label="平台限定">
            <Select options={PLATFORM_OPTIONS} allowClear placeholder="不限" />
          </Form.Item>
          <Form.Item name="field" label="匹配字段" rules={[{ required: true }]}>
            <Select options={FIELD_OPTIONS} />
          </Form.Item>
          <Form.Item name="match_type" label="匹配方式" rules={[{ required: true }]}>
            <Select options={MATCH_TYPE_OPTIONS} />
          </Form.Item>
          <Form.Item name="value" label="匹配值" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="item_name_keyword" label="AND条件—商品名包含">
            <Input placeholder="留空=不限" />
          </Form.Item>
          <Form.Item name="priority" label="优先级（数字越小越先）" rules={[{ required: true }]}>
            <InputNumber min={1} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="is_active" label="启用" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>
    </>
  )
}

// ─── 主页面 ───────────────────────────────────────────────────
export default function DispatchPage() {
  return (
    <Tabs
      items={[
        { key: 'management', label: '分发管理', children: <DispatchManagementTab /> },
        { key: 'rules', label: '分发规则', children: <DispatchRulesTab /> },
      ]}
    />
  )
}
```

- [ ] **Step 2: 检查 useCategoryOptions hook 路径是否正确**

```bash
grep -r "useCategoryOptions" frontend/src/hooks/ 2>/dev/null || grep -r "useCategoryOptions" frontend/src/ --include="*.ts" --include="*.tsx" -l
```

Expected: 找到 hook 文件路径。若路径不是 `../../hooks/useCategoryOptions`，根据实际路径修改 import。

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/Dispatch/index.tsx
git commit -m "feat(p8): add Dispatch page with batch management and rules management tabs"
```

---

## Task 9: 修改 Clean 页面 — 加品类选择器

**Files:**
- Modify: `frontend/src/pages/Clean/index.tsx`

- [ ] **Step 1: 在 Clean 页面增加 dispatch 状态和品类 Select**

在文件顶部 import 中追加：

```tsx
import { Select } from 'antd'  // 如 Select 已在 import 中则无需重复
import { listDispatchBatches, getDispatchBatchStats } from '../../services/api'
```

在 `CleanPage` 组件内，`selectedFileIds` state 之后添加：

```tsx
const [dispatchBatchId, setDispatchBatchId] = useState<number | null>(null)
const [dispatchCategoryCode, setDispatchCategoryCode] = useState<string | undefined>()
const [categoryOptions, setCategoryOptions] = useState<{ value: string; label: string }[]>([])
```

在文件选中后自动检查分发批次（`filesData` 加载后，或 `selectedFileIds` 变化时）：

在 `handleRun` 函数中，修改 `runCleanJob` 调用：

```tsx
const handleRun = async () => {
  if (!selectedFileIds.length) { message.warning('请先选择文件'); return }
  setRunning(true)
  try {
    await runCleanJob({
      file_ids: selectedFileIds,
      rules: { dedup },
      ...(dispatchBatchId && dispatchCategoryCode
        ? { dispatch_batch_id: dispatchBatchId, dispatch_category_code: dispatchCategoryCode }
        : {}),
    })
    message.success('清洗完成')
    refreshJobs()
  } finally {
    setRunning(false)
  }
}
```

在「清洗配置」Card 的右侧列（`<Col span={12}>`）内，去重 Switch 之后，Run Button 之前，添加品类选择器：

```tsx
{categoryOptions.length > 0 && (
  <div style={{ marginTop: 16 }}>
    <Text strong>按品类过滤（可选）</Text>
    <Select
      placeholder="选择品类（不选=全量清洗）"
      allowClear
      style={{ width: '100%', marginTop: 8 }}
      options={categoryOptions}
      value={dispatchCategoryCode}
      onChange={v => setDispatchCategoryCode(v)}
    />
  </div>
)}
```

选文件后加载该文件的 dispatch batch，触发逻辑：在 `selectedFileIds` 变化时（`useEffect` 或 `onChange` 回调中）：

```tsx
// 在组件内添加
const handleFileChange = async (ids: number[]) => {
  setSelectedFileIds(ids)
  setDispatchCategoryCode(undefined)
  setCategoryOptions([])
  setDispatchBatchId(null)
  if (ids.length === 1) {
    // 单文件选中才自动检查分发批次
    const batchRes = await listDispatchBatches({ file_id: ids[0] })
    const doneBatch = (batchRes.data as Array<{ id: number; status: string; file_id: number }>)
      .find(b => b.status === 'done')
    if (doneBatch) {
      setDispatchBatchId(doneBatch.id)
      const statsRes = await getDispatchBatchStats(doneBatch.id)
      const cats = statsRes.data.categories as Array<{ category_code: string; count: number }>
      setCategoryOptions(cats.map(c => ({
        value: c.category_code,
        label: `${c.category_code}（${c.count.toLocaleString()} 条）`,
      })))
    }
  }
}
```

将 `Checkbox.Group` 的 `onChange` 从 `onChange={v => setSelectedFileIds(v as number[])}` 改为 `onChange={v => handleFileChange(v as number[])}`。

- [ ] **Step 2: Commit**

```bash
git add frontend/src/pages/Clean/index.tsx
git commit -m "feat(p8): Clean page adds dispatch category selector when batch available"
```

---

## Task 10: 注册路由和导航菜单

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/Layout/index.tsx`

- [ ] **Step 1: App.tsx 注册 /dispatch 路由**

在 `frontend/src/App.tsx` 顶部 import 区域追加：

```tsx
import DispatchPage from './pages/Dispatch'
```

在 `<Route path="/historical" .../>` 之后追加：

```tsx
<Route path="/dispatch" element={<DispatchPage />} />
```

- [ ] **Step 2: Layout/index.tsx 加菜单项**

在 `menuItems` 数组中，`/rawdata` 和 `/clean` 之间插入：

```tsx
{ key: '/dispatch', icon: <FunnelPlotOutlined />, label: '数据分发' },
```

在 `import` 语句的图标列表中追加 `FunnelPlotOutlined`：

```tsx
import {
  UploadOutlined,
  DatabaseOutlined,
  ClearOutlined,
  ExportOutlined,
  ProfileOutlined,
  AppstoreAddOutlined,
  AimOutlined,
  UserOutlined,
  LogoutOutlined,
  FundOutlined,
  QuestionCircleOutlined,
  LinkOutlined,
  FilterOutlined,
  HistoryOutlined,
  TagsOutlined,
  FunnelPlotOutlined,  // 新增
} from '@ant-design/icons'
```

- [ ] **Step 3: 验证 TypeScript 编译无错误**

```bash
cd frontend
npx tsc --noEmit 2>&1 | head -50
```

Expected: 无错误输出（或只有现有的不相关 warning）

- [ ] **Step 4: Commit**

```bash
git add frontend/src/App.tsx frontend/src/components/Layout/index.tsx
git commit -m "feat(p8): register /dispatch route and add 数据分发 menu item"
```

---

## Task 11: 运行迁移并验证

- [ ] **Step 1: 在容器内执行 Alembic 迁移**

```bash
docker compose exec backend alembic upgrade p8a1b2c3d4e5
```

Expected: 输出 `Running upgrade p7a1b2c3d4e5 -> p8a1b2c3d4e5`，无错误

- [ ] **Step 2: 验证新表存在**

```bash
docker compose exec db mysql -u luotu -plutou123 luotu -e "SHOW TABLES LIKE 'dispatch%';"
```

Expected:
```
Tables_in_luotu (dispatch%)
dispatch_batches
dispatch_items
dispatch_rules
```

- [ ] **Step 3: 验证 clean_jobs 新列存在**

```bash
docker compose exec db mysql -u luotu -plutou123 luotu -e "SHOW COLUMNS FROM clean_jobs LIKE 'dispatch%';"
```

Expected: 显示 `dispatch_batch_id` 和 `dispatch_category_code` 两列

- [ ] **Step 4: 验证后端服务启动无报错**

```bash
docker compose logs backend --tail=20
```

Expected: 无 `ImportError` 或 `AttributeError`，看到 `Uvicorn running`

- [ ] **Step 5: 验证接口可访问**

```bash
curl -s http://localhost:8000/api/dispatch/rules | head -20
```

Expected: `[]`（空数组，无 401/404/500）

- [ ] **Step 6: 最终 commit（若有未提交文件）**

```bash
git status
# 确认无未提交文件，所有变更均已 commit
```

---

## Self-Review Checklist

spec 覆盖验证：

1. ✅ `dispatch_rules` 表 — Task 1 migration + Task 2 ORM
2. ✅ `dispatch_batches` 表 — Task 1 migration + Task 2 ORM
3. ✅ `dispatch_items` 表 — Task 1 migration + Task 2 ORM
4. ✅ `clean_jobs` 加2列 — Task 1 migration + Task 2 CleanJobRecord
5. ✅ `POST /dispatch/run` — Task 3
6. ✅ `GET /dispatch/batches` — Task 3
7. ✅ `GET /dispatch/batches/{id}/stats` — Task 3
8. ✅ `GET/POST/PUT/DELETE /dispatch/rules` — Task 3
9. ✅ `data_cleaner.py` dispatch 过滤 — Task 4
10. ✅ `clean.py` 接受 dispatch 参数 — Task 5
11. ✅ `sql/init.sql` 更新 — Task 6
12. ✅ `api.ts` 新增 dispatch 函数 — Task 7
13. ✅ `Dispatch/index.tsx` 新页面 (Tab1 分发管理 + Tab2 规则管理) — Task 8
14. ✅ `Clean/index.tsx` 品类选择器 — Task 9
15. ✅ `/dispatch` 路由 + 菜单项 — Task 10
16. ✅ 迁移验证 — Task 11

规则匹配语义：`contains` / `equals` 主字段匹配，`item_name_keyword` 非空时为 AND 条件，priority ASC 命中即停。与 spec 一致。

向下兼容：`run_clean` 新参数有默认值 `None`，`runCleanJob` payload 新字段可选，`clean.py` 不传 dispatch 参数时行为不变。
