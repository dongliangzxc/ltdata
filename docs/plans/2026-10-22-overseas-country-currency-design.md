# 海外国家与人民币汇率支持设计方案

> 日期：2026-10-22
> 状态：已确认，开发中
> 关联：`问题记录.md` →「海外国家与汇率」

## 1. 背景与目标

平台目前通过 `upload_files.data_region` 区分「国内 / 海外」，但没有记录海外数据具体属于哪个国家，也没有汇率和人民币口径。新需求如下：

1. 海外数据需要记录到具体国家，沿上传 → 原始数据 → 清洗链路透传，用于清洗详情展示。
2. 提供国家与汇率维护入口，维护 20+ 个国家 / 币种与人民币的汇率。
3. 清洗任务详情/预览增加货币转换能力，默认显示原币，可切换人民币或其他币种。

本方案的核心原则：

- **原币数据不破坏**：上传的 `price`、`sales_amount` 等字段继续保存原币金额，不直接改成人民币。
- **国家只做展示字段**：国家记录在原始数据行上，参与去重，但不拆分清洗任务。
- **人民币是展示口径**：人民币金额 = 原币金额 × 当前汇率，仅在清洗详情/预览展示，不写入原始数据。
- **不猜历史数据**：历史海外数据没有国家时不自动猜测，标记为待补充。

## 2. 现状梳理

- `UploadFileRecord.data_region` 已存在，取值为 `domestic / overseas`（`backend/app/models/schemas.py:26`）。
- 上传确认接口已接收 `data_region`、`data_year`、`data_month`（`backend/app/api/upload.py:877`）。
- 上传历史页已有「国内 / 海外」筛选（`frontend/src/pages/Upload/index.tsx:951`）。
- `raw_data` 当前唯一键为 `(item_id, month, platform)`（`sql/init.sql:57`）。
- `published_items` 当前唯一键为 `(platform, item_id, month)`（`backend/app/models/analytics_db.py:25`）。
- 清洗队列当前按 `品类 + 平台 + 月份` 聚合（`backend/app/services/clean_task_snapshot.py:264`）。
- 清洗任务详情页是 `/match`（`frontend/src/components/Layout/index.tsx:115`），价格展示在复核详情、候选、转移弹窗等位置。
- 匹配结果页是 `/match-results`，价格列定义在 `frontend/src/pages/MatchResults/columns.tsx`。
- 看板、查询工作台、导出都直接使用 `published_items` 的原币金额字段。

## 3. 核心概念

| 概念 | 说明 |
|---|---|
| 地区 region | 继续保留 `domestic / overseas`，由国家自动推导：`CN` 为国内，其余为海外 |
| 国家 country | ISO 3166-1 alpha-2 国家码，如 `US / DE / JP / GB`，是新增的数据维度 |
| 币种 currency | 国家对应币种，如 `USD / EUR / JPY / GBP` |
| 汇率 rate | `1 单位外币 = rate 元人民币`，例如 USD 汇率为 7.20 |
| 原币金额 | 上传 Excel 中的 `price / sales_amount / ref_price` 等，保持不动 |
| 人民币金额 | 展示派生值，`原币金额 × rate`，仅用于清洗详情/预览 |
| 目标币种 | 清洗详情中选择的展示币种，按「原币 → 人民币 → 目标币种」换算 |

## 4. 已确认方向（轻量版）

需求方已确认：

1. **同一品类 + 平台 + 月份可能同时存在多个国家的数据，但不按国家拆分清洗任务**。
2. **国家只作为一个展示字段**，记录到数据上即可，不需要参与清洗任务分组。
3. **第一期人民币只做清洗任务详情 / 清洗结果预览**，发布、看板、查询工作台、导出暂不改。
4. **清洗详情增加货币转换能力**：后端返回原币金额和人民币金额，前端负责换算；选择其他目标币种时按「原币 → 人民币 → 目标币种」中转。

基于以上确认，采用以下轻量方案：

