# 数据处理平台 设计文档

## 一、需求背景

咨询公司需要一个 Web 数据处理平台，用于电商数据（如 Soundbar 各平台销售数据）的采集、清洗与报告产出。核心流程：

```
上传原始 Excel → 入库展示 → 数据清洗映射 → 导出已处理 Excel
```

---

## 二、数据结构分析

### 2.1 原始数据（7-9月原始数据）

以京东为例，Sheet1 字段如下：

| 字段 | 说明 |
|------|------|
| 平台 | 京东全部 / 天猫全部 / 淘宝 |
| 月 | YYYYMM 格式，如 202507 |
| Lv0~Lv2 类目名称 | 品类层级 |
| 宝贝ID | 商品唯一标识 |
| 宝贝名称 | 标题 |
| 宝贝图片 | 图片URL |
| 宝贝链接 | 商品详情链接 |
| 参考价格 | 挂牌价 |
| 宝贝品牌(bid) | 平台原始品牌名 |
| 宝贝店铺名称 | 店铺 |
| 销量 | 当月销量 |
| 销售额 | 当月销售额 |
| 价格 | 实际均价 |
| 品牌 | 人工标注的标准品牌码 |
| 机型 | 人工标注的型号 |

### 2.2 已处理数据（7-8月已处理）

天猫/淘宝版本字段略有差异（Lv1~Lv5 类目），核心业务字段与原始数据一致，额外增加了：品牌（标准化）和机型（标准化）。

### 2.3 数据模板（Soundbar数据模板.xlsx）

包含 4 个 Sheet：

- **元数据**：规格定义（SPEAKER TYPE, SYSTEM TYPE, BLUETOOTH 等）
- **型号**：品类+品牌+型号+上市信息+价格
- **型号规格**：每个型号对应的详细规格值
- **rawdata**：标准报告格式（年/月/周/报告类型/渠道/商场/品类/品牌/型号/销额/销量/单价/网址）

---

## 三、系统架构

### 3.1 技术选型

| 层次 | 技术 | 选型理由 |
|------|------|---------|
| 前端 | React 18 + TypeScript + Ant Design Pro | 企业级数据管理 UI 组件完善 |
| 后端 | Python 3.11 + FastAPI | pandas 原生 Excel 处理能力强 |
| 数据库 | PostgreSQL 15 | 结构化数据 + JSONB 灵活扩展 |
| 文件存储 | 本地 uploads 目录（可替换 MinIO） | MVP 阶段简化部署 |
| 包管理 | uv (Python) + pnpm (Node) | 现代化依赖管理 |

### 3.2 目录结构

```
luotu/
├── backend/
│   ├── app/
│   │   ├── main.py               # FastAPI 入口
│   │   ├── api/
│   │   │   ├── upload.py         # 文件上传接口
│   │   │   ├── rawdata.py        # 原始数据查询
│   │   │   ├── clean.py          # 数据清洗接口
│   │   │   └── export.py         # 数据导出接口
│   │   ├── models/
│   │   │   ├── database.py       # SQLAlchemy 配置
│   │   │   └── schemas.py        # Pydantic 模型 + DB 模型
│   │   ├── services/
│   │   │   ├── excel_parser.py   # Excel 解析逻辑
│   │   │   ├── data_cleaner.py   # 数据清洗逻辑
│   │   │   └── exporter.py       # 导出逻辑
│   │   └── core/
│   │       └── config.py         # 配置项
│   ├── uploads/                  # 上传文件存储目录
│   ├── pyproject.toml
│   └── alembic/                  # 数据库迁移
├── frontend/
│   ├── src/
│   │   ├── pages/
│   │   │   ├── Upload/           # 上传页面
│   │   │   ├── DataList/         # 数据列表页面
│   │   │   ├── Clean/            # 数据清洗页面
│   │   │   └── Export/           # 导出页面
│   │   ├── components/           # 公共组件
│   │   ├── services/             # API 调用层
│   │   └── App.tsx
│   ├── package.json
│   └── vite.config.ts
└── docker-compose.yml
```

