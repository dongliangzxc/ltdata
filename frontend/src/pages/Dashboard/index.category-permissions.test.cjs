const fs = require('node:fs')
const path = require('node:path')
const assert = require('node:assert/strict')

const source = fs.readFileSync(path.join(__dirname, 'index.tsx'), 'utf8')

assert.match(source, /localStorage\.getItem\('auth_user'\)/, 'dashboard should read the cached auth user')
assert.match(source, /category_permissions/, 'dashboard should inspect category permissions')
assert.match(source, /visibleCategories/, 'dashboard should derive visible categories')
assert.match(source, /categoryOptions/, 'dashboard should build category options from visible categories')
