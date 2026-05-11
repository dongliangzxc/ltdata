# P7 — 品类感知强化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 补全 6 处缺失的品类筛选/字段，支持多分析师按品类隔离操作数据。

**Architecture:** 后端 3 处改动（migration + 2 个 API 新增 category_code 过滤参数）；前端 5 处页面改动 + api.ts 类型更新，所有改动相互独立可并行。noise_words 表需要新增 category_code 列（Alembic migration），其余均为纯参数/UI 扩展。

**Tech Stack:** Python / FastAPI / SQLAlchemy / Alembic / React + Ant Design / TypeScript

---

## 涉及文件

| 文件 | 类型 |
|---|---|
| `backend/alembic/versions/p7a1b2c3d4e5_p7_noise_word_category.py` | 新建（migration） |
| `backend/app/models/schemas.py` | 修改（NoiseWord ORM 加列） |
| `backend/app/api/rules_api.py` | 修改（NoiseWordIn 加字段、create 存 category、list 修复过滤） |
| `backend/app/api/models_api.py` | 修改（list_models 加 category_code 过滤） |
| `backend/app/api/correction_rules_api.py` | 修改（list_rules 加 category_code 过滤） |
| `frontend/src/services/api.ts` | 修改（3 处类型/签名更新） |
| `frontend/src/pages/UrlMappings/index.tsx` | 修改（弹框加品类辅助 Select + 型号联动过滤） |
| `frontend/src/pages/Models/index.tsx` | 修改（工具栏加品类 Select） |
| `frontend/src/pages/Rules/index.tsx` | 修改（干扰词库新增表单加品类；修正规则列表+弹框加品类） |
| `frontend/src/pages/Match/index.tsx` | 修改（MissingAttrsTabContent 加品类 Select） |

---

### Task 1: 后端 — noise_words 表加 category_code 列

**Files:**
- Create: `backend/alembic/versions/p7a1b2c3d4e5_p7_noise_word_category.py`
- Modify: `backend/app/models/schemas.py`
- Modify: `backend/app/api/rules_api.py`

- [ ] **Step 1: 新建 Alembic migration 文件**

创建 `backend/alembic/versions/p7a1b2c3d4e5_p7_noise_word_category.py`，内容如下：

```python
"""P7 — add category_code to noise_words

Revision ID: p7a1b2c3d4e5
Revises: p4c3d4e5f6a7
Create Date: 2026-05-11
"""
from alembic import op
import sqlalchemy as sa

revision = 'p7a1b2c3d4e5'
down_revision = 'p4c3d4e5f6a7'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('noise_words',
        sa.Column('category_code', sa.String(50), nullable=True))
    op.create_index('ix_noise_words_category_code', 'noise_words', ['category_code'])


def downgrade():
    op.drop_index('ix_noise_words_category_code', table_name='noise_words')
    op.drop_column('noise_words', 'category_code')
```

- [ ] **Step 2: 修改 NoiseWord ORM**

打开 `backend/app/models/schemas.py`，找到 `NoiseWord` 类（约第 390 行），在 `created_at` 行之后添加 `category_code` 列：

```python
class NoiseWord(Base):
    __tablename__ = "noise_words"
    __table_args__ = (
        UniqueConstraint("keyword", "match_field", name="uq_noise_keyword_field"),
    )

    id          = Column(Integer, primary_key=True, index=True)
    keyword     = Column(String(200), nullable=False)
    match_field = Column(String(20),  default="item_name")
    is_active   = Column(SmallInteger, default=1)
    created_by  = Column(String(50))
    created_at  = Column(DateTime, default=datetime.utcnow)
    category_code = Column(String(50), nullable=True, index=True)  # 新增
```

- [ ] **Step 3: 修改 rules_api.py — NoiseWordIn 加字段**

打开 `backend/app/api/rules_api.py`，找到 `NoiseWordIn`（约第 32 行），修改为：

