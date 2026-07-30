const fs = require('node:fs')
const path = require('node:path')
const assert = require('node:assert/strict')

const pageSource = fs.readFileSync(path.join(__dirname, 'index.tsx'), 'utf8')
const layoutSource = fs.readFileSync(path.join(__dirname, '../../components/Layout/index.tsx'), 'utf8')

assert.match(
  layoutSource,
  /permission: 'data_management'/,
  'data_management should continue to gate the Upload and Dispatch entry points',
)
assert.match(
  pageSource,
  /category_permissions/,
  'Dispatch should read category permissions from the authenticated user',
)
assert.match(
  pageSource,
  /visibleCategories/,
  'Dispatch should derive a visible category list before rendering category-scoped UI',
)
assert.match(
  pageSource,
  /safe empty state|暂无可用品类|无可用品类/,
  'Dispatch should render a safe empty state when there are no permitted categories',
)
assert.match(
  pageSource,
  /visibleCategoryCodes\.has\(row\.category_code\)/,
  'Dispatch should suppress unauthorized category actions with the visible category set',
)
assert.match(
  pageSource,
  /visibleStatsRules\.filter\(rule => rule\.category_code === category\.category_code\)/,
  'Dispatch should only expand stats rows for permitted categories',
)
