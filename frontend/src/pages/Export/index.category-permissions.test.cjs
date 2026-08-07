const fs = require('node:fs')
const path = require('node:path')
const assert = require('node:assert/strict')

const source = fs.readFileSync(path.join(__dirname, 'index.tsx'), 'utf8')

assert.match(source, /localStorage\.getItem\('auth_user'\)/, 'export page should read the cached auth user')
assert.match(source, /category_permissions/, 'export page should inspect category permissions')
assert.match(source, /visibleCategories/, 'export page should derive visible categories')
assert.match(source, /categoryOptions/, 'export page should build category options from visible categories')
