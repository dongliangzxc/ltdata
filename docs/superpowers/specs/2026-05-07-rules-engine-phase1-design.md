# 规则引擎可配置化 — 第一期设计文档

**日期**：2026-05-07
**范围**：第一期，共三期改造计划
**状态**：已确认，待实现

---

## 背景与目标

现有平台的清洗和匹配逻辑全部硬编码在 `data_cleaner.py` 和 `matcher.py` 中，分析师无法自主维护规则，每次新增干扰词、品牌写法或型号关键词都需要开发介入修改代码并发版。

本期目标：在不破坏现有匹配率的前提下，将三类规则（干扰词、品牌写法、显式匹配规则）迁移到数据库，通过新增的规则管理页面让分析师自主维护。

---

## 方案选择

**选定方案：两层引擎（叠加优先）**

保留现有 S0-S4 算法骨架不变，新增三张规则配置表在前置阶段介入：

- 清洗阶段新增干扰词过滤 + 品牌写法标准化
- 匹配阶段新增 S0.5 显式规则层，优先于 S1-S4 执行
- 无配置时行为与现在完全一致，向前兼容

排除方案：扁平规则表（全量替换 S1-S4）——现有 S1-S4 本质上已是数据驱动（依赖 models 表），全量替换需手工维护数百条规则重复算法能自动完成的工作，得不偿失。

---

## 整体数据流

```
上传原始数据
    │
    ▼
【清洗阶段 data_cleaner.py】
    ├─ 加载 noise_words 表（内存索引）
    ├─ 加载 brand_aliases 表（内存索引）
    ├─ 遍历每条 raw_data：
    │   ├─ 命中干扰词 → 写 filtered_items 存档，跳过
    │   ├─ 未命中 → brand_raw 查 brand_aliases，有映射则覆盖 brand_std
    │   └─ 去重 → 写 cleaned_data（现有逻辑不变）
    │
    ▼
【匹配阶段 matcher.py】
    ├─ S0:   item_url 查 url_mappings（现有，不变）
    ├─ S0.5: item_name 查 match_rules（新增，按 priority 升序）
    │         contains → keyword in item_name_upper
    │         exact    → item_name_upper == keyword_upper
    │         第一条命中 → match_source="s0.5", status="matched"
    └─ S1-S4: 现有算法兜底（不变）
    │
    ▼
【结果处理】
    ├─ 已匹配 → 发布分析库（现有）
    ├─ 待确认 → 人工处理（现有 + 新增品牌未识别分组）
    └─ 被过滤 → filtered_items，可在规则管理页恢复
```

---

## 数据库 Schema

### 新增表

**`noise_words`（干扰词库）**
```sql
id          SERIAL PRIMARY KEY
keyword     VARCHAR(200) NOT NULL
match_field VARCHAR(20) DEFAULT 'item_name'  -- item_name / shop_name / brand_raw
is_active   BOOLEAN DEFAULT TRUE
created_by  VARCHAR(50)
created_at  TIMESTAMP DEFAULT NOW()
UNIQUE(keyword, match_field)
```

**`filtered_items`（干扰项存档）**
```sql
id               SERIAL PRIMARY KEY
raw_data_id      INTEGER REFERENCES raw_data(id)
clean_job_id     INTEGER REFERENCES clean_jobs(id)
matched_keyword  VARCHAR(200)
is_recovered     BOOLEAN DEFAULT FALSE
recovered_at     TIMESTAMP
created_at       TIMESTAMP DEFAULT NOW()
```

**`brand_aliases`（品牌写法库）**
```sql
id          SERIAL PRIMARY KEY
alias_name  VARCHAR(200) NOT NULL    -- 原始写法，如"索尼"
brand_code  VARCHAR(100) NOT NULL    -- 标准品牌码，如"SONY"
is_active   BOOLEAN DEFAULT TRUE
created_by  VARCHAR(50)
created_at  TIMESTAMP DEFAULT NOW()
UNIQUE(alias_name)
```

**`match_rules`（S0.5 显式匹配规则）**
```sql
id          SERIAL PRIMARY KEY
keyword     VARCHAR(200) NOT NULL
match_type  VARCHAR(20) DEFAULT 'contains'   -- contains / exact
model_id    INTEGER REFERENCES models(id)
priority    INTEGER DEFAULT 100              -- 越小越先执行
is_active   BOOLEAN DEFAULT TRUE
created_by  VARCHAR(50)
created_at  TIMESTAMP DEFAULT NOW()
UNIQUE(keyword)
```

### 现有表改动

```sql
-- cleaned_data 新增字段
ALTER TABLE cleaned_data ADD COLUMN is_recovered BOOLEAN DEFAULT FALSE;

-- match_results 新增字段（记录匹配时品牌是否被识别，用于前端分组展示）
ALTER TABLE match_results ADD COLUMN brand_identified BOOLEAN DEFAULT TRUE;
```

---

## 后端改动

### 服务层

**`data_cleaner.py`**：在现有去重逻辑之前插入两个步骤：
1. 启动时从 DB 加载 `noise_words`（active only）和 `brand_aliases`（active only）到内存
2. 每条记录先做干扰词检查：命中 → 写 `filtered_items`（记录 `matched_keyword`），跳过该条记录
3. 未命中则查 `brand_aliases`：alias_name 精准匹配 brand_raw（大写标准化后比较），命中则 `brand_std = brand_code`
4. 后续去重 + 写 `cleaned_data` 逻辑不变

