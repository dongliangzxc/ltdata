# Brand Search and Edit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Brand Management search across brand code/original name/edited name and allow editing only `brands.brand_name`.

**Architecture:** Keep brand search client-side because the page already fetches the full brand list and the confirmed search scope only uses fields already present in `BrandItem`. Add a focused backend PATCH endpoint for persistent name edits, reusing the existing `BrandOut` response shape so the frontend can refresh cleanly.

**Tech Stack:** FastAPI, SQLAlchemy ORM, Pydantic, pytest, React, TypeScript, Ant Design, ahooks.

## Global Constraints

- Search scope is limited to brand code, original uploaded brand name, and edited brand name.
- Edit scope is limited to `brands.brand_name`, shown as `修改后名称`.
- Do not edit `brand_code`.
- Do not edit `brands.original_brand_name`.
- Empty edited name is allowed and must be stored as `None`.
- Do not add server-side pagination or alias/category search in this change.
- Follow existing file patterns in `backend/app/api/brands_api.py`, `backend/tests/test_brands_api.py`, `frontend/src/pages/Brands/index.tsx`, and `frontend/src/services/api.ts`.
- Preserve unrelated working tree changes in `backend/app/services/data_cleaner.py`, `backend/tests/test_data_cleaner.py`, and other currently modified frontend pages.

---

## File Structure

- Modify `backend/app/api/brands_api.py`
  - Add `BrandUpdate` request model.
  - Extract brand response assembly into `_build_brand_outs(db, brands)`.
  - Keep `list_brands()` behavior unchanged by delegating to the helper.
  - Add `PATCH /api/brands/{brand_code}` to update `BrandRecord.brand_name` only.

- Modify `backend/tests/test_brands_api.py`
  - Add focused PATCH endpoint tests.
  - Use the existing `client_and_db` fixture.

- Modify `frontend/src/services/api.ts`
  - Add `UpdateBrandPayload` type.
  - Add `updateBrand(brandCode, payload)` service function.

- Modify `frontend/src/pages/Brands/index.tsx`
  - Add local search keyword state and filtered brand list.
  - Add edit modal state and save handler.
  - Add an Operation column with Edit button.
  - Use `filteredBrands` as table data.

---

### Task 1: Backend Brand Update API

**Files:**
- Modify: `backend/tests/test_brands_api.py`
- Modify: `backend/app/api/brands_api.py`

**Interfaces:**
- Consumes: existing `BrandRecord`, `ModelRecord`, `BrandAlias`, `BrandOut`, `get_db`, and `router`.
- Produces: `PATCH /api/brands/{brand_code}` accepting `{ "brand_name": string | null }` and returning `BrandOut`.
- Produces helper: `_build_brand_outs(db: Session, brands: list[BrandRecord]) -> list[BrandOut]`.

- [ ] **Step 1: Add failing backend tests for successful update, trimming, blank-as-null, immutable original name, and 404**

Append these tests to `backend/tests/test_brands_api.py`:

```python
def test_update_brand_name_changes_only_edited_name(client_and_db):
    client, db = client_and_db
    brand = BrandRecord(
        brand_code="SONY",
        brand_name="索尼旧名",
        original_brand_name="Sony Upload",
    )
    db.add(brand)
    db.add(ModelRecord(brand_code="SONY", model_code="A1", brand_name="索尼型号", category_code="camera"))
    db.add(BrandAlias(alias_name="Sony", brand_code="SONY"))
    db.commit()

    resp = client.patch("/brands/SONY", json={"brand_name": " 索尼新名 "})

    assert resp.status_code == 200
    body = resp.json()
    assert body["brand_code"] == "SONY"
    assert body["brand_name"] == "索尼新名"
    assert body["original_brand_name"] == "Sony Upload"
    assert body["model_count"] == 1
    assert body["alias_count"] == 1
    assert db.query(BrandRecord).filter_by(brand_code="SONY").one().brand_name == "索尼新名"
    assert db.query(BrandRecord).filter_by(brand_code="SONY").one().original_brand_name == "Sony Upload"


def test_update_brand_name_stores_blank_as_none(client_and_db):
    client, db = client_and_db
    db.add(BrandRecord(brand_code="BOSE", brand_name="Bose", original_brand_name="Bose Upload"))
    db.commit()

    resp = client.patch("/brands/BOSE", json={"brand_name": "   "})

    assert resp.status_code == 200
    assert resp.json()["brand_name"] is None
    assert db.query(BrandRecord).filter_by(brand_code="BOSE").one().brand_name is None


def test_update_brand_name_returns_404_for_missing_brand(client_and_db):
    client, _db = client_and_db

    resp = client.patch("/brands/MISSING", json={"brand_name": "Missing"})

    assert resp.status_code == 404
    assert resp.json()["detail"] == "品牌不存在"
```