```python
class NoiseWordIn(BaseModel):
    keyword: str
    match_field: str = "item_name"  # item_name / shop_name / brand_raw
    category_code: Optional[str] = None
```

确认文件顶部已有 `from typing import Optional`（该文件已有此导入）。

- [ ] **Step 4: 修改 rules_api.py — create_noise_word 存 category_code**

找到 `create_noise_word` 函数中创建 `NoiseWord` 的行（约第 60 行），修改为：

```python
row = NoiseWord(
    keyword=body.keyword,
    match_field=body.match_field,
    category_code=body.category_code or None,
)
```

- [ ] **Step 5: 修改 rules_api.py — list_noise_words 修复实际过滤**

找到 `list_noise_words` 函数（约第 37 行），替换整个函数体：

```python
@router.get("/noise-words")
def list_noise_words(
    category_code: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    q = db.query(NoiseWord).order_by(NoiseWord.created_at.desc())
    if category_code:
        q = q.filter(NoiseWord.category_code == category_code)
    rows = q.all()
    return [
        {
            "id": r.id,
            "keyword": r.keyword,
            "match_field": r.match_field,
            "is_active": r.is_active,
            "created_at": r.created_at,
            "category_code": r.category_code,
        }
        for r in rows
    ]
```

- [ ] **Step 6: 验证 Python 语法无报错**

```bash
cd /Users/dongliang04/workspace/gitProject/luotu/backend
python -c "
from app.models.schemas import NoiseWord
from app.api.rules_api import router
print('OK')
"
```

期望：`OK`

- [ ] **Step 7: 运行测试确认无回归**

```bash
cd /Users/dongliang04/workspace/gitProject/luotu/backend
python -m pytest tests/ -x -q 2>&1 | tail -5
```

期望：所有现有测试通过（pass，0 errors）。若有失败先修复。

- [ ] **Step 8: 更新 sql/init.sql — noise_words 建表加 category_code 列**

打开 `sql/init.sql`，找到 `CREATE TABLE noise_words`，在 `created_at` 列之后加入 `category_code`：

```sql
  `category_code` varchar(50) DEFAULT NULL COMMENT '品类码，NULL=全局',
```

同时确认 Alembic 版本更新（`alembic_version` 的 INSERT/UPDATE 改为 `p7a1b2c3d4e5`）。

- [ ] **Step 9: 提交**

```bash
cd /Users/dongliang04/workspace/gitProject/luotu
git add backend/alembic/versions/p7a1b2c3d4e5_p7_noise_word_category.py
git add backend/app/models/schemas.py backend/app/api/rules_api.py sql/init.sql
git commit -m "feat(p7): add category_code column to noise_words + fix list filter"
```

---

### Task 2: 后端 — list_models 加 category_code 过滤

**Files:**
- Modify: `backend/app/api/models_api.py`

- [ ] **Step 1: 修改 list_models 函数**

打开 `backend/app/api/models_api.py`，找到 `list_models` 函数（约第 352 行），在现有参数之后加入 `category_code`，并在 count query 和 main query 两处各加过滤：

