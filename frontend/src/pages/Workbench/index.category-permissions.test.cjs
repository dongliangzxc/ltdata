const fs = require('node:fs')
const path = require('node:path')
const assert = require('node:assert/strict')

const source = fs.readFileSync(path.join(__dirname, 'index.tsx'), 'utf8')

assert.match(source, /localStorage\.getItem\('auth_user'\)/, 'workbench page should read the cached auth user')
assert.match(source, /category_permissions/, 'workbench page should inspect category permissions')
assert.match(source, /visibleCategoryOptions/, 'workbench page should derive visible category options')
assert.match(source, /options=\{visibleCategoryOptions\}/, 'workbench category selector should use filtered category options')