- 上传时选择国家（或按文件/行映射国家），国家写入 `upload_files` 和 `raw_data`。
- 待入清洗队列仍按 `品类 + 平台 + 月份` 聚合，**不按国家拆分任务**。
- `cleaned_data` 透传 `country_code`，或者清洗详情/预览通过 `raw_data_id` 关联取国家。
- 清洗任务不需要 `country_code`；同一任务内允许存在多国家、多币种数据。
- 汇率维护页维护「国家 / 币种 → 人民币」的汇率。
- 清洗详情接口返回每条数据的原币金额、原币币种、人民币金额，以及当前启用币种的汇率表；前端用人民币中转计算目标币种。
- 发布、看板、查询工作台、导出保持原样，本期不增加国家/人民币字段。

### 4.1 为什么不把国家放在清洗任务上

当前清洗队列按 `raw_data` 的 `品类 + 平台 + 月份` 聚合。如果只在清洗任务上记录国家，系统无法知道任务内哪些原始数据属于该国家；而需求方已确认同一个 `品类 + 平台 + 月份` 可能混多个国家，因此国家必须记录在原始数据行上，而不是任务上。

任务仍然可以保持「一个任务处理一个品类/平台/月份范围」，任务内不同国家的行各自携带国家，清洗详情按行展示和换算即可。

### 4.2 去重

因为同一商品可能在不同国家市场重复出现，`raw_data` 去重键建议从 `(item_id, month, platform)` 调整为 `(country_code, item_id, month, platform)`。如果不调整，后上传国家的数据可能被前一个国家判为重复而跳过。

### 4.3 多文件上传与国家选择

需求方确认：一次可以选择多个文件上传，文件读取完成后让用户选择国家；国家来自 master 在平台上预先配置好的国家列表。

建议流程：

1. master 先在「国家与汇率」页面配置好国家、币种和汇率。
2. 用户在数据上传页一次拖入多个 Excel / CSV 文件。
3. 前端逐个读取文件表头，得到每个文件的 `temp_file_id`、文件名、推断平台和推荐模板。
4. 页面展示文件列表，每一行包含：文件名、平台、推荐模板、国家选择器。
5. 国家默认按「国内 / 海外」逻辑处理：国内默认 CN；海外必须选择具体国家。
6. 支持「批量设置国家」，但最终以每个文件自己的国家为准；同一个批次允许多个国家文件一起上传。
7. 用户逐个文件确认列映射后入库；国家随该文件的 `/upload/confirm` 请求提交。
8. 后端按文件写入 `upload_files.country_code`，并把该国家写入该文件产生的每一条 `raw_data.country_code`。

已确认：**一个文件只属于一个国家**，不支持同一个文件内按行混合多个国家；多文件上传时每个文件分别选择国家，同一批次允许多个国家。

前端改造点：

- `Upload.Dragger` 改为 `multiple`。
- 新增「待处理文件列表」状态，保存每个文件的 `temp_file_id`、表头结果、推荐模板、country_code、映射状态。
- 现有单文件 `mapping` 步骤改为对列表中某个文件继续操作，完成后回到列表处理下一个。
- 全部文件处理完成后再进入汇总预览。

后端改造点：

- `/upload/confirm` 增加 `country_code`，校验国家是否启用、海外是否必填。
- 写入 `upload_files.country_code` 和 `raw_data.country_code`。
- 去重查询带 `country_code`。
- 其他上传逻辑不变，仍按单个文件处理。

## 5. 数据模型设计

### 5.1 国家与币种表 `countries`

```sql
CREATE TABLE countries (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    code            VARCHAR(8)   NOT NULL COMMENT 'ISO 国家码，如 US/DE/JP；CN=中国',
    name_cn         VARCHAR(64)  NOT NULL COMMENT '中文名',
    name_en         VARCHAR(128) NULL COMMENT '英文名',
    currency_code   VARCHAR(8)   NOT NULL COMMENT '币种，如 USD/EUR/JPY/CNY',
    currency_symbol VARCHAR(8)   NULL COMMENT '币种符号，如 $/€/¥',
    region          VARCHAR(16)  NOT NULL DEFAULT 'overseas' COMMENT 'domestic/overseas',
    is_active       TINYINT      NOT NULL DEFAULT 1,
    sort_order      INT          NOT NULL DEFAULT 100,
    created_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_countries_code (code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='国家与币种主数据';
```