- [ ] **Step 2: Run backend tests and verify they fail because PATCH endpoint is missing**

Run:

```bash
cd backend && pytest tests/test_brands_api.py::test_update_brand_name_changes_only_edited_name tests/test_brands_api.py::test_update_brand_name_stores_blank_as_none tests/test_brands_api.py::test_update_brand_name_returns_404_for_missing_brand -q --tb=short
```

Expected: failures with HTTP 405 Method Not Allowed or 404 for the PATCH route.

- [ ] **Step 3: Add request model and response helper in `backend/app/api/brands_api.py`**

In `backend/app/api/brands_api.py`, add this model after `BrandAliasCreate`:

```python
class BrandUpdate(BaseModel):
    brand_name: str | None = None
```

Replace the body of `list_brands()` by extracting its aggregation into a helper. The helper should live above `list_brands()`:

```python
def _build_brand_outs(db: Session, brands: list[BrandRecord]) -> list[BrandOut]:
    normalized_brand_code = func.trim(ModelRecord.brand_code)
    model_counts: dict[str, int] = dict(
        db.query(normalized_brand_code, func.count(ModelRecord.id))
        .filter(ModelRecord.brand_code.isnot(None))
        .group_by(normalized_brand_code)
        .all()
    )
    alias_counts: dict[str, int] = dict(
        db.query(BrandAlias.brand_code, func.count(BrandAlias.id))
        .group_by(BrandAlias.brand_code)
        .all()
    )
    model_brand_names: dict[str, str] = {}
    category_map: dict[str, set[str]] = {}
    for brand_code, brand_name, category_code in (
        db.query(normalized_brand_code, ModelRecord.brand_name, ModelRecord.category_code)
        .filter(ModelRecord.brand_code.isnot(None))
        .all()
    ):
        if not brand_code:
            continue
        if brand_name and brand_code not in model_brand_names:
            model_brand_names[brand_code] = brand_name
        if category_code:
            category_map.setdefault(brand_code, set()).add(category_code)
    category_codes_by_brand = {
        code: sorted(codes)
        for code, codes in category_map.items()
    }

    return [
        BrandOut(
            brand_code=brand.brand_code,
            brand_name=_first_text(brand.brand_name, model_brand_names.get(brand.brand_code)),
            original_brand_name=_first_text(brand.original_brand_name, brand.brand_name, model_brand_names.get(brand.brand_code)),
            category_codes=category_codes_by_brand.get(brand.brand_code, []),
            model_count=model_counts.get(brand.brand_code, 0),
            alias_count=alias_counts.get(brand.brand_code, 0),
        )
        for brand in brands
    ]
```

Then make `list_brands()` use it:

```python
@router.get("", response_model=list[BrandOut])
def list_brands(db: Session = Depends(get_db)):
    """返回品牌主数据列表，附带型号数、别名数、覆盖品类。"""
    brands = db.query(BrandRecord).order_by(BrandRecord.brand_code).all()
    return _build_brand_outs(db, brands)
```

- [ ] **Step 4: Add PATCH endpoint in `backend/app/api/brands_api.py`**

Add this endpoint after `create_brand()` and before alias routes:

```python
@router.patch("/{brand_code}", response_model=BrandOut)
def update_brand(brand_code: str, payload: BrandUpdate, db: Session = Depends(get_db)):
    brand = db.query(BrandRecord).filter(BrandRecord.brand_code == brand_code).first()
    if not brand:
        raise HTTPException(status_code=404, detail="品牌不存在")

    cleaned_name = payload.brand_name.strip() if payload.brand_name is not None else None
    brand.brand_name = cleaned_name or None
    db.commit()
    db.refresh(brand)
    return _build_brand_outs(db, [brand])[0]
```

