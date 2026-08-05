const fs = require('node:fs')
const path = require('node:path')
const assert = require('node:assert/strict')

const source = fs.readFileSync(path.join(__dirname, 'index.tsx'), 'utf8')

assert.match(source, /localStorage\.getItem\('auth_user'\)/, 'url mappings page should read the cached auth user')
assert.match(source, /category_permissions/, 'url mappings page should inspect category permissions')
assert.match(source, /visibleCategoryOptions/, 'url mappings page should derive visible category options')
assert.match(source, /options=\{visibleCategoryOptions\}/, 'category filter should use filtered category options')
assert.match(source, /visibleModelOptions/, 'model options should be filtered by visible category permissions')
