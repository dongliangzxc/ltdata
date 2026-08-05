const fs = require('node:fs')
const path = require('node:path')
const assert = require('node:assert/strict')

const source = fs.readFileSync(path.join(__dirname, 'index.tsx'), 'utf8')

assert.match(source, /localStorage\.getItem\('auth_user'\)/, 'models page should read the cached auth user')
assert.match(source, /category_permissions/, 'models page should inspect category permissions')
assert.match(source, /visibleCategoryOptions/, 'models page should derive a visible category option list')
assert.match(source, /options=\{visibleCategoryOptions\}/, 'model filters and forms should use filtered category options')
assert.match(source, /CreateModelModal[\s\S]*categoryOptions=\{visibleCategoryOptions\}/, 'create model modal should receive filtered category options')