初始数据：内置 `CN`（中国/CNY/国内/汇率 1），其余 20+ 国家由需求方提供清单后初始化；页面支持新增、停用。

### 5.2 汇率表 `exchange_rates`

需求方确认：**按国家维护汇率**，每个国家一条当前汇率；即使多个国家使用同一币种，也分别维护。

```sql
CREATE TABLE exchange_rates (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    country_code  VARCHAR(8)    NOT NULL COMMENT '国家码',
    currency_code VARCHAR(8)    NOT NULL COMMENT '币种快照，如 USD/EUR/JPY/CAD',
    rate_to_cny   DECIMAL(18,8) NOT NULL COMMENT '1 外币 = N 人民币',
    source        VARCHAR(32)   NOT NULL DEFAULT 'manual' COMMENT 'manual/import',
    operator      VARCHAR(100)  NULL,
    remark        VARCHAR(500)  NULL,
    created_at    DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at    DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_fx_country (country_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='国家兑人民币汇率';
```

说明：

- `rate_to_cny` 精度 8 位，兼容 JPY、KRW、IDR 等小数值币种。
- 国内 CN 固定汇率 1，不落配置记录，避免误改。
- 每个国家一条当前汇率；同一币种（如 EUR）在多个国家分别维护，允许各自独立修改。
- 本期是「当前汇率」，修改后清洗详情展示立即变化；如果需要汇率历史版本，再给该表增加 `effective_month`，本期不做。
- 因为按国家维护，前端换算的目标也应选择「国家（币种）」，而不是只选币种，避免同一币种多条汇率时无法确定用哪条。

### 5.3 各表字段新增

| 表 | 新增字段 | 用途 |
|---|---|---|
| `upload_files` | `country_code` | 上传批次归属国家 |
| `raw_data` | `country_code` | 原始数据国家，用于展示和换算 |
| `cleaned_data` | `country_code` | 清洗产物透传国家（也可通过 `raw_data_id` 关联） |

本期不改：

- `clean_jobs`：任务不按国家拆分，不加国家字段。
- `published_items`：本期不做发布后的国家/人民币口径。
- `match_results`：通过 `raw_data_id` 关联国家。
- `item_url_mappings`、`item_exclusions`：本期不改匹配键。
- `historical_mappings`：后续海外历史库再评估。

### 5.4 唯一键调整

必须调整：

- `raw_data`：`uq_raw_dedup` 改为 `(country_code, item_id, month, platform)`。
  同一 ASIN/商品 ID 在不同国家市场可能重复，不加国家会把不同国家数据误判为重复。

本期不需要调整：

- `published_items` 唯一键不变。
- `item_url_mappings`、`item_exclusions` 匹配键不变。

## 6. 数据流设计

### 6.1 上传

1. 用户可一次选择多个文件；文件读取完成后，在文件列表中为每个文件选择国家。
2. 国家必须来自 master 配置且处于启用状态。
3. 选择海外国家时，该文件按海外数据处理；国内默认 CN。
4. 上传确认时每个文件分别传自己的 `country_code`，后端根据国家表反推 `data_region`。
5. 写入 `upload_files.country_code` 和该文件产生的每一条 `raw_data.country_code`。
6. 去重查询必须带上 `country_code`。
7. 上传预览和上传历史展示国家、币种。
8. 同一批次允许多个国家文件；一个文件只对应一个国家。

本期不在上传时计算或快照汇率；人民币金额在清洗详情查询时按当前汇率计算。

### 6.2 分发与清洗任务

1. 分发、清洗队列、清洗任务逻辑**保持现状**，不按国家分组。
2. 同一清洗任务内可以出现多个国家的数据；每一行通过 `raw_data.country_code` 识别国家。
3. 清洗任务列表/详情不需要国家字段，也不改变任务创建、追加、重建、转移逻辑。
4. 清洗任务详情中的每一条数据展示自己的国家。
5. 旧任务中的旧数据没有国家，显示「未记录国家」，不参与人民币换算。