```python
@router.get("", response_model=PaginatedResponse)
def list_models(
    brand_code:    Optional[str] = Query(None),
    keyword:       Optional[str] = Query(None),
    category_code: Optional[str] = Query(None),   # 新增
    page:          int = Query(1, ge=1),
    page_size:     int = Query(20, ge=1, le=2000),
    db: Session = Depends(get_db),
):
    # count query
    cq = db.query(ModelRecord)
    if brand_code:
        cq = cq.filter(ModelRecord.brand_code.ilike(f"%{brand_code}%"))
    if keyword:
        cq = cq.filter(
            ModelRecord.model_name.ilike(f"%{keyword}%") |
            ModelRecord.model_code.ilike(f"%{keyword}%") |
            ModelRecord.brand_name.ilike(f"%{keyword}%")
        )
    if category_code:                                         # 新增
        cq = cq.filter(ModelRecord.category_code == category_code)
    total = cq.count()

    q = db.query(ModelRecord, Category).outerjoin(
        Category, ModelRecord.category_code == Category.code
    )
    if brand_code:
        q = q.filter(ModelRecord.brand_code.ilike(f"%{brand_code}%"))
    if keyword:
        q = q.filter(
            ModelRecord.model_name.ilike(f"%{keyword}%") |
            ModelRecord.model_code.ilike(f"%{keyword}%") |
            ModelRecord.brand_name.ilike(f"%{keyword}%")
        )
    if category_code:                                         # 新增
        q = q.filter(ModelRecord.category_code == category_code)
    rows = q.order_by(ModelRecord.brand_code, ModelRecord.model_code) \
            .offset((page - 1) * page_size).limit(page_size).all()
    # ... 后续 result 构建保持不变
```

- [ ] **Step 2: 验证**

```bash
cd /Users/dongliang04/workspace/gitProject/luotu/backend
python -c "from app.api.models_api import router; print('OK')"
```

期望：`OK`

- [ ] **Step 3: 提交**

```bash
cd /Users/dongliang04/workspace/gitProject/luotu
git add backend/app/api/models_api.py
git commit -m "feat(p7): list_models supports category_code filter"
```

---

### Task 3: 后端 — list_correction_rules 加 category_code 过滤

**Files:**
- Modify: `backend/app/api/correction_rules_api.py`

- [ ] **Step 1: 修改 list_rules 函数**

打开 `backend/app/api/correction_rules_api.py`，在文件顶部导入区加入缺少的导入（若还没有）：

```python
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
```

然后将 `list_rules` 函数改为：

```python
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

- [ ] **Step 2: 验证**

```bash
cd /Users/dongliang04/workspace/gitProject/luotu/backend
python -c "from app.api.correction_rules_api import router; print('OK')"
```

期望：`OK`

- [ ] **Step 3: 提交**

```bash
cd /Users/dongliang04/workspace/gitProject/luotu
git add backend/app/api/correction_rules_api.py
git commit -m "feat(p7): list_correction_rules supports category_code filter"
```

---

### Task 4: 前端 — api.ts 类型更新

**Files:**
- Modify: `frontend/src/services/api.ts`

- [ ] **Step 1: 更新 createNoiseWord 类型**

找到第 178 行：
```typescript
export const createNoiseWord = (payload: { keyword: string; match_field: string }) =>
  api.post('/rules/noise-words', payload)
```

改为：
```typescript
export const createNoiseWord = (payload: { keyword: string; match_field: string; category_code?: string | null }) =>
  api.post('/rules/noise-words', payload)
```

- [ ] **Step 2: 更新 listCorrectionRules 加 params 参数**

找到第 277 行：
```typescript
export const listCorrectionRules = () =>
  api.get('/correction-rules')
```

改为：
```typescript
export const listCorrectionRules = (params?: Record<string, unknown>) =>
  api.get('/correction-rules', { params })
```

- [ ] **Step 3: 更新 listMissingAttrs 第二参数类型**

找到第 252 行：
```typescript
export const listMissingAttrs = (clean_job_id: number, params?: Record<string, unknown>) =>
  api.get(`/match/${clean_job_id}/missing-attrs`, { params })
