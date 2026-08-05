const fs = require('node:fs')
const path = require('node:path')
const assert = require('node:assert/strict')

const source = fs.readFileSync(path.join(__dirname, 'index.tsx'), 'utf8')

assert.match(source, /localStorage\.getItem\('auth_user'\)/, 'brands page should read the cached auth user')
assert.match(source, /category_permissions/, 'brands page should inspect category permissions')
assert.match(source, /visibleCategoryOptions/, 'brands page should derive a visible category option list')
assert.match(source, /options=\{visibleCategoryOptions\}/, 'brand category filter should use filtered category options')
assert.match(source, /for \(const c of visibleCategoryOptions\)/, 'brand category labels should use filtered category options')
