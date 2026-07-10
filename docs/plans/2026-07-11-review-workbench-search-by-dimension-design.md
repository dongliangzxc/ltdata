# 任务复核工作台：搜索维度下拉框设计

## 背景

匹配页 [Match/index.tsx](../../frontend/src/pages/Match/index.tsx) 的"任务复核工作台"卡片右上角有一个搜索框，目前仅按商品名称（`RawDataRecord.item_name`）模糊搜索。用户希望能够扩展该搜索框，通过一个下拉框在三个搜索维度中切换：

- 商品名称
- 原品牌（用户上传的原始品牌文本）
- 入库品牌（型号库里挂着的规范化品牌）

同一时间只能选一个维度，不做多维度组合。

## 范围

**In scope**

- 在复核工作台顶部搜索框左侧新增一个 `Select`，允许用户切换搜索维度。
- 后端 `list_pending`（复核工作台 7 个 tab）和 `list_filtered_items`（干扰项过滤 tab）新增 `search_by` 参数。
- 干扰项 tab 只允许"商品名称"和"原品牌"两个维度；从其他 tab 切到干扰项 tab 时，若当前维度是"入库品牌"则回落到"商品名称"。
- "入库品牌"维度支持通过 `brand_code`（例如 `DJI`）或品牌名 `Brand.brand_name`（例如 `大疆`）任一模糊匹配。
- 切换搜索维度时清空当前输入并重置页码。
- 后端替换掉干扰项接口原本对 `matched_keyword` / `intervention_rule_name` / `matched_reason` 的搜索行为。

**Out of scope**

- 不支持多个维度组合搜索。
- 不改变复核工作台其他筛选控件（品类筛选、排序）。
- 不改变匹配结果列表或已发布库的搜索行为。
- 不引入服务端全文索引或引擎变更；沿用现有 `ilike` 模糊匹配。

## 决策记录（本次会话已确认）

| # | 问题 | 结论 |
|---|------|------|
| 1 | "入库品牌"具体指什么？ | 图中"入库品牌"栏，指通过 `model_id` 关联的 `ModelRecord.brand_code` |
| 2 | 输入英文编码还是中文品牌名？ | 两者都支持：`brand_code` 或品牌表 `brand_name` 任一 `ilike` 匹配 |
| 3 | 下拉框的放置方式？ | 搜索框左侧独立一个 `Select` |
| 4 | 默认维度 & 切换维度时的行为？ | 默认"商品名称"；切换维度时清空输入 + 重置页码 + 触发搜索刷新 |
| 5 | 搜索维度是否覆盖所有 8 个 tab？ | 是；`list_pending` 和 `list_filtered_items` 都支持 `search_by` |
| 6 | 干扰项 tab 下如何处理"入库品牌"？ | 干扰项 tab 的下拉框只显示"商品名称"和"原品牌"两个选项；切到干扰项 tab 时若维度为"入库品牌"则自动回落到"商品名称" |
| 7 | 干扰项 tab 是否保留原来按"命中规则/关键词"搜索的能力？ | 不保留 |

## 前端设计

### State

在 [Match/index.tsx](../../frontend/src/pages/Match/index.tsx) 的 `MatchPage` 组件里新增：

```ts
type SearchBy = 'item_name' | 'brand_raw' | 'brand_code'
const [searchBy, setSearchBy] = useState<SearchBy>('item_name')
```

### UI 结构

在 `Card` `任务复核工作台` 的 `extra` `Space` 内，将现有 `Input.Search` 替换为：

```tsx
<Select
  value={searchBy}
  onChange={handleChangeSearchBy}
  style={{ width: 130 }}
  options={searchByOptions}   // 根据 activeTab 生成
/>
<Input.Search
  placeholder={searchPlaceholder[searchBy]}
  allowClear
  style={{ width: 180 }}
  value={keyword}             // 由受控值改为受控组件
  onChange={e => setKeyword(e.target.value)}
  onSearch={v => { setKeyword(v); setPage(1) }}
/>
```

- `searchByOptions`：
  - 干扰项 tab：`[商品名称, 原品牌]`
  - 其他 tab：`[商品名称, 原品牌, 入库品牌]`
- `searchPlaceholder`：`{ item_name: '搜索宝贝名称', brand_raw: '搜索原品牌', brand_code: '搜索入库品牌' }`。
- 现有 `Input.Search` 是非受控的，为了让"切换维度"能清空输入内容，需要改成受控（`value` + `onChange`）。

### 切换维度

```ts
function handleChangeSearchBy(next: SearchBy) {
  setSearchBy(next)
  setKeyword('')
  setPage(1)
}
```

`refreshDeps` 里增加 `searchBy`，`listPendingMatches` / `listFilteredItems` 的请求体新增 `search_by: searchBy` 参数。切换 tab 时，若目标是 `filtered` 且当前 `searchBy === 'brand_code'`，回落到 `'item_name'` 并清空 `keyword`（在 `Tabs` `onChange` 里处理）。

### 请求参数