```

该函数已接受 `Record<string, unknown>`，无需修改函数本身。但需要确认 Match/index.tsx 调用时能传入 `category_name`，参数类型已兼容（`Record<string, unknown>` 接受任意 key）。**此步骤无需改动。**

- [ ] **Step 4: 验证 TypeScript 编译**

```bash
cd /Users/dongliang04/workspace/gitProject/luotu/frontend
npx tsc --noEmit 2>&1 | head -20
```

期望：无报错

- [ ] **Step 5: 提交**

```bash
cd /Users/dongliang04/workspace/gitProject/luotu
git add frontend/src/services/api.ts
git commit -m "feat(p7): api.ts updates createNoiseWord and listCorrectionRules types"
```

---

### Task 5: 前端 — UrlMappings 弹框加品类辅助筛选联动型号

**Files:**
- Modify: `frontend/src/pages/UrlMappings/index.tsx`

- [ ] **Step 1: 更新 ModelOption 类型加 category_code**

找到文件顶部 `type ModelOption`（约第 29 行），添加 `category_code` 字段：

```typescript
type ModelOption = {
  id: number
  brand_code: string
  model_code: string
  brand_name: string | null
  model_name: string | null
  category_code: string | null   // 新增
}
```

- [ ] **Step 2: 导入 useCategoryOptions**

在文件顶部 import 区（约第 12 行附近）加入：

```typescript
import { useCategoryOptions } from '../../hooks/useCategoryOptions'
```

- [ ] **Step 3: 在组件内加 modalCategoryCode 状态 + categoryOptions**

在 `UrlMappingsPage` 函数内，在现有 `useState` 声明块附近（约第 58 行）加入：

```typescript
const [modalCategoryCode, setModalCategoryCode] = useState<string | undefined>()
const { options: categoryOptions } = useCategoryOptions()
```

- [ ] **Step 4: openCreate / openEdit 时重置 modalCategoryCode**

找到 `openCreate` 函数（约第 76 行），在 `setModalOpen(true)` 之前加：

```typescript
const openCreate = () => {
  setEditingId(null)
  form.resetFields()
  setModalCategoryCode(undefined)   // 新增
  setModalOpen(true)
}
```

找到 `openEdit` 函数（约第 82 行），在 `setModalOpen(true)` 之前加：

```typescript
const openEdit = (record: UrlMapping) => {
  setEditingId(record.id)
  form.setFieldsValue({
    platform: record.platform,
    item_id: record.item_id,
    item_url: record.item_url,
    model_id: record.model_id,
    price: record.price,
  })
  setModalCategoryCode(undefined)   // 新增
  setModalOpen(true)
}
```

- [ ] **Step 5: 计算 filteredModelOptions**

在 `columns` 定义之前（约第 136 行附近），加入：

```typescript
const filteredModelOptions = modalCategoryCode
  ? modelOptions.filter(m => m.category_code === modalCategoryCode)
  : modelOptions
```

- [ ] **Step 6: 在 Modal 内的 Form 最上方加品类 Select**

找到 Modal 内的 Form（约第 239 行）。在 `<Form.Item name="platform"` 之前插入品类辅助 Select（**不在 Form.Item 内，直接用 div 包裹**）：

```tsx
<Modal
  title={editingId ? '编辑映射' : '新增映射'}
  open={modalOpen}
  onOk={handleSave}
  onCancel={() => setModalOpen(false)}
  confirmLoading={saving}
  destroyOnClose
>
  <Form form={form} layout="vertical">
    {/* 品类辅助筛选，不提交 */}
    <div style={{ marginBottom: 16 }}>
      <div style={{ marginBottom: 4, fontSize: 14 }}>品类（筛选型号用）</div>
      <Select
        allowClear
        placeholder="选择品类可缩小型号列表"
        style={{ width: '100%' }}
        options={categoryOptions}
        value={modalCategoryCode}
        onChange={v => setModalCategoryCode(v)}
      />
    </div>
    <Form.Item name="platform" label="平台" rules={[{ required: true }]}>
      <Select options={PLATFORM_OPTIONS} />
    </Form.Item>
    <Form.Item name="item_id" label="item_id" rules={[{ required: true }]}>
      <Input placeholder="如：100045223280" />
    </Form.Item>
    <Form.Item name="item_url" label="商品 URL">
      <Input placeholder="https://item.jd.com/..." />
    </Form.Item>
    <Form.Item name="model_id" label="型号" rules={[{ required: true }]}>
      <Select
        showSearch
        placeholder="搜索品牌/型号码"
        filterOption={(input, option) =>
          (option?.label as string ?? '').toLowerCase().includes(input.toLowerCase())
        }
        options={filteredModelOptions.map(m => ({
          value: m.id,
          label: `[${m.brand_code}] ${m.model_code}${m.model_name ? ' ' + m.model_name : ''}`,
        }))}
      />
    </Form.Item>
    <Form.Item name="price" label="单价（元）">
      <InputNumber min={0} precision={2} style={{ width: '100%' }} />
    </Form.Item>
  </Form>