### 6.3 清洗与匹配

1. `data_cleaner.py` 写 `cleaned_data` 时透传 `country_code`；也可以在查询时通过 `raw_data_id` 关联取国家。
2. 匹配算法、候选、确认、撤销等逻辑不变。
3. 复核详情接口 `GET /api/match/items/{match_id}/review-detail` 新增返回：
   - `country_code`、`country_name`、`currency_code`
   - `price_cny`、`ref_price_cny`、`sales_amount_cny`、`adjusted_price_cny`
   - 顶层 `rates`：当前启用国家 → `{currency_code, rate_to_cny}`，供前端换算目标国家/币种
4. 清洗详情内用到的列表、汇总接口按同样口径返回原币和人民币金额；匹配结果独立页本期不改。
5. 人民币金额由后端按「原币金额 × 该国家 rate_to_cny」计算；国家为 CN 时汇率固定 1。
6. 汇率缺失时 `price_cny` 等返回 NULL，前端只显示原币并提示「未配置该国家汇率」。

### 6.4 发布到分析库

本期不改。发布数据继续保存原币金额，不增加国家/人民币字段；后续如果看板、查询工作台、导出需要跨国家人民币汇总，再单独做二期。

### 6.5 看板、查询工作台、导出

本期不改。页面仍按原币展示和汇总；跨国家/跨币种金额不能直接相加，这一点在二期处理。本期只在清洗任务详情/预览提供货币换算展示，不影响已发布数据。

## 7. 清洗详情货币转换

### 7.1 位置

- 清洗任务详情 `/match`：复核详情、已匹配/待确认表格、转移弹窗中的价格。
- 清洗结果预览 `/clean` 预览弹窗。

本期不做：匹配结果 `/match-results`、数据调整、查询工作台、数据看板、导出。

### 7.2 交互

在清洗详情顶部增加一个「显示币种」选择器：

- 默认：`原币`（每条数据展示自己的国家/币种，例如 USD 行显示 `$129.99`）。
- 可选：`人民币`，以及 master 配置的其他国家（展示为「国家名（币种）」，如「加拿大（CAD）」）。
- 选择人民币时：USD 行显示 `≈¥939.03`。
- 选择加拿大时：按 `USD → CNY → CAD` 计算，即先用美国汇率换成人民币，再除以加拿大汇率。
- 选择原币时：行内币种一致则直接显示原币金额；如果目标国家/币种与行不同，也走人民币中转。
- 编辑「调整后价格」「调整系数」时输入仍然是原币，换算结果只读展示，避免误把目标币种当原币录入。
- 汇率缺失时只显示原币，并提示「未配置 XX 国家汇率」。
- 选择器状态保存在浏览器本地（`localStorage`），不写用户表。

因为汇率按国家维护，目标选择器按「国家（币种）」列出，不单独按币种列出，避免 EUR 等多国共用币种时不知道使用哪条汇率。

### 7.3 前端换算公式

后端返回：

- 每条记录：`country_code`、`currency_code`、`price`、`sales_amount`、`ref_price`、`adjusted_price`、对应的 `*_cny` 字段。
- 顶层：`rates = { US: {currency_code: "USD", rate_to_cny: 7.20}, CA: {currency_code: "CAD", rate_to_cny: 5.25}, ... }`。

前端换算：

```
原币 → 人民币:  amount_cny = amount_original * rates[source_country].rate_to_cny
人民币 → 目标国家: amount_target = amount_cny / rates[target_country].rate_to_cny
原币 → 目标国家: amount_target = amount_original * rates[source_country].rate_to_cny / rates[target_country].rate_to_cny
```

如果后端已经返回 `amount_cny`，前端直接用 `amount_cny / rates[target_country].rate_to_cny`，避免重复乘源国家汇率。

说明：人民币作为目标时汇率固定为 1；源国家为 CN 时也固定为 1。目标国家与源国家相同时直接显示原币，避免换算误差。

## 8. 国家与汇率配置（仅 master）

### 8.1 菜单位置与权限

放在「系统配置」下，新增「国家与汇率」，仅 master 可见、可操作；普通用户完全看不到该菜单。