**`matcher.py`**：在 S0 和 S1 之间插入 S0.5：
1. 启动时从 DB 加载 `match_rules`（active only），按 priority 升序排序到内存列表
2. S0 命中 → 跳过 S0.5（现有行为）
3. S0 未命中 → 遍历 match_rules：
   - `contains`：`rule.keyword.upper() in item_name_upper`
   - `exact`：`item_name_upper == rule.keyword.upper()`
   - 命中 → `model_id=rule.model_id, match_status="matched", match_source="s0.5"`，跳过 S1-S4
4. S0.5 未命中 → 走现有 S1-S4（不变）

### 新增 API（`rules_api.py`）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/rules/noise-words` | 查询干扰词列表 |
| POST | `/api/rules/noise-words` | 新增干扰词 |
| DELETE | `/api/rules/noise-words/{id}` | 删除干扰词 |
| PATCH | `/api/rules/noise-words/{id}` | 启用/禁用 |
| GET | `/api/rules/brand-aliases` | 查询品牌写法列表 |
| POST | `/api/rules/brand-aliases` | 新增品牌写法（单条） |
| POST | `/api/rules/brand-aliases/import` | Excel 批量导入（两列：alias_name/brand_code） |
| DELETE | `/api/rules/brand-aliases/{id}` | 删除 |
| GET | `/api/rules/match-rules` | 查询匹配规则列表（按 priority 升序） |
| POST | `/api/rules/match-rules` | 新增规则 |
| PATCH | `/api/rules/match-rules/{id}` | 修改（含 priority 调整） |
| DELETE | `/api/rules/match-rules/{id}` | 删除 |
| GET | `/api/rules/filtered-items` | 查询干扰项存档（支持 clean_job_id/keyword 筛选，分页） |
| POST | `/api/rules/filtered-items/{id}/recover` | 恢复单条：将 raw_data 重新写入 cleaned_data（is_recovered=true），同时将 filtered_items 记录标记为 is_recovered=true + recovered_at=now()（记录保留用于审计，不删除） |
| POST | `/api/rules/filtered-items/recover-batch` | 批量恢复（body: `{ids: [1,2,3]}`），逻辑同单条 |

### 现有接口调整

- `GET /api/match/{job_id}/pending`：响应 item 增加 `brand_identified: bool` 字段。判断逻辑：在 S1-S3 阶段，只要 `brand_raw` 通过 `brand_code_index` 或 `brand_name_index` 找到了候选品牌组（即品牌被识别），即使最终没找到型号，`brand_identified=true`；S4 全局兜底未识别品牌时为 `false`。实现时在 `MatchResult` 表新增 `brand_identified BOOLEAN` 字段，由 matcher 写入。
- `GET /api/clean/jobs/{job_id}/preview`：响应增加 `filtered_count: int` 字段

---

## 前端改动

### 新增 `/rules` 页面

导航栏在「数据清洗」之后新增「规则管理」入口，路由 `/rules`。

页面包含四个 Tab：

**Tab 1 — 干扰词库**
- 表格列：关键词 / 匹配字段 / 状态 / 操作（删除/启禁）
- 顶部：关键词输入框 + 匹配字段下拉（item_name/shop_name/brand_raw）+ 添加按钮
- 支持启用/禁用（不删除，保留历史）

**Tab 2 — 品牌写法库**
- 表格列：原始写法 / 标准品牌码 / 操作
- 支持单条添加（两个输入框）
- 支持 Excel 批量导入（上传 → 预览行数/错误 → 确认导入，复用现有 Excel 导入交互模式）

**Tab 3 — 匹配规则**
- 表格列：优先级 / 关键词 / 匹配方式 / 目标型号 / 操作
- 按 priority 升序排列，priority 字段可直接在表格内编辑
- 新增/编辑弹窗：关键词输入、匹配方式选择（包含/精准）、型号搜索下拉（复用现有组件）、优先级输入

**Tab 4 — 干扰项存档**
- 表格列：商品名称 / 原始品牌 / 触发词 / 所属清洗任务 / 操作（恢复）
- 顶部筛选：清洗任务下拉、触发词搜索
- 支持单条恢复和批量勾选恢复

### `/match` 页面改造

待处理条目区域新增 Tab 分组：

```
待处理条目
├── 未识别品牌  [N]  ← 新增 Tab（brand_identified=false）
└── 待确认     [M]  ← 现有 Tab
```

「未识别品牌」Tab 顶部展示提示：
> _"以下商品的品牌在系统中未能识别，建议先前往「规则管理 → 品牌写法库」补充写法后重新执行匹配，效率高于逐条人工确认。"_
> 右上角放「前往规则管理」快捷链接。

### `/clean` 页面改造

清洗完成的结果卡片改为：

```
输入行数   清洗输出   被过滤（干扰词）
  1,200      980          220        [查看被过滤数据 →]
```

「查看被过滤数据」跳转 `/rules?tab=filtered&job_id={id}`，自动定位到干扰项存档 Tab 并按当前任务筛选。

---

## 兼容性与风险

| 风险点 | 说明 | 缓解方式 |
|--------|------|---------|
| 干扰词误过滤 | 关键词设置过宽导致有效数据被过滤 | filtered_items 存档 + 恢复流程 + 清洗结果展示 filtered_count |
| match_rules 误命中 | 关键词太短导致不相关商品被错误匹配 | 规则页面添加提示建议关键词 ≥5 字符；exact 模式不受限制 |
| brand_aliases 覆盖错误 | 写法映射错误导致 brand_std 被污染 | alias_name UNIQUE 约束；支持禁用（不删除）便于排查 |
| 性能 | 干扰词/品牌别名/规则全量加载到内存 | 数量级预计百条量级，内存开销可忽略；如超万条再考虑分批加载 |

---

## 不在本期范围内

- 按品类隔离规则（全局共用，后续如有需求再扩展）
- 规则版本历史 / 回滚
- 规则导出
- 属性关键词匹配（规则4，第二期考虑）
