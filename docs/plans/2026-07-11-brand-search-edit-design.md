# Brand Search and Edit Design

## Context

The Brand Management page currently lists brand master data from `GET /api/brands`, including brand code, original uploaded brand name, editable brand name, category coverage, model count, and alias count. The page already supports creating brands and managing aliases from expanded rows.

This change adds two focused capabilities:

1. Search the visible brand list.
2. Edit only the normalized display name stored in `brands.brand_name`.

## Scope

In scope:

- Add a search input to the Brand Management page header area.
- Search by brand code, original uploaded brand name, and edited brand name.
- Add an edit action for each brand row.
- Add a backend PATCH endpoint to update `brands.brand_name` only.
- Refresh the brand list after a successful edit.
- Add frontend and backend tests for search and edit behavior.

Out of scope:

- Editing `brand_code`.
- Editing `brands.original_brand_name`.
- Searching aliases.
- Searching categories.
- Adding server-side pagination.
- Changing alias management behavior.

## UX Design

The Brand Management page keeps the existing table and create-brand button.

The header area gains a search input with placeholder text:

`搜索品牌码 / 上传时品牌名称 / 修改后名称`

The table gains an Operation column with an Edit button. Clicking Edit opens a modal titled `修改品牌名称`. The modal has one field:

- `修改后名称`

Saving trims surrounding whitespace. An empty value is allowed and is sent as `null`, so the list can fall back to existing display behavior.

After save succeeds, the modal closes and the brand list refreshes.

## Frontend Design

`frontend/src/pages/Brands/index.tsx` will keep using `listBrands()` to fetch all brands.

Search filtering is client-side because the current page already loads the full list and the confirmed search scope is limited to fields already present in `BrandItem`:

- `brand_code`
- `original_brand_name`
- `brand_name`

The filtering should be case-insensitive for Latin text and should work for Chinese text by direct substring matching.

The page will add local state for:

- search keyword
- edit modal open state
- currently edited brand
- edit form saving state

`frontend/src/services/api.ts` will add:

- `updateBrand(brandCode, payload)` calling `PATCH /brands/{brand_code}`

## Backend Design

`backend/app/api/brands_api.py` will add a PATCH endpoint:

`PATCH /api/brands/{brand_code}`

Request body:

```json
{
  "brand_name": "索尼"
}
```

Behavior:

- Look up `BrandRecord` by `brand_code`.
- Return 404 if it does not exist.
- Trim `brand_name` when provided.
- Store empty string as `None`.
- Do not update `brand_code`.
- Do not update `original_brand_name`.
- Commit and return the same `BrandOut` shape used by the list API, with model count, alias count, and category codes populated for that brand.

To avoid duplicating response assembly logic, extract a small helper that builds `BrandOut` values for one or more brands using the same aggregation rules as `list_brands`.

## Data Flow

Search flow:

1. Page loads brands with `listBrands()`.
2. User types into search input.
3. Frontend filters the in-memory list.
4. Table renders filtered rows.

Edit flow:

1. User clicks Edit on a brand row.
2. Modal opens with current `brand_name` value.
3. User saves.
4. Frontend calls `PATCH /api/brands/{brand_code}`.
5. Backend updates `BrandRecord.brand_name` only.
6. Frontend refreshes `listBrands()` and closes the modal.

## Error Handling

Frontend:

- Show existing global API error messages through the axios interceptor.
- Keep the edit modal open if save fails.
- Disable duplicate saves while the update request is running.

Backend:

- Return 404 with `品牌不存在` for unknown brand codes.
- Reuse existing FastAPI validation for malformed payloads.

## Testing

Backend tests:

- PATCH updates `brand_name` for an existing brand.
- PATCH trims whitespace.
- PATCH stores blank value as `None`.
- PATCH does not change `original_brand_name`.
- PATCH unknown brand returns 404.

Frontend tests or focused component checks:

- Search filters by brand code.
- Search filters by original uploaded brand name.
- Search filters by edited brand name.
- Edit modal sends only `brand_name` and refreshes list after success.

## Confirmed Requirements

- Search scope is limited to brand code, original uploaded brand name, and edited brand name.
- Edit scope is limited to `brands.brand_name`, shown as `修改后名称`.
- Brand code and original uploaded brand name are not editable in this change.
