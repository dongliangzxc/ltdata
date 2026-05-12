# P9 — 列模板上传 Design Spec

**Goal:** 将 Excel 上传改造为两阶段流程，通过可复用的「列模板」将原始列名映射到标准字段，未映射列自动存入 `extra_data`，彻底解除上传格式与代码的强耦合。

**Background:** 当前 `excel_parser.py` 硬编码两套列映射（JD / 天猫），遇到新增列或列名变化就会静默丢失数据。`raw_data` 表已有 `extra_data JSON` 列但从未填充。本次改造利用已有字段，加入模板机制，让上传人在首次遇到新格式时做一次映射，后续复用。

---

## 工作流程

```
用户拖拽文件
  → POST /api/upload/headers
      服务端：保存到临时目录，读表头，找最相似模板
      返回：{ temp_file_id, columns, suggested_template, match_score }

  → 前端展示映射确认页（Step 2）
      表格：原始列名 | 映射目标 Select | 忽略 Checkbox
      必填字段未映射时标红，禁止提交
      可选：「保存为模板」Switch + 模板名输入

  → 用户点击「确认入库」
      POST /api/upload/confirm
      { temp_file_id, mapping, ignore_columns, save_template_name? }
      服务端：解析文件 → 写入 raw_data（含 extra_data）→ 返回预览
```

临时文件保存在 `UPLOAD_DIR/tmp/`，`confirm` 成功后移至正式目录；超过 24 小时未 confirm 的临时文件由定期清理任务删除（可用 cron 或启动时清理）。

---

## 数据模型

### 新增表：`column_templates`

```sql
CREATE TABLE column_templates (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    name            VARCHAR(100) NOT NULL            COMMENT '模板名称，如「京东月报」',
    platform        VARCHAR(50)                      COMMENT '辅助提示，jd/tmall/taobao/suning/NULL=通用',
    col_fingerprint CHAR(32)                         COMMENT '列名集合排序后的 MD5，用于精确匹配',
    mapping         JSON         NOT NULL            COMMENT '{"原始列名": "标准字段名 | __ext__", ...}',
    ignore_columns  JSON                             COMMENT '["列名1", ...] 入库时忽略',
    is_builtin      TINYINT      NOT NULL DEFAULT 0  COMMENT '1=内置模板（不可删除）',
    created_at      DATETIME     DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME     DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);
```

**mapping 值约定：**
- 标准字段名（如 `item_id`、`sales_qty`）：映射到 `raw_data` 对应列
- `__ext__`：显式存入 `extra_data`
- 不在 mapping 中且不在 ignore_columns 中的列：同样存入 `extra_data`（默认行为）

**内置模板初始数据**（migration 中 INSERT）：
- 「京东月报」：对应现有 `JD_COLUMN_MAP`，`is_builtin=1`
- 「天猫/淘宝月报」：对应现有 `TM_TB_COLUMN_MAP`，`is_builtin=1`

### 修改表：`upload_files`

```sql
ALTER TABLE upload_files
    ADD COLUMN template_id INT NULL COMMENT '本次上传使用的列模板 ID';
```

### `raw_data.extra_data`

已有 JSON 列，不改结构。本次起正式填充：所有未映射到标准字段的原始列，以 `{"原始列名": 值, ...}` 格式写入。

---

## 后端

### 新文件：`backend/app/api/upload_templates_api.py`

挂载路由：`/api/upload/templates`（在 `main.py` 注册）

| 接口 | 说明 |
|---|---|
| `GET /` | 列出所有模板 |
| `POST /` | 新建模板 |
| `PUT /{id}` | 修改模板（内置模板可改 mapping/name，不可删） |
| `DELETE /{id}` | 删除非内置模板，内置模板返回 403 |

### 修改：`backend/app/api/upload.py`

新增两个端点：

**`POST /api/upload/headers`**

```python
# 1. 保存文件到 UPLOAD_DIR/tmp/{uuid}_{filename}，生成 temp_file_id（uuid）
# 2. 读第一行，提取列名列表
# 3. 计算列名集合的 MD5 fingerprint
# 4. 查 column_templates：先精确匹配 col_fingerprint，
#    无则计算所有模板的 Jaccard 相似度，取最高分
# 5. 返回：
#    { temp_file_id, columns, suggested_template, match_score }
#    match_score: 0~100，< 70 时前端显示警告
```

**`POST /api/upload/confirm`**

```python
# payload: { temp_file_id, mapping, ignore_columns, save_template_name? }
# 1. 定位临时文件（UPLOAD_DIR/tmp/{temp_file_id}_*）
# 2. 用 mapping 重新解析文件（替代原 parse_raw_excel）：
#    - 标准字段 → raw_data 对应列
#    - 其余未忽略列 → extra_data dict
# 3. 若 save_template_name 非空：INSERT/UPDATE column_templates
#    （计算 col_fingerprint，保存 mapping + ignore_columns）
# 4. 走原有去重逻辑（item_id + month + platform）
# 5. 写入 upload_files（含 template_id）和 raw_data
# 6. 将临时文件移至正式目录 UPLOAD_DIR/{filename}
# 7. 返回原有 { file_id, filename, platform, month_range, row_count, inserted, skipped, preview }
```

### 修改：`backend/app/services/excel_parser.py`

新增函数 `parse_with_mapping(file_path, mapping, ignore_columns) -> tuple[list[dict], str, str]`：