---

## 四、核心功能模块

### 4.1 文件上传模块

**接口**：`POST /api/upload`

**处理逻辑**：
1. 接收 multipart/form-data，支持 `.xlsx` / `.xls`
2. 用 pandas 读取 Sheet1 内容
3. 自动识别平台类型（京东/天猫/淘宝）及数据格式版本
4. 写入 `upload_files` 表（记录元信息）
5. 批量写入 `raw_data` 表
6. 返回解析行数、文件ID、预览数据（前50行）

**数据库表：upload_files**
```sql
id          SERIAL PRIMARY KEY
filename    VARCHAR(255)
platform    VARCHAR(50)      -- JD/TM/TB
month_range VARCHAR(20)      -- e.g. "202507-202509"
row_count   INTEGER
status      VARCHAR(20)      -- pending/processing/done/error
uploaded_at TIMESTAMP
```

**数据库表：raw_data**
```sql
id              SERIAL PRIMARY KEY
file_id         INTEGER REFERENCES upload_files(id)
platform        VARCHAR(50)
month           INTEGER          -- 202507
category_lv0    VARCHAR(100)
category_lv1    VARCHAR(100)
category_lv2    VARCHAR(100)
item_id         VARCHAR(100)
item_name       TEXT
item_image      TEXT
item_url        TEXT
ref_price       NUMERIC(12,2)
brand_raw       VARCHAR(200)     -- 平台原始品牌名
shop_name       VARCHAR(200)
sales_qty       INTEGER
sales_amount    NUMERIC(14,2)
price           NUMERIC(12,2)
brand_std       VARCHAR(100)     -- 标准品牌码
model_std       VARCHAR(100)     -- 标准机型
extra_data      JSONB            -- 差异字段兜底
created_at      TIMESTAMP
```

### 4.2 数据展示模块

**接口**：`GET /api/rawdata`

**查询参数**：
- `file_id`: 文件ID过滤
- `platform`: 平台过滤
- `month`: 月份过滤
- `brand_std`: 品牌过滤
- `page` / `page_size`: 分页（默认 20）

**前端展示**：
- 表格支持排序、筛选、列显示控制
- 顶部展示汇总统计（总销量、总销售额、品牌数、型号数）
- 支持按文件、平台、月份切换数据集

### 4.3 数据清洗模块

清洗的核心是：将原始数据中的 `品牌`/`机型` 字段映射到标准品牌码/型号码，并过滤无效数据。

**接口**：`POST /api/clean/run`

**请求体**：
```json
{
  "file_ids": [1, 2, 3],
  "rules": {
    "filter_brands": ["BOSE", "JBL", "EDIFIER"],  // 可选：只保留指定品牌
    "exclude_models": [],                           // 排除特定型号
    "dedup": true                                   // 去重（同店铺同商品）
  }
}
```

**清洗逻辑**（`data_cleaner.py`）：
1. **品牌标准化**：`brand_std` 字段已在上传时从 Excel 的"品牌"列读取，本步骤可补全空值（模糊匹配型号表）
2. **过滤规则**：按品牌白名单/黑名单过滤
3. **去重**：同 item_id 同月份保留销量最大的记录
4. **数据质量检查**：标记销量为0、价格异常的记录

**数据库表：cleaned_data**
```sql
id              SERIAL PRIMARY KEY
raw_data_id     INTEGER REFERENCES raw_data(id)
platform        VARCHAR(50)
month           INTEGER
category_lv1    VARCHAR(100)
category_lv2    VARCHAR(100)
category_lv3    VARCHAR(100)
item_id         VARCHAR(100)
item_url        TEXT
item_name       TEXT
item_image      TEXT
ref_price       NUMERIC(12,2)
brand_raw       VARCHAR(200)
shop_name       VARCHAR(200)
sales_qty       INTEGER
sales_amount    NUMERIC(14,2)
price           NUMERIC(12,2)
brand_std       VARCHAR(100)
model_std       VARCHAR(100)
clean_job_id    INTEGER
created_at      TIMESTAMP
```

