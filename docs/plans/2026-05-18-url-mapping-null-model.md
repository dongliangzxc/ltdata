# URL 映射放宽导入（耳机数据库型号为空行）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 耳机数据库.xlsx 中 84 万条型号为空/脏的行，现在也能提取 URL 存入 item_url_mappings(model_id=NULL)，匹配时自然穿透 S1-S4，确认后回写 model_id。

**Architecture:** 三处改动独立推进：① Schema 放开 nullable → ② 导入逻辑在跳过型号时仍捕获 URL → ③ 确认回写扩展到 matched 状态下的 NULL 补填。matcher.py 无需改动（NULL 已是 falsy，自然穿透）。

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy ORM, Alembic, openpyxl, pytest + SQLite in-memory

---

## 文件清单

| 操作 | 文件 |
|------|------|
| 新建 | `backend/alembic/versions/p14a1b2c3d4e5_url_mapping_nullable_model.py` |
| 修改 | `backend/app/models/schemas.py`（item_url_mappings.model_id nullable） |
| 修改 | `backend/app/services/model_db_importer.py`（URL-only 逻辑 + stats） |
| 修改 | `scripts/import_model_db.py`（print_report 新增 urls_from_dirty_model 行） |
| 修改 | `backend/app/api/match_api.py`（back-fill 扩展至 matched 状态） |
| 修改 | `backend/tests/test_model_db_importer.py`（新增 3 个测试） |

---

## Task 1: Schema — item_url_mappings.model_id 改为可空

**Files:**
- Modify: `backend/app/models/schemas.py:342`
- Create: `backend/alembic/versions/p14a1b2c3d4e5_url_mapping_nullable_model.py`

- [ ] **Step 1: 修改 ORM 定义**

在 `backend/app/models/schemas.py` 第 342 行，将：
```python
    model_id   = Column(Integer, ForeignKey("models.id"), nullable=False)
```
改为：
```python
    model_id   = Column(Integer, ForeignKey("models.id"), nullable=True)
```

- [ ] **Step 2: 新建 Alembic migration**

新建文件 `backend/alembic/versions/p14a1b2c3d4e5_url_mapping_nullable_model.py`，内容：

```python
"""item_url_mappings.model_id 改为可空，支持 URL-only 映射

Revision ID: p14a1b2c3d4e5
Revises: p13a1b2c3d4e5
Create Date: 2026-05-18
"""
from alembic import op

revision = 'p14a1b2c3d4e5'
down_revision = 'p13a1b2c3d4e5'
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column('item_url_mappings', 'model_id', nullable=True)


def downgrade():
    op.alter_column('item_url_mappings', 'model_id', nullable=False)
```

- [ ] **Step 3: 验证 migration 文件被 Alembic 识别**

```bash
cd backend && python -m alembic heads
```
预期输出包含 `p14a1b2c3d4e5 (head)`。

- [ ] **Step 4: 验证现有测试仍通过**

```bash
cd backend && python -m pytest tests/test_model_db_importer.py -v
```
预期：全部 PASS（SQLite in-memory 建表会读 ORM 定义，应立即兼容）。

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/schemas.py backend/alembic/versions/p14a1b2c3d4e5_url_mapping_nullable_model.py
git commit -m "feat: item_url_mappings.model_id 改为可空，支持 URL-only 映射"
```

---

## Task 2: model_db_importer — 型号脏数据行也捕获 URL

**Files:**
- Modify: `backend/app/services/model_db_importer.py:190-244`
- Test: `backend/tests/test_model_db_importer.py`

### 2A: 写失败测试

- [ ] **Step 1: 在 test_model_db_importer.py 末尾添加两个测试**

```python
# ── 型号脏数据行仍捕获 URL ─────────────────────────────────

