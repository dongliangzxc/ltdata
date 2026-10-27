# 匹配结果批量系数与 ID/链接数据修正设计

> 日期：2026-10-23
> 状态：批量系数与 ID/链接筛选已实现；Excel 修正模板/上传修正已取消（见顶部变更说明）
>
> 变更说明（2026-10-23）：需求方确认取消「导出修正模板 + 上传修正文件」，改为在匹配结果页增加「商品ID / 链接」筛选，并支持多选（默认全选当前筛选结果）；多选用于批量调整系数。
> 关联：`问题记录.md` →「匹配结果批量调数与数据修正」

## 1. 背景

匹配结果页 `/match-results` 目前支持：

- 按任务、来源、价格预警、平台、品类、产品系列、品牌、型号、关键词筛选。
- 单条设置价格调整系数、销量调整系数。

不足：

1. 筛选品牌或型号后，只能逐条保存系数，无法对当前筛选结果统一调整。
2. 部分商品数据需要按 ID/链接修正，目前没有“下载修正 → 编辑 → 上传覆盖”的闭环。

## 2. 需求一：筛选后批量调整系数

### 2.1 交互

在匹配结果页筛选区增加按钮：

```text
批量调整系数
```

弹窗：

- 调整对象：`价格系数` / `销量系数`
- 系数：数字输入（支持清空）
- 调整范围：当前 Tab + 当前筛选条件下的全部结果（不是当前页）
- 显示预计影响条数
- 二次确认

示例：

- 筛选品牌 = `科大讯飞`
- 销量系数 = `1.10`
- 点击确认 → 所有符合条件的匹配结果 `sales_coefficient = 1.10`

### 2.2 计算口径

价格系数：

```text
adjusted_price = ROUND(raw_data.price * coefficient, 2)
coefficient 为空 → adjusted_price = NULL（恢复原价）
```

销量系数：

```text
sales_coefficient = coefficient
coefficient 为空 → sales_coefficient = NULL（清除调整）
```

不修改 `raw_data.price` 和 `raw_data.sales_qty`。

### 2.3 后端接口

```http
POST /api/match/reviewed/bulk-coefficient
```

请求：

```json
{
  "clean_job_id": 246,
  "tab": "all",
  "match_source": ["s1"],
  "price_flag": null,
  "keyword": null,
  "platform": null,
  "brand_keyword": "科大讯飞",
  "model_keyword": null,
  "category_code": null,
  "series": null,
  "coefficient_filter": null,
  "target": "sales",
  "coefficient": 1.1
}
```

响应：

```json
{
  "updated_count": 128
}
```

实现要点：

- 复用 `list_reviewed_global` 的筛选条件，抽出共享查询构造器。
- 按匹配结果 ID 分批更新，避免一条超大 SQL。
- 更新后 `touch_clean_job`，让任务最近处理时间更新。
- 价格系数需要关联 `raw_data.price` 计算。
- 系数校验：`0 <= coefficient <= 999.9999`；允许 `null` 表示清除。
- 操作日志建议记录：操作人、筛选条件、目标字段、系数、影响条数、时间。

### 2.4 前端

- 按钮放在筛选区右侧或在汇总卡片上方。
- 打开弹窗时用当前筛选条件请求预计影响条数。
- 确认后调用批量接口，关闭弹窗，刷新列表和汇总。
- 批量操作期间禁用按钮，避免重复提交。
- 成功后清空当前页的单条草稿，避免显示旧值。

## 3. 需求二：按 ID/链接下载修正并上传覆盖

### 3.1 目标

针对部分商品数据错误，允许：

1. 按当前筛选条件下载修正模板。
2. 在 Excel 中修改允许修正的字段。
3. 上传修正文件。
4. 系统按 ID/链接匹配原数据并预览变更。
5. 确认后覆盖原数据。

### 3.2 修正范围（建议第一期）

可修正字段：

- 商品名称 `item_name`
- 原价格 `price`
- 原销量 `sales_qty`
- 原销售额 `sales_amount`
- 参考价 `ref_price`
- 商品链接 `item_url`

暂不支持通过该入口修改：

- 匹配型号
- 品牌码
- 目标品类
- 品类归属

型号/品牌如需调整，继续走「重新选择」或品牌/型号管理。

### 3.3 导出修正模板

```http
GET /api/match/reviewed/correction-template
```

使用与列表一致的筛选参数，导出当前筛选结果。

列设计：

| 列 | 说明 |
|---|---|
| `match_result_id` | 系统匹配结果 ID，用于精确回写 |
| `item_id` | 平台商品 ID |
| `item_url` | 商品链接 |
| `platform` | 平台 |
| `month` | 月份 |
| `country_code` | 国家 |
| `item_name_原值` | 当前商品名称 |
| `price_原值` | 当前原价格 |
| `sales_qty_原值` | 当前原销量 |
| `sales_amount_原值` | 当前原销售额 |
| `ref_price_原值` | 当前参考价 |
| `item_name_修正` | 空=不修改 |
| `price_修正` | 空=不修改 |
| `sales_qty_修正` | 空=不修改 |
| `sales_amount_修正` | 空=不修改 |
| `ref_price_修正` | 空=不修改 |
| `item_url_修正` | 空=不修改 |