- [ ] **Step 5: Run backend tests and verify they pass**

Run:

```bash
cd backend && pytest tests/test_brands_api.py -q --tb=short
```

Expected: all tests in `test_brands_api.py` pass.

- [ ] **Step 6: Commit backend API changes**

Run:

```bash
git add backend/app/api/brands_api.py backend/tests/test_brands_api.py
git commit -m "feat: add brand name update api" -m "Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: Frontend Brand Search and Edit UI

**Files:**
- Modify: `frontend/src/services/api.ts`
- Modify: `frontend/src/pages/Brands/index.tsx`

**Interfaces:**
- Consumes: `PATCH /api/brands/{brand_code}` from Task 1.
- Produces: `updateBrand(brandCode: string, payload: UpdateBrandPayload)` service function.
- Produces UI behavior: search filters table data by `brand_code`, `original_brand_name`, and `brand_name`; edit modal updates `brand_name` only.

- [ ] **Step 1: Add API service types and function**

In `frontend/src/services/api.ts`, add this type after `CreateBrandPayload`:

```ts
export type UpdateBrandPayload = {
  brand_name?: string | null
}
```

Add this function after `createBrand`:

```ts
export const updateBrand = (brandCode: string, payload: UpdateBrandPayload) =>
  api.patch<BrandItem>(`/brands/${encodeURIComponent(brandCode)}`, payload)
```

- [ ] **Step 2: Update Brand page imports**

In `frontend/src/pages/Brands/index.tsx`, update icon imports:

```ts
import { PlusOutlined, DeleteOutlined, EditOutlined } from '@ant-design/icons'
```

Update service imports:

```ts
import {
  listBrands, listBrandAliasesByCode, createBrandAliasForCode, deleteBrandAliasById,
  updateBrand,
  type BrandItem, type BrandAliasItem,
} from '../../services/api'
```

- [ ] **Step 3: Add local state and helper functions inside `BrandsPage`**

Inside `BrandsPage`, after `const [createOpen, setCreateOpen] = useState(false)`, add:

```ts
  const [searchText, setSearchText] = useState('')
  const [editOpen, setEditOpen] = useState(false)
  const [editingBrand, setEditingBrand] = useState<BrandItem | null>(null)
  const [editSaving, setEditSaving] = useState(false)
  const [editForm] = Form.useForm<{ brand_name: string }>()
```

After `renderOptionalText`, add:

```ts
  const filteredBrands = useMemo(() => {
    const keyword = searchText.trim().toLowerCase()
    if (!keyword) return brands || []
    return (brands || []).filter((brand) => {
      const fields = [brand.brand_code, brand.original_brand_name, brand.brand_name]
      return fields.some(value => (value || '').toLowerCase().includes(keyword))
    })
  }, [brands, searchText])

  const openEdit = (brand: BrandItem) => {
    setEditingBrand(brand)
    editForm.setFieldsValue({ brand_name: brand.brand_name || '' })
    setEditOpen(true)
  }

  const closeEdit = () => {
    setEditOpen(false)
    setEditingBrand(null)
    editForm.resetFields()
  }

  const handleEditSave = async () => {
    if (!editingBrand) return
    const values = await editForm.validateFields()
    const trimmedName = values.brand_name?.trim() || ''
    setEditSaving(true)
    try {
      await updateBrand(editingBrand.brand_code, { brand_name: trimmedName || null })
      message.success('品牌名称已更新')
      closeEdit()
      refresh()
    } finally {
      setEditSaving(false)
    }
  }
```

- [ ] **Step 4: Add Operation column**

Append this column object to the `columns` array in `BrandsPage`:

```tsx
    {
      title: '操作',
      key: 'actions',
      width: 120,
      render: (_: unknown, record: BrandItem) => (
        <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(record)}>
          编辑
        </Button>
      ),
    },
```

- [ ] **Step 5: Add search input to the page header**

Replace the current card title prop:

```tsx
<Card
  title="品牌管理"
  extra={<Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>新建品牌</Button>}
