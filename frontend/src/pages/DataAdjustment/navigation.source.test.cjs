const fs = require('node:fs')
const path = require('node:path')
const assert = require('node:assert/strict')

const root = path.resolve(__dirname, '../..')
const appSource = fs.readFileSync(path.join(root, 'App.tsx'), 'utf8')
const layoutSource = fs.readFileSync(path.join(root, 'components/Layout/index.tsx'), 'utf8')
const permissionsSource = fs.readFileSync(path.join(root, 'auth/permissions.ts'), 'utf8')

assert.match(appSource, /DataAdjustmentPage/, 'App should import and render DataAdjustmentPage')
assert.match(appSource, /path="\/data-adjustment"/, 'App should register /data-adjustment route')

const cleanIndex = layoutSource.indexOf("key: '/clean'")
const adjustmentIndex = layoutSource.indexOf("key: '/data-adjustment'")
const matchResultsIndex = layoutSource.indexOf("key: '/match-results'")
assert.ok(cleanIndex >= 0, 'Layout should contain clean menu item')
assert.ok(adjustmentIndex > cleanIndex, 'Layout should place data adjustment after clean menu item')
assert.ok(matchResultsIndex > adjustmentIndex, 'Layout should place data adjustment before match results')
assert.match(layoutSource, /label: '数据调整'/, 'Layout should label the menu item 数据调整')

assert.match(
  permissionsSource,
  /\['\/data-adjustment',\s*'processing_workbench'\]/,
  'permissions should map /data-adjustment to processing_workbench'
)