- `listPendingMatches(selectedJobId!, { ..., search_by: searchBy })`
- `listFilteredItems({ ..., search_by: searchBy })`

`frontend/src/services/api.ts` 里两个函数的 `params` 都是 `Record<string, unknown>`，无需类型变动。

## 后端设计

### `list_pending`（[backend/app/api/match_api.py](../../backend/app/api/match_api.py) L279）

新增：

```python
search_by: str = Query("item_name")
```

白名单 `{"item_name", "brand_raw", "brand_code"}`；不合法值回落为 `item_name`。

当 `keyword` 非空时，按 `search_by` 分派 where：

- `item_name` → `RawDataRecord.item_name.ilike(f"%{keyword}%")`（保持现状）
- `brand_raw` → `RawDataRecord.brand_raw.ilike(f"%{keyword}%")`
- `brand_code` → 在现有查询上 `outerjoin(BrandRecord, BrandRecord.brand_code == ModelRecord.brand_code)`；条件 `ModelRecord.brand_code.ilike(...) | BrandRecord.brand_name.ilike(...)`

现有查询已经 `outerjoin(ModelRecord)`，因此接入品牌表只需要多一次 `outerjoin`。

### `list_filtered_items`（[backend/app/api/rules_api.py](../../backend/app/api/rules_api.py) L434）

新增：

```python
search_by: str = Query("item_name")
```

白名单 `{"item_name", "brand_raw"}`；其他值回落为 `item_name`。

当 `keyword` 非空时：

- `item_name` → `RawDataRecord.item_name.ilike(f"%{keyword}%")`
- `brand_raw` → `RawDataRecord.brand_raw.ilike(f"%{keyword}%")`

**移除**原本对 `matched_keyword` / `intervention_rule_name` / `matched_reason` 的三路 `ilike` 条件。

## 数据流

搜索维度切换流程：

1. 用户点击左侧下拉框选择新维度。
2. 前端 `setSearchBy(next)`，同时清空 `keyword` 与 `setPage(1)`。
3. `refreshDeps` 变化触发 `useRequest` 重新拉取，`search_by` 携入请求。
4. 后端根据 `search_by` 在对应字段上执行 `ilike` 模糊匹配（此时 `keyword` 为空，故返回全部数据）。
5. 用户输入关键词后按回车或点搜索图标 → `setKeyword(v)` 触发再次拉取。

Tab 切换到干扰项时：

1. 若 `searchBy === 'brand_code'`，`setSearchBy('item_name')` + `setKeyword('')`。
2. 现有 tab 切换逻辑继续走。

## 错误处理

- 后端遇到非法 `search_by` 值时回落到默认，不返回错误，避免阻塞前端。
- 前端受控 `Input.Search` 的 `value` 保证清空时输入框视觉一致。
- 现有 `useRequest` 的错误提示逻辑保持不变。

## 测试

**后端**（[backend/tests](../../backend/tests) 下新增用例）

- `list_pending`
  - `search_by=item_name` + `keyword=大疆` → 按商品名称模糊匹配（现有行为）。
  - `search_by=brand_raw` + `keyword=大疆` → 按 `brand_raw` 模糊匹配。
  - `search_by=brand_code` + `keyword=DJI` → 命中 `ModelRecord.brand_code`。
  - `search_by=brand_code` + `keyword=大疆` → 命中品牌表 `brand_name`。
  - `search_by=invalid_field` → 回落到 `item_name`。
- `list_filtered_items`
  - `search_by=item_name` + `keyword=xxx` → 命中商品名称。
  - `search_by=brand_raw` + `keyword=xxx` → 命中原品牌。
  - `search_by=brand_code`（不允许）→ 回落到 `item_name`。
  - 原本按 `matched_keyword` 搜索的路径已移除。

**前端**（本地目视 + 现有测试保持）

- 三个维度切换后 placeholder 变化、输入被清空、列表刷新。
- 干扰项 tab 下拉框只有两项；从其他 tab 带着 `brand_code` 维度切进来时自动回落。
- 搜索"大疆"或"DJI"在"入库品牌"维度下均能命中同一条 DJI 数据。

## 涉及文件

- [frontend/src/pages/Match/index.tsx](../../frontend/src/pages/Match/index.tsx)
- [backend/app/api/match_api.py](../../backend/app/api/match_api.py)
- [backend/app/api/rules_api.py](../../backend/app/api/rules_api.py)
- [backend/tests/test_match_api.py](../../backend/tests/) 或新建对应测试文件
- [backend/tests/test_rules_api.py](../../backend/tests/) 或新建对应测试文件
- [问题记录.md](../../问题记录.md) 追加"任务复核工作台搜索维度"章节

## 后续（不在本次范围）

- 若将来产品希望"多维度组合"或加"店铺"维度，可以把 `search_by` 从枚举改为多选数组，后端做 `or_(*conds)`；本次不实现。
- 若数据量增长导致 `ilike` 明显变慢，再考虑引入前缀索引或全文索引。