已确认 master 就是现有管理员账号：`users.is_admin=1`（`backend/app/core/permissions.py:104`），不新增独立角色。

权限落地：

- 前端菜单项设置 `adminOnly: true`，非管理员不渲染。
- 路由增加管理员校验，非管理员直接 403。
- 写接口（新增/编辑/删除国家、汇率）后端强制 `is_admin=1`。
- 国家下拉列表只读接口允许已登录用户访问，因为上传页需要选择国家；也可以直接随 `/upload/headers` 返回启用国家列表，避免暴露完整配置接口。
- 汇率详情只随清洗详情接口返回，不需要给普通用户开放汇率配置接口。

### 8.2 页面设计

两个 Tab：

**国家与币种**

- 列表：国家码、中文名、英文名、币种、币种符号、地区、状态、排序。
- 新增/编辑/停用。
- 国内 CN 不允许删除或改币种。

**汇率维护**

- 筛选：国家、币种。
- 列表：国家、币种、币种符号、汇率（1 外币 = N 人民币）、更新时间、操作人、备注、操作。
- 每个国家一条当前汇率，新增/编辑/删除。
- 同一币种在多个国家分别维护，允许各自修改；页面可提示同币种汇率不一致，但不强制同步。
- 修改汇率后，清洗详情的人民币换算立即使用新汇率，不做历史快照。

### 8.3 本期不做重算

本期汇率仅用于清洗详情展示，不写入原始数据、不清洗产物、不写发布库，因此不需要重算任务。修改汇率后刷新清洗详情即可看到新换算结果。

## 9. 接口设计

| 接口 | 权限 | 说明 |
|---|---|---|
| `GET /api/countries/options` | 已登录 | 启用国家下拉选项，供上传页使用 |
| `GET /api/countries` | master | 国家配置列表，支持 `is_active`、`region` |
| `POST /api/countries` | master | 新增国家 |
| `PUT /api/countries/{code}` | master | 编辑国家 |
| `DELETE /api/countries/{code}` | master | 停用/删除国家 |
| `GET /api/exchange-rates` | master | 汇率配置列表，支持 `country_code` |
| `POST /api/exchange-rates` | master | 新增国家汇率 |
| `PUT /api/exchange-rates/{id}` | master | 修改国家汇率 |
| `DELETE /api/exchange-rates/{id}` | master | 删除国家汇率 |

上传确认接口新增 `country_code`；清洗任务详情/预览接口新增返回 `country_code`、`currency_code`、`*_cny` 字段和顶层 `rates`。发布、分析、导出接口本期不改。

## 10. 迁移与兼容

1. 新增 Alembic 迁移（建议 `p65..._overseas_country_currency.py`），同时更新：
   - `sql/init.sql`
   - `sql/maintenance/fix_prod_migrations.sql`
   - ORM 模型
2. 历史数据回填：
   - `data_region='domestic'` 或为空的旧上传数据 → `country_code='CN'`。
   - `data_region='overseas'` 的旧数据 → 国家无法确定，`country_code NULL`，标记「待补充国家」；不猜测、不默认 CN。
   - `published_items` 本期不改，不存在回填问题。
3. 旧的 `data_region` 字段保留，作为兼容字段和列表筛选；新数据由 `country_code` 推导后写入。
4. 唯一索引调整涉及大表，需要评估停机窗口或使用在线 DDL：
   - `raw_data` 可能有千万行，新增列、回填、重建唯一索引都要单独评估执行时间。
   - 建议先加列（可空）→ 后台回填 CN → 再重建唯一索引。
5. 旧前端/旧接口兼容：
   - 不传 `country_code` 且 `data_region=domestic` → 默认 CN。
   - 不传 `country_code` 且 `data_region=overseas` → 返回 400，要求选择国家。

## 11. 测试要点

后端：

