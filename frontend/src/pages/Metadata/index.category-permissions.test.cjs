const fs = require('node:fs')
const path = require('node:path')
const assert = require('node:assert/strict')

const source = fs.readFileSync(path.join(__dirname, 'index.tsx'), 'utf8')

assert.match(source, /localStorage\.getItem\('auth_user'\)/, 'metadata page should read the cached auth user')
assert.match(source, /category_permissions/, 'metadata page should inspect category permissions')
assert.match(source, /visibleCategoryOptions/, 'metadata page should derive a visible category option list')
assert.match(source, /options=\{visibleCategoryOptions\}/, 'search should use the filtered category options')
assert.match(source, /Form\.Item label="品类码"[\s\S]*options=\{visibleCategoryOptions\}/, 'edit form should use the filtered category options')
