const fs = require('node:fs')
const path = require('node:path')
const assert = require('node:assert/strict')

const source = fs.readFileSync(path.join(__dirname, 'CreateModelModal.tsx'), 'utf8')

assert.notEqual(source.indexOf('const loadBrands = async (keyword?: string)'), -1, 'brand loader should accept a search keyword')
assert.notEqual(source.indexOf('keyword: keyword?.trim() || undefined'), -1, 'brand loader should pass search keyword to listBrands')
assert.notEqual(source.indexOf('onSearch={loadBrands}'), -1, 'brand Select should search brands remotely')
assert.notEqual(source.indexOf('filterOption={false}'), -1, 'brand Select should not rely on local filtering of a capped brand list')