**数据库表：clean_jobs**
```sql
id          SERIAL PRIMARY KEY
file_ids    INTEGER[]
rules       JSONB
status      VARCHAR(20)
row_in      INTEGER
row_out     INTEGER
created_at  TIMESTAMP
```

### 4.4 数据导出模块

**接口**：`POST /api/export`

**请求体**：
```json
{
  "clean_job_id": 5,
  "format": "processed",        // "processed" = 已处理格式
  "split_by": "platform",       // 按平台拆分为多个 Sheet 或多个文件
  "filename_prefix": "Soundbar 7-8月已处理"
}
```

**导出逻辑**（`exporter.py`）：
1. 从 `cleaned_data` 查询数据
2. 按平台分组，每个平台生成一个 xlsx 文件
3. 列顺序严格对齐"已处理"格式：`平台, 月, Lv1~Lv5类目, 宝贝ID, 宝贝链接, 宝贝名称, 宝贝图片, 参考价格, 宝贝品牌, 宝贝店铺名称, 销量, 销售额, 价格, 品牌, 机型`
4. 使用 openpyxl 写入，支持中文文件名
5. 返回下载链接（`/api/export/download/{token}`）

---

## 五、前端页面设计

### 5.1 整体布局

左侧导航栏 + 右侧内容区，导航项：
- **数据上传**（Upload）
- **原始数据**（Raw Data）
- **数据清洗**（Clean）
- **数据导出**（Export）

### 5.2 数据上传页

- 拖拽上传区域（Ant Design `Upload.Dragger`）
- 上传历史列表（文件名、平台、数据量、状态、操作时间）
- 上传后自动展示预览表格（前50行）

### 5.3 原始数据页

- 左侧筛选栏（文件、平台、月份、品牌）
- 右侧数据表格（可配置列、排序、分页）
- 顶部 KPI 卡片（总销量、总销售额）

### 5.4 数据清洗页

- 选择要清洗的文件（多选）
- 配置清洗规则（品牌白名单、去重开关等）
- 点击"开始清洗"，实时展示进度
- 清洗结果预览（清洗前后数量对比）

### 5.5 数据导出页

- 选择清洗任务
- 配置导出格式（文件前缀、是否按平台拆分）
- 点击导出，生成下载链接

---

## 六、边界条件与异常处理

| 场景 | 处理方式 |
|------|---------|
| 上传非 Excel 格式 | 前端校验扩展名，后端返回 400 |
| Excel 列名不匹配 | 模糊匹配列名，匹配失败返回具体报错列 |
| 数值字段含非数值 | 转换时记录日志，置 NULL 并标记 |
| 超大文件（>10MB） | 后台异步处理，前端轮询状态 |
| 重复上传同文件 | 按 filename + row_count 检测，提示用户 |
| 导出中文文件名 | URL encode 编码处理 |

---

## 七、数据流路径

```
用户上传 Excel
    ↓
FastAPI 接收 → pandas 解析 → 校验列名
    ↓
批量写入 raw_data 表（PostgreSQL）
    ↓
前端展示原始数据（分页查询）
    ↓
用户配置清洗规则 → POST /api/clean/run
    ↓
data_cleaner.py → 过滤 + 标准化 → 写入 cleaned_data 表
    ↓
用户触发导出 → exporter.py → openpyxl 生成 xlsx
    ↓
用户下载已处理 Excel
```

---

## 八、预期产出

- 完整可运行的 Web 平台（本地 Docker 一键启动）
- 支持上传 Soundbar 7-9月原始数据三个平台文件
- 数据清洗后可导出与"Soundbar 7-8月已处理"格式一致的 Excel
- 前端界面美观、数据展示流畅（万行数据分页加载）
