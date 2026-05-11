# P7 — 品类感知强化 Design Spec

**Goal:** 补全系统中 6 处缺失的品类筛选/字段，支持多分析师按品类隔离操作数据。

**Background:** 平台由多名分析师共同维护，每人负责不同品类。现有各页面已有品类筛选，但以下 6 处仍有缺口，影响多人协作效率。

---

## 改动范围

| # | 位置 | 改动类型 | 说明 |
|---|---|---|---|
| 1 | URL映射 新增/编辑弹框 | 纯前端 | 弹框内加辅助「品类」Select，联动过滤型号下拉（不作为提交字段） |
| 2 | 型号管理 列表 | 前端 + 后端 | 工具栏加可选品类筛选；后端 GET /api/models 加 category_code 参数 |
| 3 | 规则 > 干扰词库 新增表单 | 前端 + 后端 | 新增表单加可选品类字段；后端 POST /api/rules/noise-words 确认支持 category_code |
| 4 | 规则 > 修正规则 列表 | 前端 + 后端 | 工具栏加可选品类筛选；后端 GET /api/correction-rules 加 category_code 参数 |
| 5 | 规则 > 修正规则 弹框 | 纯前端 | category_code 字段从 Input 改为 useCategoryOptions 的 Select |
| 6 | Match > 未补属性 Tab | 前端 + 后端 | MissingAttrsTabContent 内加品类 Select；后端确认/添加 category_name 过滤支持 |

---

## 详细设计

### #1 URL映射弹框 — 品类辅助筛选联动型号

**交互：**
- 弹框顶部加一个「品类（筛选型号用）」Select，`allowClear`，使用 `useCategoryOptions`
- 该字段**不加入 Form**，单独用 `useState` 管理（不提交到后端）
- 型号 Select 的 `options` 根据选中品类过滤：

```tsx
// 弹框内新增状态
const [modalCategoryCode, setModalCategoryCode] = useState<string | undefined>()

// 每次弹框关闭/打开时重置
// openCreate / openEdit 时：setModalCategoryCode(undefined)

// 型号选项过滤
const filteredModelOptions = modalCategoryCode
  ? modelOptions.filter(m => m.category_code === modalCategoryCode)
  : modelOptions
```

- `ModelOption` 类型需补充 `category_code: string | null` 字段（后端 /api/models 已返回此字段）
- 品类 Select 放在 Form 最上方（modal_id Form.Item 之前），label 为「品类（筛选型号用）」，不设 Form.Item name

**文件：** `frontend/src/pages/UrlMappings/index.tsx`

---

### #2 型号管理列表 — 品类筛选

**后端：** `backend/app/api/models_api.py`，`list_models` 函数加参数：

```python
category_code: Optional[str] = Query(None),
```

在 count query 和 main query 中各加过滤条件：

```python
if category_code:
    cq = cq.filter(ModelRecord.category_code == category_code)
# ...
if category_code:
    q = q.filter(ModelRecord.category_code == category_code)
```

**前端：** `frontend/src/pages/Models/index.tsx`

- 在 `search` state 中加入 `category_code` key（已是 `Record<string, string | undefined>`，无需改 type）
- 工具栏品牌 Input 和关键词 Input 之间插入品类 Select：

```tsx
const { options: categoryOptions } = useCategoryOptions()

// 工具栏加
<Col>
  <Select
    placeholder="品类筛选"
    allowClear
    style={{ width: 140 }}
    options={categoryOptions}
    onChange={v => { setSearch(p => ({ ...p, category_code: v || undefined })); setPage(1) }}
  />
</Col>
```

- 导入 `useCategoryOptions`

---

### #3 干扰词库新增表单 — 加品类字段

**背景：** `noise_words` 表目前没有 `category_code` 列（P3 的筛选是 no-op）。需要补 Alembic migration 添加该列，同时修复 `list_noise_words` 的过滤逻辑。

**后端：** `backend/app/api/rules_api.py` + `backend/app/models/schemas.py` + 新 Alembic migration

1. 新增 Alembic migration（revision: `p7a1b2c3d4e5`，down_revision: `p4c3d4e5f6a7`）：
```python
op.add_column('noise_words', sa.Column('category_code', sa.String(50), nullable=True))
```

2. `NoiseWord` ORM 添加字段：
```python
category_code = Column(String(50), nullable=True, index=True)
```

3. `NoiseWordIn` schema 添加：
```python
category_code: Optional[str] = None
```

4. `create_noise_word` 存储 `category_code`：
```python
row = NoiseWord(keyword=body.keyword, match_field=body.match_field, category_code=body.category_code or None)
```

5. `list_noise_words` 修复实际过滤（现在是 no-op）：
```python
rows = db.query(NoiseWord).order_by(NoiseWord.created_at.desc())
if category_code:
    rows = rows.filter(NoiseWord.category_code == category_code)
rows = rows.all()
# 返回时改为 "category_code": r.category_code
```

**前端：** `frontend/src/pages/Rules/index.tsx` — `NoiseWordTab`

- 新增状态：`const [addCategoryCode, setAddCategoryCode] = useState<string | undefined>()`
- 工具栏「添加」按钮旁加品类 Select（`useCategoryOptions` 已有，复用已有 `categoryOptions`）
- `handleAdd` 提交时携带 `category_code: addCategoryCode || null`
- 添加成功后 `setAddCategoryCode(undefined)` 重置
- `api.ts` 的 `createNoiseWord` 类型从 `{ keyword: string; match_field: string }` 改为 `{ keyword: string; match_field: string; category_code?: string | null }`