@pytest.fixture
def dirty_model_excel(tmp_path):
    """品牌有效、型号为空、URL有效的一行数据"""
    path = tmp_path / "dirty_model.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    headers = [
        "平台", "宝贝名称", "宝贝链接", "销量", "销售额", "ASP",
        "品牌", "型号", "佩戴类型", "In-ear Type", "开放式外观",
        "Power Type", "Bluetooth Version", "Sport", "Gaming", "HIFI",
        "ANC", "ENC", "Fast Charging", "IP Marking", "Health Monitoring",
        "Touch Screen Monitor", "骨传导", "AI", "AI+功能",
    ]
    ws.append(headers)
    ws.append([
        "JD", "某品牌耳机", "https://item.jd.com/99999.html",
        50, 10000, 200,
        "Sony/索尼", "",          # ← 型号为空
        "Headband", "Over Ear", "NULL", "Hybrid", 5.0,
        "NO", "NO", "NO", "YES", "NO", "NO", "NO", "NO", "NO", "NO", "NO", "",
    ])
    wb.save(path)
    return str(path)


def test_dirty_model_row_creates_url_mapping(db, dirty_model_excel):
    """型号为空但品牌+URL有效时，应建 ItemUrlMapping(model_id=None)"""
    from app.models.schemas import ItemUrlMapping
    db.add(Category(code="headphone", name="耳机"))
    db.commit()

    stats = import_model_db(dirty_model_excel, "headphone", db, dry_run=False)

    url_mapping = db.query(ItemUrlMapping).filter_by(
        platform="jd", item_id="99999"
    ).first()
    assert url_mapping is not None
    assert url_mapping.model_id is None
    assert stats["urls_from_dirty_model"] == 1


def test_dirty_model_dry_run_counts_urls(dirty_model_excel):
    """dry-run 模式也要统计 urls_from_dirty_model"""
    stats = import_model_db(dirty_model_excel, "headphone", db=None, dry_run=True)
    assert stats["urls_from_dirty_model"] == 1
```

- [ ] **Step 2: 运行，确认失败**

```bash
cd backend && python -m pytest tests/test_model_db_importer.py::test_dirty_model_row_creates_url_mapping tests/test_model_db_importer.py::test_dirty_model_dry_run_counts_urls -v
```
预期：FAIL，`KeyError: 'urls_from_dirty_model'` 或 `AssertionError`。

### 2B: 实现

- [ ] **Step 3: 修改 `model_db_importer.py` stats 字典（第 190-203 行）**

在 `stats` dict 末尾加一项：
```python
    stats = {
        "total": len(all_rows) - 1,
        "skip_model": 0,
        "skip_brand": 0,
        "skip_url": 0,
        "skip_no_attr": 0,
        "valid_rows": 0,
        "unique_models": 0,
        "models_new": 0,
        "models_existing": 0,
        "specs_written": 0,
        "urls_new": 0,
        "url_extract_fail": 0,
        "urls_from_dirty_model": 0,   # ← 新增
    }
```

- [ ] **Step 4: 在 stats dict 之后、groups 定义之前，新增 url_only_map**

在第 206 行（`groups: dict...` 那行）前插入：
```python
    # (platform, item_id) → item_url：型号脏但 URL 有效的行，不建 model，只建 url_mapping
    url_only_map: dict[tuple, str] = {}
```

- [ ] **Step 5: 修改 is_dirty_model 命中分支（第 215-217 行）**

将：
```python
        if is_dirty_model(model):
            stats["skip_model"] += 1
            continue
```
改为：
```python
        if is_dirty_model(model):
            stats["skip_model"] += 1
            # 型号脏但品牌+URL有效：仍捕获 URL（model_id=NULL），跳过建 model/spec
            if not is_dirty_brand(brand) and url and url not in _NULL_VALUES:
                item_id_dirty = extract_item_id(url, platform)
                if item_id_dirty:
                    url_only_map[(platform, item_id_dirty)] = url
            continue
```

- [ ] **Step 6: 在 groups 扫描结束后更新 urls_from_dirty_model stat**

在 `stats["unique_models"] = len(groups)` 那行（第 242 行）之后加：
```python
    stats["urls_from_dirty_model"] = len(url_only_map)
```

- [ ] **Step 7: 在写库阶段末尾写入 url_only_map**

找到 `db.commit()` 最后那行（文件末尾，第 315 行）之前，在 `for batch_start, ...` 循环结束后加入：

```python
    # ── URL-only 条目：model_id=NULL，upsert ────────────────
    for (plat, iid), iurl in url_only_map.items():
        existing = db.query(ItemUrlMapping).filter_by(
            platform=plat, item_id=iid
        ).first()
        if existing:
            if existing.model_id is None:
                existing.item_url = iurl   # 更新 URL，model_id 仍 NULL
        else:
            db.add(ItemUrlMapping(
                platform=plat,
                item_id=iid,
                item_url=iurl,
                model_id=None,
            ))
            stats["urls_new"] += 1

    db.commit()