- 汇率查询：按币种取当前汇率，CNY 固定 1，缺失返回空。
- 上传：批量文件可为每个文件选国家；国内默认 CN；海外必填国家；每条 raw_data 写入对应文件的国家。
- 去重：同 item_id/month/platform、不同国家不被误判重复。
- 清洗：任务分组逻辑不变；cleaned_data 透传国家；同一任务可存在多国家。
- 清洗详情：每条返回原币、人民币、币种、汇率表；缺汇率时人民币为空。
- 前端换算：USD→CNY、USD→CAD（经 CNY）结果正确。
- 权限：非 master 无法访问国家/汇率配置接口和页面。
- 迁移：旧 domestic 数据回填 CN；旧 overseas 数据保持待补充。

前端：

- 上传页支持多选文件，文件列表逐行显示国家选择器；未选国家的海外文件不能确认。
- 批量设置国家可用，但每个文件保留自己的国家。
- 清洗任务详情/预览显示国家列和币种选择器。
- 选择人民币显示 `≈¥`；选择 CAD 按 USD→CNY→CAD 换算；编辑仍为原币。
- 国家与汇率配置页仅 master 菜单可见，新增/编辑/删除受权限保护。

## 12. 实施阶段

**第一阶段（本期）**

1. 国家表、币种汇率表、迁移和历史回填。
2. master 专属「国家与汇率」配置页与权限。
3. 多文件上传、逐文件选择国家，`upload_files` / `raw_data` 记录国家，调整 `raw_data` 去重键。
4. 清洗产物透传国家，清洗详情/预览返回原币、人民币和汇率表。
5. 前端币种选择器与换算展示。

**后续（不在本期）**

1. 匹配结果、数据调整人民币展示。
2. 发布写入国家与人民币字段。
3. 数据看板、查询工作台国家筛选与人民币汇总。
4. 导出增加国家、币种、汇率、人民币列。
5. 海外历史库、URL 映射/排除库国家隔离。
6. 汇率月度历史、自动抓取、操作日志。

## 13. 待确认问题

| # | 问题 | 默认方案 | 状态 |
|---|---|---|---|
| 1 | 20+ 国家的具体清单、ISO 码和币种由谁提供？ | 先用 CN + 常见国家种子，需求方补充完整清单 | ⏳ |
| 2 | 多文件上传时，国家是按每个文件分别选，还是一个批次统一选？ | 每个文件分别选择，允许同一批次混合多个国家 | ✅ |
| 3 | 汇率维护按国家还是按币种？ | 按国家维护，每个国家一条当前汇率；同一币种多国分别维护 | ✅ |
| 4 | 汇率只维护当前值，还是按月维护历史？ | 本期只维护当前值；历史版本后续再加 | ⏳ |
| 5 | 汇率由人工维护还是接第三方自动获取？ | 先人工维护，保留自动抓取扩展 | ⏳ |
| 6 | 汇率缺失时允许上传还是阻止上传？ | 允许上传，人民币显示为空并提示 | ⏳ |
| 7 | 显示币种选择器默认选什么？ | 默认「原币」，可选人民币和其他启用国家（展示国家+币种） | ⏳ |
| 8 | 目标币种换算是否统一经人民币中转？ | 是，原币 → 人民币 → 目标国家/币种 | ✅ |
| 9 | 本期人民币只做清洗详情/预览吗？ | 是，发布、看板、查询工作台、导出本期不改 | ✅ |
| 10 | 清洗任务是否按国家单独分组？ | 不按国家拆分，国家仅作为行级展示字段 | ✅ |
| 11 | 同一品类+平台+月份是否可能有多国家数据？ | 可能，任务内允许多国家，按行展示 | ✅ |
| 12 | 历史海外数据没有国家如何处理？ | 保留 NULL，页面标记待补充，不猜测 | ⏳ |
| 13 | 国家与汇率配置是否只给 master？ | 是，仅 master 可见和操作，普通用户只能在上传页选择国家 | ✅ |
| 14 | master 是否等同现有 `is_admin=1` 管理员？ | 是，复用现有管理员账号，不新增独立角色 | ✅ |
| 15 | 海外数据 Excel 表头、金额单位是否与国内一致？ | 假设一致，金额为当地币种 | ⏳ |
| 16 | 上传文件本身是否可能混合多个国家？ | 不会，一个文件只选一个国家 | ✅ |