---

### #4 修正规则列表 — 品类筛选

**后端：** `backend/app/api/correction_rules_api.py`，`list_rules` 函数：

```python
from typing import Optional
from fastapi import Query

@router.get("", response_model=list[CorrectionRuleOut])
def list_rules(
    category_code: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    q = db.query(CorrectionRule).order_by(CorrectionRule.priority, CorrectionRule.id)
    if category_code:
        q = q.filter(CorrectionRule.category_code == category_code)
    return q.all()
```

**前端：** `frontend/src/pages/Rules/index.tsx` — `CorrectionRulesTab`

- 新增状态：`const [filterCategory, setFilterCategory] = useState<string | undefined>()`
- 新增：`const { options: categoryOptions } = useCategoryOptions()`
- `useRequest` 改为：

```tsx
const { data, loading, refresh } = useRequest(
  () => listCorrectionRules(filterCategory ? { category_code: filterCategory } : undefined).then(r => r.data),
  { refreshDeps: [filterCategory] }
)
```

- 工具栏「新增规则」按钮旁加品类 Select（allowClear）
- `api.ts` 的 `listCorrectionRules` 改为：

```ts
export const listCorrectionRules = (params?: Record<string, unknown>) =>
  api.get('/correction-rules', { params })
```

---

### #5 修正规则弹框 — category_code 改为 Select

**前端：** `frontend/src/pages/Rules/index.tsx` — `CorrectionRulesTab` Modal

将 Form.Item `category_code` 的控件从：

```tsx
<Input placeholder="如：TV（留空表示不限品类）" />
```

改为：

```tsx
<Select
  allowClear
  placeholder="选择品类（留空=全局）"
  options={[{ value: '', label: '全局（不限品类）' }, ...categoryOptions]}
/>
```

同时 `handleSubmit` 中已有 `category_code: vals.category_code || null` 的处理，保持不变。

---

### #6 Match > 未补属性 Tab — 品类筛选

**后端：** 已支持。`list_missing_attrs`（`match_api.py` 第 252 行）已有 `category_name: Optional[str] = Query(None)` 参数，无需改动。

**前端：** `frontend/src/pages/Match/index.tsx` — `MissingAttrsTabContent`

组件内自管理品类状态，加 Select 筛选器：

```tsx
function MissingAttrsTabContent({ cleanJobId, onApplyDone }) {
  const [page, setPage] = useState(1)
  const [filterCategory, setFilterCategory] = useState<string | undefined>()
  const { options: categoryOptions } = useCategoryOptions()
  // ...
  const { data, loading, refresh } = useRequest(
    () => listMissingAttrs(cleanJobId, {
      page, page_size: 20,
      ...(filterCategory ? { category_name: filterCategory } : {}),
    }).then(r => r.data),
    { refreshDeps: [cleanJobId, page, filterCategory] }
  )
  // ...
  // Table 上方加 Select
  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      <Alert ... />
      <Select
        placeholder="品类筛选"
        allowClear
        style={{ width: 160 }}
        options={categoryOptions}
        onChange={v => { setFilterCategory(v); setPage(1) }}
      />
      <Table ... />
    </Space>
  )
}
```

`api.ts` 的 `listMissingAttrs` 第二参数类型加 `category_name?: string`。

---

## 文件变更清单

### 后端（需修改）

| 文件 | 改动 |
|---|---|
| `backend/alembic/versions/p7a1b2c3d4e5_category_awareness.py` | 新增 migration：noise_words 表加 category_code 列 |
| `backend/app/models/schemas.py` | `NoiseWord` ORM 加 `category_code` 列；`NoiseWordIn` 加 `category_code` 字段 |
| `backend/app/api/models_api.py` | `list_models` 加 `category_code: Optional[str]` Query 参数及过滤 |
| `backend/app/api/correction_rules_api.py` | `list_rules` 加 `category_code: Optional[str]` Query 参数及过滤 |
| `backend/app/api/rules_api.py` | `create_noise_word` 存储 `category_code`；修复 `list_noise_words` 实际过滤 |

### 前端（需修改）

| 文件 | 改动 |
|---|---|
| `frontend/src/services/api.ts` | `createNoiseWord` 类型加 `category_code`；`listCorrectionRules` 加 params；`listMissingAttrs` 类型加 `category_name` |
| `frontend/src/pages/UrlMappings/index.tsx` | 弹框加品类辅助 Select，`ModelOption` 加 `category_code`，型号过滤逻辑 |
| `frontend/src/pages/Models/index.tsx` | 工具栏加品类 Select，search state 加 category_code |
| `frontend/src/pages/Rules/index.tsx` | NoiseWordTab 新增表单加品类；CorrectionRulesTab 列表加品类筛选+弹框改 Select |
| `frontend/src/pages/Match/index.tsx` | MissingAttrsTabContent 加品类 Select 筛选器 |

---

## 不在本次范围内

- 规则 > 品牌写法库：无品类概念，不涉及
- 规则 > 匹配规则：规则本身无品类约束字段，不涉及
- 规则 > 干扰项存档：只读归档，不涉及
- 工作台 / 导出：已有品类筛选，不涉及