```python
# 用传入的 mapping 替代硬编码的 JD/TM 列映射
# mapping: {"原始列名": "标准字段名"} （已过滤掉 __ext__ 和 ignore）
# 剩余未映射列 → extra_data
# 平台和月份推断逻辑复用现有代码
# 返回: (records, platform, month_range)
# records 每条: { ...标准字段..., "extra_data": {"原始列名": 值, ...} }
```

原有 `parse_raw_excel` 保留，原 `POST /upload` 接口不变（向下兼容）。

### 新 Alembic Migration

revision: `p9a1b2c3d4e5`，down_revision: `p8a1b2c3d4e5`

- 建 `column_templates` 表
- `upload_files` 加 `template_id` 列
- INSERT 两条内置模板（京东、天猫/淘宝）

---

## 前端

### 修改：`frontend/src/pages/Upload/index.tsx`

**Step 1（现有上传区）**：文件选中后调 `POST /upload/headers`，成功后切换到 Step 2，不再直接入库。

**Step 2（新增映射确认卡片）**：

```
┌─────────────────────────────────────────────────────┐
│ 列映射确认                     已匹配模板：京东月报 ▼  │
├──────────────────┬──────────────────────┬───────────┤
│ 原始列名          │ 映射到               │ 忽略      │
├──────────────────┼──────────────────────┼───────────┤
│ 宝贝ID           │ item_id ✦            │ □         │
│ 宝贝名称          │ item_name ✦          │ □         │
│ 月               │ month ✦              │ □         │
│ 平台             │ platform ✦           │ □         │
│ 销量             │ sales_qty ✦          │ □         │
│ 销售额            │ sales_amount ✦      │ □         │
│ 价格             │ price ✦              │ □         │
│ 新增列X          │ 存入ext              │ □         │  ← 未知列默认 ext
│ 内部备注          │ -                   │ ☑         │  ← 忽略
└──────────────────┴──────────────────────┴───────────┘
  ✦ = 必填字段（红色标注，Select 未选时禁止提交）

  □ 保存为模板  [模板名称输入框]          [取消] [确认入库]
```

- 顶部下拉可切换为其他已有模板（切换后重新预填 mapping）
- `match_score < 70` 时顶部显示黄色警告「未找到高度匹配的模板，请仔细核对映射」
- 点「确认入库」→ 调 `POST /upload/confirm` → 成功后显示现有数据预览卡片

**「列模板」Tab**（与「上传历史」并列）：

- 表格列：模板名、平台、列数、是否内置、最后更新时间、操作（编辑/删除）
- 内置模板删除按钮置灰
- 编辑弹框：名称 Input + 平台 Select + 同款映射表格（可调整 mapping 和 ignore_columns）

### 修改：`frontend/src/services/api.ts`

新增：

```typescript
export const getUploadHeaders = (formData: FormData) =>
  api.post('/upload/headers', formData, { headers: { 'Content-Type': 'multipart/form-data' } })

export const confirmUpload = (payload: {
  temp_file_id: string
  mapping: Record<string, string>
  ignore_columns: string[]
  save_template_name?: string
}) => api.post('/upload/confirm', payload)

export const listUploadTemplates = () =>
  api.get('/upload/templates')

export const createUploadTemplate = (data: unknown) =>
  api.post('/upload/templates', data)

export const updateUploadTemplate = (id: number, data: unknown) =>
  api.put(`/upload/templates/${id}`, data)

export const deleteUploadTemplate = (id: number) =>
  api.delete(`/upload/templates/${id}`)
```

---

## 标准字段参考

| 标准字段名 | 说明 | 必填 |
|---|---|---|
| `item_id` | 商品 ID | ✦ |
| `month` | 月份（如 202507） | ✦ |
| `platform` | 平台（jd/tmall/taobao/suning） | ✦ |
| `item_name` | 商品名称 | ✦ |
| `sales_qty` | 销量 | ✦ |
| `sales_amount` | 销售额 | ✦ |
| `price` | 价格 | ✦ |
| `category_lv0~lv5` | 各级类目 | 可选 |
| `brand_raw` | 原始品牌字段 | 可选 |
| `shop_name` | 店铺名 | 可选 |
| `ref_price` | 参考价格 | 可选 |
| `item_image` | 商品图片 URL | 可选 |
| `item_url` | 商品链接 | 可选 |
| `brand_std` | 标准品牌码 | 可选 |
| `model_std` | 标准机型码 | 可选 |

---

## 文件变更清单

### 后端

| 文件 | 改动 |
|---|---|
| `backend/alembic/versions/p9a1b2c3d4e5_column_templates.py` | 新增 migration |
| `backend/app/models/schemas.py` | 新增 ColumnTemplate ORM + Pydantic |
| `backend/app/api/upload_templates_api.py` | 新建，模板 CRUD |
| `backend/app/api/upload.py` | 新增 `/headers` 和 `/confirm` 端点 |
| `backend/app/services/excel_parser.py` | 新增 `parse_with_mapping` 函数 |
| `backend/app/main.py` | 注册 upload_templates_api router |
| `sql/init.sql` | 新增 column_templates 表；upload_files 加 template_id |

### 前端

| 文件 | 改动 |
|---|---|
| `frontend/src/pages/Upload/index.tsx` | 改造为两步流程，新增映射确认和模板 Tab |
| `frontend/src/services/api.ts` | 新增 6 个 upload/template 相关函数 |

---

## 不在本次范围内

- 模板版本历史（每次修改的 diff 记录）
- 多 Sheet Excel 的分 Sheet 映射
- 上传时实时校验必填字段的数据质量（空值率等）
- 临时文件自动清理的定时任务（可手动在 entrypoint.sh 中加 find 命令）