说明：

- 原值列只读参考，修正列由用户填写。
- 空值表示不修改；如需清空文本字段，使用 `__CLEAR__`（可选）。
- 导出文件名带任务号/时间，避免覆盖。

### 3.4 上传修正文件

分两步：

1. 上传并预览
   - `POST /api/match/reviewed/correction/import-preview`
   - 解析 Excel，匹配原数据，返回：
     - 可更新条数
     - 未匹配条数
     - 多匹配/歧义条数
     - 字段级变更预览（原值 → 新值）
2. 确认覆盖
   - `POST /api/match/reviewed/correction/import-confirm`
   - 使用预览阶段生成的临时 token 或再次上传文件。
   - 事务内批量更新。

匹配优先级：

1. `match_result_id` 精确匹配。
2. `platform + item_id + month + country_code` 精确匹配。
3. `item_url` 提取 `platform + item_id` 后匹配。
4. 匹配不到或多条命中：该行跳过，进入错误列表，不阻断其他行。

### 3.5 覆盖逻辑

更新 `raw_data`：

- `item_name`、`item_name_norm`
- `price`
- `sales_qty`
- `sales_amount`
- `ref_price`
- `item_url`

同步 `cleaned_data`（同一 `clean_job_id + raw_data_id`）：

- `item_name`
- `price`
- `sales_qty`
- `sales_amount`
- `ref_price`
- `item_url`
- 重新计算 `calc_price = sales_amount / sales_qty`（销量 > 0 时）

如果价格/销量变化：

- 重新执行价格审核，更新 `match_results.price_flag / price_ref`。
- 重新执行修正规则，刷新 `cleaned_data.corrected_sales_qty / corrected_sales_amount`。
- 如果任务已发布：
  - 建议阻止直接覆盖，提示“已发布任务请先处理发布数据或重新发布”；
  - 或允许覆盖但标记“需重新发布”。第一期建议阻止，避免分析库与业务库不一致。

如果商品名称变化：

- 更新 `item_name_norm`。
- 不自动重新匹配型号；用户可手动点「重新匹配」。
- 搜索、展示、导出使用新名称。

### 3.6 修正日志

建议新增 `data_correction_logs`：

- `id`
- `match_result_id`
- `raw_data_id`
- `clean_job_id`
- `field_name`
- `old_value`
- `new_value`
- `operator`
- `created_at`

用途：追溯谁改了哪个字段；后续可做撤销。

### 3.7 幂等与安全

- 修正文件先预览再确认，不能直接覆盖。
- 单次最大行数建议 5000 行。
- 未匹配行不会静默忽略，必须在预览中列出。
- 数值校验：价格、销量、销售额必须是非负数。
- 如果修正后的销量为 0，`calc_price` 置空，避免除零。
- 操作人记录到日志。
- 修正接口需要处理工作台权限，并按任务品类权限校验。

## 4. 页面设计

匹配结果页增加两个入口：

```text
[批量调整系数]  [导出修正模板]  [上传修正]
```

或者放到一个「数据修正」下拉菜单：

```text
数据修正 ▾
  - 下载修正模板
  - 上传修正文件
```

建议：

- 批量系数放在筛选区右侧，和筛选动作紧密关联。
- 修正模板/上传放在表格上方工具栏。
- 上传后弹窗展示预览，不直接覆盖。

## 5. 实施阶段

### 第一阶段

1. 批量价格/销量系数接口和弹窗。
2. 导出修正模板。
3. 上传预览 + 确认覆盖价格/销量/名称等基础字段。
4. 修正日志。
5. 已发布任务默认阻止覆盖。

### 第二阶段（可选）

1. 修正撤销。
2. 修正文件支持型号重新匹配。
3. 批量系数操作撤销。
4. 修正记录独立查询页。

## 6. 待确认

| # | 问题 | 默认方案 | 状态 |
|---|---|---|---|
| 1 | 批量调整的是价格系数还是销量系数？ | 弹窗内可选，默认销量系数 | ⏳ |
| 2 | 批量范围是当前 Tab + 筛选结果，还是所有 Tab？ | 当前 Tab + 当前筛选全部结果 | ⏳ |
| 3 | 批量系数是否需要支持清除？ | 支持，填空即清除 | ⏳ |
| 4 | 修正模板允许修改哪些字段？ | 商品名称、价格、销量、销售额、参考价、商品链接 | ⏳ |
| 5 | 是否允许修正匹配型号/品牌/品类？ | 第一期不允许，继续走重新选择 | ⏳ |
| 6 | 修正上传必须带 `match_result_id` 还是支持仅 ID/链接？ | 优先 match_result_id，同时支持平台+item_id、URL 匹配 | ⏳ |
| 7 | 已发布任务是否允许覆盖？ | 第一期阻止，要求先处理发布数据 | ⏳ |
| 8 | 是否需要修正日志和撤销？ | 日志第一期做，撤销第二期 | ⏳ |
| 9 | 单次修正文件最大行数？ | 5000 行 | ⏳ |
