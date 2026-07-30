const fs = require('node:fs')
const path = require('node:path')
const assert = require('node:assert/strict')

const pageSource = fs.readFileSync(path.join(__dirname, 'index.tsx'), 'utf8')
const apiSource = fs.readFileSync(path.join(__dirname, '../../services/api.ts'), 'utf8')

assert.match(apiSource, /category_permissions:\s*string\[\]/, 'user profile should include category permission codes')
assert.match(apiSource, /category_permissions\?:\s*string\[\]/, 'user create/update payloads should accept category permission codes')

assert.match(pageSource, /useCategoryOptions/, 'users page should load existing categories for category permissions')
assert.match(pageSource, /category_permissions\?:\s*string\[\]/, 'user form should include category permissions')
assert.match(pageSource, /title:\s*'品类权限'/, 'users table should show a category permissions column')
assert.match(pageSource, /name="category_permissions"/, 'user form should render a category permissions field')
assert.match(pageSource, /mode="multiple"/, 'category permissions field should allow multiple categories')
assert.match(pageSource, /categoryOptions/, 'category permissions field should use category options')
assert.match(pageSource, /category_permissions:\s*values\.category_permissions/, 'save payload should submit category permissions')