</Modal>
```

- [ ] **Step 7: 验证 TypeScript 编译**

```bash
cd /Users/dongliang04/workspace/gitProject/luotu/frontend
npx tsc --noEmit 2>&1 | head -20
```

期望：无报错

- [ ] **Step 8: 提交**

```bash
cd /Users/dongliang04/workspace/gitProject/luotu
git add frontend/src/pages/UrlMappings/index.tsx
git commit -m "feat(p7): url-mappings modal adds category helper to filter model dropdown"
```

---

### Task 6: 前端 — 型号管理列表加品类筛选

**Files:**
- Modify: `frontend/src/pages/Models/index.tsx`

- [ ] **Step 1: 导入 useCategoryOptions**

打开文件，在 import 区找到 `from '../../services/api'` 的那几行（约第 11 行），在其后加入：

```typescript
import { useCategoryOptions } from '../../hooks/useCategoryOptions'
```

- [ ] **Step 2: 在组件内初始化 categoryOptions**

在组件函数内，找到 `const [search, setSearch] = useState...` 附近（约第 58 行），加入：

```typescript
const { options: categoryOptions } = useCategoryOptions()
```

- [ ] **Step 3: 在工具栏品牌 Input 和关键词 Input 之间插入品类 Select**

找到工具栏 Row（约第 256 行），在品牌 Input 的 `<Col>` 和关键词 Input 的 `<Col>` 之间插入：

```tsx
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

完整工具栏变为：

```tsx
<Row gutter={12} style={{ marginBottom: 16 }} align="middle">
  <Col>
    <Input
      placeholder="搜索品牌"
      allowClear
      style={{ width: 140 }}
      onChange={e => { setSearch(p => ({ ...p, brand_code: e.target.value || undefined })); setPage(1) }}
    />
  </Col>
  <Col>
    <Select
      placeholder="品类筛选"
      allowClear
      style={{ width: 140 }}
      options={categoryOptions}
      onChange={v => { setSearch(p => ({ ...p, category_code: v || undefined })); setPage(1) }}
    />
  </Col>
  <Col>
    <Input
      placeholder="搜索型号/名称"
      allowClear
      style={{ width: 160 }}
      onChange={e => { setSearch(p => ({ ...p, keyword: e.target.value || undefined })); setPage(1) }}
    />
  </Col>
  <Col flex="auto" />
  <Col>
    <Space>
      <Upload beforeUpload={handleImport} showUploadList={false} accept=".xlsx,.xls">
        <Button icon={<UploadOutlined />} loading={previewing || importing}>Excel 导入</Button>
      </Upload>
      <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新增型号</Button>
    </Space>
  </Col>
</Row>
```

- [ ] **Step 4: 验证 TypeScript 编译**

```bash
cd /Users/dongliang04/workspace/gitProject/luotu/frontend
npx tsc --noEmit 2>&1 | head -20
```

期望：无报错

- [ ] **Step 5: 提交**

```bash
cd /Users/dongliang04/workspace/gitProject/luotu
git add frontend/src/pages/Models/index.tsx
git commit -m "feat(p7): models list adds optional category filter"
```

---

### Task 7: 前端 — Rules 页：干扰词库新增表单加品类 + 修正规则列表+弹框加品类

**Files:**
- Modify: `frontend/src/pages/Rules/index.tsx`