```

> 注意：原来最后的 `db.commit()` 被这段代码的末尾取代，不要保留两个 `db.commit()`。

- [ ] **Step 8: 运行测试，确认通过**

```bash
cd backend && python -m pytest tests/test_model_db_importer.py -v
```
预期：全部 PASS。

- [ ] **Step 9: Commit**

```bash
git add backend/app/services/model_db_importer.py backend/tests/test_model_db_importer.py
git commit -m "feat: import_model_db 型号脏数据行仍捕获 URL，写入 item_url_mappings(model_id=NULL)"
```

---

## Task 3: print_report — 展示 urls_from_dirty_model

**Files:**
- Modify: `scripts/import_model_db.py:26-50`

- [ ] **Step 1: 修改 print_report 函数**

在 `print_report` 函数（第 32-50 行）的过滤区块里，在 `型号脏数据` 那行后面加一行：

```python
    print(f"  型号脏数据:       {stats['skip_model']:>10,} 行（其中捕获URL: {stats.get('urls_from_dirty_model', 0):,} 条）")
```

并在入库结果区块里加：

```python
        print(f"  url_mappings 新增:  {stats['urls_new']:>8,} 条")
        print(f"    其中 URL-only:    {stats.get('urls_from_dirty_model', 0):>8,} 条")  # ← 新增
        print(f"  url 提取失败跳过:   {stats['url_extract_fail']:>8,} 条")
```

dry-run 区块：

```python
    if dry_run:
        print(f"  (dry-run 模式，未写库)")
        print(f"  可捕获 URL-only:  {stats.get('urls_from_dirty_model', 0):>8,} 条")  # ← 新增
```

- [ ] **Step 2: 本地 dry-run 验证输出格式**

```bash
python scripts/import_model_db.py "平台元数据/耳机数据库.xlsx" --category headphone --dry-run
```
预期新增一行 `可捕获 URL-only: X 条`，X 为正数（84 万条脏型号行中品牌+URL 有效的数量）。

- [ ] **Step 3: Commit**

```bash
git add scripts/import_model_db.py
git commit -m "feat: print_report 展示 urls_from_dirty_model 数量"
```

---

## Task 4: match_api — 扩展 back-fill 到 matched 状态

**Files:**
- Modify: `backend/app/api/match_api.py:353-370`

### 4A: 写失败测试

- [ ] **Step 1: 在 backend/tests/test_match_api.py 末尾添加测试**

（如果 test_match_api.py 不存在，新建，头部加：
`import pytest`
`from tests.conftest import db` 或直接复用 conftest 中的 `db` fixture）

```python
def test_confirm_matched_backfills_null_url_mapping(db):
    """
    prev_status='matched' 且 item_url_mappings.model_id=NULL 时，
    确认后应回写 model_id（而不是跳过）。
    """
    from app.models.schemas import (
        ModelRecord, UploadFileRecord, RawDataRecord,
        CleanJobRecord, MatchResult, ItemUrlMapping,
    )
    from app.api.match_api import confirm_match

    # 建最小数据
    model = ModelRecord(brand_code="Sony", model_code="WH-XM5", category_code="headphone")
    db.add(model)
    db.flush()

    upload = UploadFileRecord(filename="x.xlsx", status="done")
    db.add(upload)
    db.flush()

    clean_job = CleanJobRecord(file_ids=[upload.id], status="done")
    db.add(clean_job)
    db.flush()

    rd = RawDataRecord(
        file_id=upload.id,
        platform="jd",
        item_id="88888",
        item_url="https://item.jd.com/88888.html",
        item_name="索尼耳机",
        brand_raw="Sony",
    )
    db.add(rd)
    db.flush()

    # item_url_mappings 中已有该 URL，model_id=NULL
    db.add(ItemUrlMapping(
        platform="jd", item_id="88888",
        item_url="https://item.jd.com/88888.html", model_id=None,
    ))
    db.flush()

    mr = MatchResult(
        clean_job_id=clean_job.id,
        raw_data_id=rd.id,
        model_id=model.id,
        match_status="matched",   # ← 算法自动匹配，非 text_only
        matched_by="auto",
        match_source="s1",
    )
    db.add(mr)
    db.commit()

    # 直接调用路由函数（绕过 FastAPI DI，传入 db）
    confirm_match(mr.id, {"model_id": model.id}, db=db)

    mapping = db.query(ItemUrlMapping).filter_by(platform="jd", item_id="88888").first()
    assert mapping.model_id == model.id
