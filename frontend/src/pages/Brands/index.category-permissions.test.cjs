const fs = require('node:fs')
const path = require('node:path')
const assert = require('node:assert/strict')

const source = fs.readFileSync(path.join(__dirname, 'index.tsx'), 'utf8')

// 品牌管理为全局功能：品类筛选与标签使用全部品类，不再按用户品类权限过滤品牌
assert.match(source, /useCategoryOptions\(\)/, 'brands page should load category options')
assert.match(source, /options=\{categoryOptions\}/, 'brand category filter should use all categories')
assert.match(source, /for \(const c of categoryOptions\)/, 'brand category labels should use all categories')
assert.doesNotMatch(source, /visibleCategoryOptions/, 'brands page should not filter categories by user permission')