#### Part A: 干扰词库 NoiseWordTab

- [ ] **Step 1: 在 NoiseWordTab 加新增时的品类状态**

找到 `NoiseWordTab` 函数内的 state 声明区（约第 32 行），在 `categoryCode` state 之后加入：

```typescript
const [addCategoryCode, setAddCategoryCode] = useState<string | undefined>()
```

- [ ] **Step 2: handleAdd 携带 category_code**

找到 `handleAdd` 函数（约第 47 行），将 `createNoiseWord` 调用改为：

```typescript
await createNoiseWord({
  keyword: keyword.trim(),
  match_field: matchField,
  category_code: addCategoryCode || null,
})
```

在 `setKeyword('')` 之后加入：

```typescript
setAddCategoryCode(undefined)
```

- [ ] **Step 3: 新增表单 Space 中加品类 Select**

找到工具栏 `<Space wrap>` 内的「添加」按钮（约第 67 行），在「添加」Button 之后（品类筛选 Select 之前）插入：

```tsx
<Select
  placeholder="指定品类（可选）"
  allowClear
  style={{ width: 140 }}
  options={categoryOptions}
  value={addCategoryCode}
  onChange={v => setAddCategoryCode(v)}
/>
```

完整新增区 Space 变为：

```tsx
<Space wrap>
  <Input placeholder="输入干扰关键词" value={keyword} onChange={e => setKeyword(e.target.value)}
    onPressEnter={handleAdd} style={{ width: 220 }} />
  <Select value={matchField} onChange={setMatchField} style={{ width: 130 }}
    options={[
      { value: 'item_name', label: '商品名称' },
      { value: 'shop_name', label: '店铺名称' },
      { value: 'brand_raw', label: '原始品牌' },
    ]} />
  <Select
    placeholder="指定品类（可选）"
    allowClear
    style={{ width: 140 }}
    options={categoryOptions}
    value={addCategoryCode}
    onChange={v => setAddCategoryCode(v)}
  />
  <Button type="primary" icon={<PlusOutlined />} loading={adding} onClick={handleAdd}>添加</Button>
  <Select
    placeholder="品类筛选"
    allowClear
    style={{ width: 140 }}
    options={categoryOptions}
    onChange={v => setCategoryCode(v)}
  />
</Space>
```

#### Part B: 修正规则 CorrectionRulesTab

- [ ] **Step 4: CorrectionRulesTab 加 filterCategory 状态和 categoryOptions**

找到 `CorrectionRulesTab` 函数内的 state 声明区（约第 461 行），在 `[form]` 之后加入：

```typescript
const [filterCategory, setFilterCategory] = useState<string | undefined>()
const { options: categoryOptions } = useCategoryOptions()
```

- [ ] **Step 5: useRequest 改为带 category_code 的参数**

找到 `useRequest` 调用（约第 466 行），修改为：

```typescript
const { data, loading, refresh } = useRequest(
  () => listCorrectionRules(filterCategory ? { category_code: filterCategory } : undefined).then(r => r.data),
  { refreshDeps: [filterCategory] }
)
```

- [ ] **Step 6: 工具栏「新增规则」按钮旁加品类筛选 Select**

找到 `return` 块内的 `<Button type="primary" ... >新增规则</Button>`（约第 570 行），改为：

```tsx
<Space wrap>
  <Select
    placeholder="品类筛选"
    allowClear
    style={{ width: 160 }}
    options={categoryOptions}
    onChange={v => setFilterCategory(v)}
  />
  <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新增规则</Button>
</Space>
```

- [ ] **Step 7: 弹框 category_code 字段从 Input 改为 Select**

找到 Modal 内 Form.Item `category_code`（约第 593 行），将控件从 Input 改为 Select：