```

- [ ] **Step 2: 运行，确认失败**

```bash
cd backend && python -m pytest tests/test_match_api.py::test_confirm_matched_backfills_null_url_mapping -v
```
预期：FAIL，`assert mapping.model_id == model.id` 失败（model_id 仍为 None）。

### 4B: 实现

- [ ] **Step 3: 修改 match_api.py 第 353-370 行**

将：
```python
        # 方案 A：text_only 条目确认时，自动将 item_url 写入 URL 映射管理
        if prev_status == "text_only" and mr.raw_data_id:
            rd_for_url = db.query(RawDataRecord).filter(RawDataRecord.id == mr.raw_data_id).first()
            if rd_for_url and rd_for_url.item_url and rd_for_url.platform and rd_for_url.item_id:
                existing_mapping = db.query(ItemUrlMapping).filter_by(
                    platform=rd_for_url.platform, item_id=rd_for_url.item_id
                ).first()
                if existing_mapping:
                    existing_mapping.model_id = model_id
                    existing_mapping.item_url = rd_for_url.item_url
                else:
                    db.add(ItemUrlMapping(
                        platform=rd_for_url.platform,
                        item_id=rd_for_url.item_id,
                        item_url=rd_for_url.item_url,
                        model_id=model_id,
                        price=rd_for_url.price,
                    ))
```
改为：
```python
        # 确认时更新 URL 映射：
        #   · 已存在且 model_id=NULL → 回写（适用于从耳机数据库 URL-only 导入的条目）
        #   · 不存在且 prev_status==text_only → 新建（保留原有行为）
        if mr.raw_data_id:
            rd_for_url = db.query(RawDataRecord).filter(RawDataRecord.id == mr.raw_data_id).first()
            if rd_for_url and rd_for_url.item_url and rd_for_url.platform and rd_for_url.item_id:
                existing_mapping = db.query(ItemUrlMapping).filter_by(
                    platform=rd_for_url.platform, item_id=rd_for_url.item_id
                ).first()
                if existing_mapping and existing_mapping.model_id is None:
                    existing_mapping.model_id = model_id
                    existing_mapping.item_url = rd_for_url.item_url
                elif not existing_mapping and prev_status == "text_only":
                    db.add(ItemUrlMapping(
                        platform=rd_for_url.platform,
                        item_id=rd_for_url.item_id,
                        item_url=rd_for_url.item_url,
                        model_id=model_id,
                        price=rd_for_url.price,
                    ))
```

- [ ] **Step 4: 运行测试，确认通过**

```bash
cd backend && python -m pytest tests/test_match_api.py::test_confirm_matched_backfills_null_url_mapping -v
```
预期：PASS。

- [ ] **Step 5: 运行完整测试套件**

```bash
cd backend && python -m pytest tests/ -v
```
预期：全部 PASS，无回归。

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/match_api.py backend/tests/test_match_api.py
git commit -m "feat: 确认回写扩展——matched 状态下 URL-only 条目也回填 item_url_mappings.model_id"
```

---

## Task 5: 端到端 dry-run 验证

- [ ] **Step 1: 跑新的 dry-run，看 URL-only 数量**

```bash
python scripts/import_model_db.py "平台元数据/耳机数据库.xlsx" --category headphone --dry-run
```
预期新增输出：
```
  型号脏数据:          841,593 行（其中捕获URL: X 条）
  可捕获 URL-only:         X 条
```
X 为 841,593 中品牌有效+URL 有效的子集数量，记录结果供和用户确认后再正式导入。

- [ ] **Step 2: 确认整体测试通过后可部署**

```bash
cd backend && python -m pytest tests/ -q
```
预期：全部 PASS。
