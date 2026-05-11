# P8 — 数据分发 Design Spec

**Goal:** 在原始数据上传后，由专人按预设规则将数据自动分配到各品类桶，各分析师在清洗/匹配阶段只看到自己负责的品类数据。

**Background:** 平台由多名分析师共同维护，每人负责不同品类。原始数据（京东/天猫 CSV）上传后是全品类混合的，需要有一个「分发」步骤把数据按品类拆分，才能让分析师各自独立工作。分发规则基本固定（按 Lv0~Lv3 类目名称 + 商品名关键词匹配），偶有微调。

---

## 工作流程

```
上传人：上传原始数据文件
  → 数据分发页 Tab1：对该文件点「执行分发」
  → 系统按规则逐行打标，写入分发映射表，显示各品类行数统计

各分析师：进入清洗页
  → 选文件 → 选自己负责的品类（从分发结果取）
  → 建清洗任务（携带 dispatch_batch_id + dispatch_category_code）
  → 跑匹配 → 人工确认（流程与现有完全一致）
```

分发触发：**手动**——上传人在分发页点「执行分发」，确认文件正确后触发。同一文件可重复分发（规则调整后重跑），每次创建新 batch，清洗页默认使用最新 batch。

---

## 数据模型

### 新增表：`dispatch_rules`

存储分发规则库，基本固定，支持管理界面微调。

```sql
CREATE TABLE dispatch_rules (
    id               INT AUTO_INCREMENT PRIMARY KEY,
    category_code    VARCHAR(50)  NOT NULL  COMMENT '分发目标品类（FK → categories.code）',
    platform         VARCHAR(50)            COMMENT '平台限定：jd/tmall/NULL=不限',
    field            VARCHAR(50)  NOT NULL  COMMENT '匹配字段：category_lv0/lv1/lv2/lv3/item_name',
    match_type       VARCHAR(20)  NOT NULL  COMMENT 'contains / equals',
    value            VARCHAR(200) NOT NULL  COMMENT '匹配值',
    item_name_keyword VARCHAR(200)          COMMENT '可选 AND 条件：商品名同时包含此词',
    priority         INT          NOT NULL DEFAULT 100 COMMENT '数字越小越先评估，命中即停',
    is_active        BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at       DATETIME     DEFAULT CURRENT_TIMESTAMP
);
```

**规则语义：** 一行 = 一个 OR 分支。同一品类可有多条规则（OR 关系）。`item_name_keyword` 非空时表示复合条件（主字段匹配 AND 商品名包含关键词），覆盖文档中所有复合规则（如「Lv2=平板电视 且 商品名含"激光"」→ 投影机）。

### 新增表：`dispatch_batches`

每次执行分发的记录。

```sql
CREATE TABLE dispatch_batches (
    id               INT AUTO_INCREMENT PRIMARY KEY,
    file_id          INT          NOT NULL  COMMENT 'FK → upload_files.id',
    status           VARCHAR(20)  NOT NULL DEFAULT 'running' COMMENT 'running/done/error',
    total_rows       INT                   COMMENT '文件总行数',
    dispatched_rows  INT                   COMMENT '命中规则的行数',
    unmatched_rows   INT                   COMMENT '未命中任何规则的行数',
    created_at       DATETIME     DEFAULT CURRENT_TIMESTAMP,
    finished_at      DATETIME,
    CONSTRAINT fk_db_file FOREIGN KEY (file_id) REFERENCES upload_files(id)
);
```

### 新增表：`dispatch_items`

行级分发映射结果。

```sql
CREATE TABLE dispatch_items (
    id               INT AUTO_INCREMENT PRIMARY KEY,
    batch_id         INT          NOT NULL  COMMENT 'FK → dispatch_batches.id',
    raw_data_id      INT          NOT NULL  COMMENT 'FK → raw_data.id',
    category_code    VARCHAR(50)  NOT NULL  COMMENT '该行被分到的品类',
    matched_rule_id  INT                   COMMENT '命中的规则 ID，用于溯源',
    UNIQUE KEY uq_batch_row (batch_id, raw_data_id),
    CONSTRAINT fk_di_batch FOREIGN KEY (batch_id) REFERENCES dispatch_batches(id) ON DELETE CASCADE,
    CONSTRAINT fk_di_raw   FOREIGN KEY (raw_data_id) REFERENCES raw_data(id) ON DELETE CASCADE
);
```

### 修改表：`clean_jobs`

新增两列：

```sql
ALTER TABLE clean_jobs
    ADD COLUMN dispatch_batch_id      INT  NULL  COMMENT '关联分发批次',
    ADD COLUMN dispatch_category_code VARCHAR(50) NULL COMMENT '本次清洗的品类范围';
```

两列同时非空时，`data_cleaner` 通过 `dispatch_items` 过滤数据源，只处理该品类的行。

---

## 后端

### 新文件：`backend/app/api/dispatch_api.py`

挂载路由：`/api/dispatch`

| 接口 | 说明 |
|---|---|
| `POST /run` | 对指定 `file_id` 执行分发 |
| `GET /batches` | 列出所有分发批次（含文件信息、状态） |
| `GET /batches/{batch_id}/stats` | 某批次各品类行数明细 |
| `GET /rules` | 规则列表（支持 platform / category_code 过滤） |
| `POST /rules` | 新增规则 |
| `PUT /rules/{rule_id}` | 修改规则 |
| `DELETE /rules/{rule_id}` | 删除规则 |

**`POST /run` 执行逻辑：**