```tsx
<Form.Item label="品类（留空=全局）" name="category_code">
  <Select
    allowClear
    placeholder="选择品类（留空=全局生效）"
    options={[{ value: '', label: '全局（不限品类）' }, ...categoryOptions]}
  />
</Form.Item>
```

- [ ] **Step 8: 验证 TypeScript 编译**

```bash
cd /Users/dongliang04/workspace/gitProject/luotu/frontend
npx tsc --noEmit 2>&1 | head -20
```

期望：无报错

- [ ] **Step 9: 提交**

```bash
cd /Users/dongliang04/workspace/gitProject/luotu
git add frontend/src/pages/Rules/index.tsx
git commit -m "feat(p7): rules page — noise-word add form + correction-rules list/modal add category"
```

---

### Task 8: 前端 — Match 未补属性 Tab 加品类筛选

**Files:**
- Modify: `frontend/src/pages/Match/index.tsx`

- [ ] **Step 1: MissingAttrsTabContent 加 filterCategory 状态和 categoryOptions**

找到 `MissingAttrsTabContent` 函数内的 state 声明（约第 87 行），在 `[applying, setApplying]` 之后加入：

```typescript
const [filterCategory, setFilterCategory] = useState<string | undefined>()
const { options: categoryOptions } = useCategoryOptions()
```

- [ ] **Step 2: useRequest 加入 category_name 参数**

找到 `useRequest` 调用（约第 92 行），修改为：

```typescript
const { data, loading, refresh } = useRequest(
  () => listMissingAttrs(cleanJobId, {
    page,
    page_size: 20,
    ...(filterCategory ? { category_name: filterCategory } : {}),
  }).then(r => r.data),
  { refreshDeps: [cleanJobId, page, filterCategory] }
)
```

- [ ] **Step 3: filterCategory 变化时重置 page**

在 `const [filterCategory, setFilterCategory]` 之后无需单独 effect，直接在 onChange 里重置即可（见 Step 4）。

- [ ] **Step 4: 在 Alert 和 Table 之间加品类 Select**

找到 `return` 块（约第 107 行），在 `<Alert ...>` 之后、`<Table ...>` 之前插入：

```tsx
<Select
  placeholder="品类筛选"
  allowClear
  style={{ width: 180 }}
  options={categoryOptions}
  onChange={v => { setFilterCategory(v); setPage(1) }}
/>
```

完整 return 块变为：

```tsx
return (
  <Space direction="vertical" size={12} style={{ width: '100%' }}>
    <Alert
      type="warning"
      showIcon
      message="以下商品型号已确认，但未匹配到属性规则。建议先前往「规则管理 → 属性规则」补充规则后重跑，或手动前往型号管理补充规格。"
      action={
        <Space>
          <Button size="small" onClick={() => window.open('/rules?tab=attr', '_blank')}>
            前往属性规则
          </Button>
          <Button size="small" type="primary" loading={applying} onClick={handleApply}>
            重跑属性规则
          </Button>
        </Space>
      }
    />
    <Select
      placeholder="品类筛选"
      allowClear
      style={{ width: 180 }}
      options={categoryOptions}
      onChange={v => { setFilterCategory(v); setPage(1) }}
    />
    <Table
      dataSource={data?.items ?? []}
      columns={columns}
      rowKey="id"
      size="small"
      loading={loading}
      pagination={{
        current: page,
        pageSize: 20,
        total: data?.total ?? 0,
        onChange: setPage,
        showTotal: (t: number) => `共 ${t} 条`,
      }}
    />
  </Space>
)
```

- [ ] **Step 5: 验证 TypeScript 编译**

```bash
cd /Users/dongliang04/workspace/gitProject/luotu/frontend
npx tsc --noEmit 2>&1 | head -20
```

期望：无报错

- [ ] **Step 6: 提交**

```bash
cd /Users/dongliang04/workspace/gitProject/luotu
git add frontend/src/pages/Match/index.tsx
git commit -m "feat(p7): match missing-attrs tab adds category filter"
```