>
```

with:

```tsx
<Card
  title={(
    <Space direction="vertical" size={8} style={{ width: '100%' }}>
      <span>品牌管理</span>
      <Input.Search
        allowClear
        placeholder="搜索品牌码 / 上传时品牌名称 / 修改后名称"
        value={searchText}
        onChange={e => setSearchText(e.target.value)}
        style={{ maxWidth: 420 }}
      />
    </Space>
  )}
  extra={<Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>新建品牌</Button>}
>
```

- [ ] **Step 6: Use filtered table data**

Change the table `dataSource` from:

```tsx
dataSource={brands || []}
```

to:

```tsx
dataSource={filteredBrands}
```

- [ ] **Step 7: Add edit modal next to the existing create modal**

After the existing `CreateBrandModal`, add:

```tsx
      <Modal
        title="修改品牌名称"
        open={editOpen}
        onOk={handleEditSave}
        confirmLoading={editSaving}
        onCancel={closeEdit}
        okText="保存"
        cancelText="取消"
      >
        <Form form={editForm} layout="vertical">
          <Form.Item label="品牌码">
            <Input value={editingBrand?.brand_code || ''} disabled />
          </Form.Item>
          <Form.Item name="brand_name" label="修改后名称">
            <Input placeholder="留空则恢复默认显示" />
          </Form.Item>
        </Form>
      </Modal>
```

- [ ] **Step 8: Run frontend type check/build**

Run:

```bash
cd frontend && npm run build
```

Expected: TypeScript and Vite build complete successfully.

- [ ] **Step 9: Commit frontend changes**

Run:

```bash
git add frontend/src/services/api.ts frontend/src/pages/Brands/index.tsx
git commit -m "feat: add brand search and edit UI" -m "Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: Final Verification

**Files:**
- No new files.
- Verify changes from Tasks 1 and 2.

**Interfaces:**
- Consumes: backend PATCH endpoint and frontend UI integration.
- Produces: verified implementation ready for deployment.

- [ ] **Step 1: Run focused backend tests**

Run:

```bash
cd backend && pytest tests/test_brands_api.py -q --tb=short
```

Expected: all brand API tests pass.

- [ ] **Step 2: Run frontend production build**

Run:

```bash
cd frontend && npm run build
```

Expected: build succeeds.

- [ ] **Step 3: Check git status excludes unrelated existing edits**

Run:

```bash
git status --short
```

Expected: commits from this plan are cleanly recorded. Existing unrelated local edits may remain, especially `backend/app/services/data_cleaner.py`, `backend/tests/test_data_cleaner.py`, `frontend/src/pages/Clean/index.tsx`, `frontend/src/pages/Match/index.tsx`, and `frontend/src/pages/Models/index.tsx`; do not revert them.

- [ ] **Step 4: Summarize implementation**

Report:

```text
Implemented brand search and edit:
- Backend PATCH /api/brands/{brand_code} updates only brand_name.
- Frontend search filters brand_code, original_brand_name, and brand_name.
- Frontend edit modal updates 修改后名称 and refreshes the list.
Verification:
- backend brand tests passed.
- frontend build passed.
Unrelated existing working tree changes were left untouched.
```

---

## Self-Review

Spec coverage:

- Search input in Brand Management header: Task 2 Steps 3, 5, 6.
- Search by brand code, original uploaded brand name, edited brand name: Task 2 Step 3.
- Edit action and modal: Task 2 Steps 4 and 7.
- Backend PATCH endpoint updating only `brand_name`: Task 1 Steps 1, 3, 4.
- Refresh after save: Task 2 Step 3.
- Backend tests: Task 1 Steps 1, 2, 5.
- Frontend build verification: Task 2 Step 8 and Task 3 Step 2.
- No brand code/original name/category/alias search edits: covered by Global Constraints and endpoint payload.

Placeholder scan:

- No TBD, TODO, placeholder implementation, or unspecified test instructions remain.

Type consistency:

- `BrandUpdate.brand_name` maps to `UpdateBrandPayload.brand_name`.
- `updateBrand(brandCode, payload)` consumes the Task 1 PATCH endpoint.
- `BrandItem` properties used in filtering already exist: `brand_code`, `original_brand_name`, `brand_name`.