```python
# 1. 创建 dispatch_batch(file_id, status='running')
# 2. 取该 file_id 对应的所有 raw_data 行
# 3. 取 platform 匹配（或 platform IS NULL）的 active 规则，按 priority ASC 排序
# 4. for each row:
#      for each rule:
#        if field_match(row, rule) AND (not rule.item_name_keyword OR keyword in row.item_name):
#          insert dispatch_items(batch_id, raw_data_id, category_code, matched_rule_id)
#          break  # 命中即停
#      else:
#        unmatched_rows += 1
# 5. 更新 batch: status='done', dispatched_rows, unmatched_rows, finished_at
```

### 修改：`backend/app/services/data_cleaner.py`

`run_clean_job` 的数据源选取逻辑：

```python
if job.dispatch_batch_id and job.dispatch_category_code:
    # 通过 dispatch_items 过滤
    raw_data_ids = db.query(DispatchItem.raw_data_id).filter(
        DispatchItem.batch_id == job.dispatch_batch_id,
        DispatchItem.category_code == job.dispatch_category_code,
    ).subquery()
    base_query = db.query(RawDataRecord).filter(RawDataRecord.id.in_(raw_data_ids))
else:
    # 现有逻辑：按 file_ids
    base_query = db.query(RawDataRecord).filter(RawDataRecord.file_id.in_(job.file_ids))
```

其余清洗步骤（干扰词过滤、品牌标准化等）不变。

### 修改：`backend/app/api/clean_api.py`

`POST /api/clean/run` 接受新增可选参数：

```python
dispatch_batch_id: Optional[int] = None
dispatch_category_code: Optional[str] = None
```

写入 `clean_jobs`，传给 `data_cleaner`。不传则行为与现在完全一致（向下兼容）。

### 新 Alembic Migration

revision: `p8a1b2c3d4e5`，down_revision: `p7a1b2c3d4e5`

建 `dispatch_rules`、`dispatch_batches`、`dispatch_items` 三张表，`clean_jobs` 加 2 列。

---

## 前端

### 新文件：`frontend/src/pages/Dispatch/index.tsx`

两个 Tab：

**Tab 1：分发管理**

- 表格列出所有 `upload_files`（文件名、平台、月份范围、数据量）
- 新增列「分发状态」：未分发 / 分发中 / 已分发（完成时间）
- 已分发的行可展开：显示各品类行数 + 未命中行数
- 未分发的行显示「执行分发」按钮；点击后 loading，完成后刷新状态
- 同一文件可重新分发（规则更新后）

**Tab 2：分发规则**

- 列表按平台分组（京东 / 天猫）显示所有规则
- 工具栏：平台筛选 Select、品类筛选 Select、「新增规则」按钮
- 表格列：品类、平台、字段、匹配方式、匹配值、AND条件、优先级、启用、操作（编辑/删除）
- 新增/编辑弹框字段：
  - 品类 Select（`useCategoryOptions`）
  - 平台 Select（京东/天猫/不限）
  - 字段 Select（Lv0类目 / Lv1类目 / Lv2类目 / Lv3类目 / 商品名称）
  - 匹配方式 Select（包含 / 精准）
  - 匹配值 Input
  - AND条件-商品名包含 Input（可选，placeholder：留空=不限）
  - 优先级 InputNumber（默认100）
  - 启用 Switch

### 修改：`frontend/src/pages/Clean/index.tsx`（清洗任务创建）

创建清洗任务时：
- 选定文件后，调用 `GET /api/dispatch/batches` 检查该文件是否有 `status=done` 的 batch
- 若有：显示「品类」Select，选项来自 `GET /api/dispatch/batches/{batch_id}/stats`，格式如「音箱耳机（1,203 条）」
- 选择品类后，`runCleanJob` 请求体携带 `dispatch_batch_id` + `dispatch_category_code`
- 不选品类：行为与现在完全一致（向下兼容）

### 修改：`frontend/src/services/api.ts`

新增：
```typescript
export const runDispatch = (fileId: number) =>
  api.post('/dispatch/run', { file_id: fileId })

export const listDispatchBatches = () =>
  api.get('/dispatch/batches')

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

修改：`runCleanJob` 接受可选 `dispatch_batch_id` + `dispatch_category_code`。

### 导航

左侧菜单在「上传」和「原始数据」之间加入「数据分发」入口，路由 `/dispatch`。

---

## 文件变更清单

### 后端（新增/修改）

| 文件 | 改动 |
|---|---|
| `backend/alembic/versions/p8a1b2c3d4e5_dispatch.py` | 新增 migration |
| `backend/app/models/schemas.py` | 新增 DispatchRule / DispatchBatch / DispatchItem ORM + Pydantic；CleanJob 加两列 |
| `backend/app/api/dispatch_api.py` | 新建，7 个接口 |
| `backend/app/api/clean_api.py` | `run` 接口加 dispatch 参数 |
| `backend/app/services/data_cleaner.py` | 数据源过滤逻辑 |
| `sql/init.sql` | 新增 3 张表；clean_jobs 加 2 列 |

### 前端（新增/修改）

| 文件 | 改动 |
|---|---|
| `frontend/src/pages/Dispatch/index.tsx` | 新建，分发管理 + 规则管理两个 Tab |
| `frontend/src/pages/Clean/index.tsx` | 创建任务时加品类 Select |
| `frontend/src/services/api.ts` | 新增 dispatch 相关函数；修改 runCleanJob |
| `frontend/src/App.tsx`（或路由文件） | 注册 `/dispatch` 路由 |
| 导航组件 | 加「数据分发」菜单项 |

---

## 不在本次范围内

- 分发结果的可视化报表（各品类趋势）
- 未命中数据的人工处理界面（可后续补充）
- 自动触发分发（上传后自动跑）
- 多人同时分发同一文件的并发控制（当前不需要）
