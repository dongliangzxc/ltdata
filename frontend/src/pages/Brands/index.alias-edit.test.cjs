const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const esbuild = require('esbuild')

const filePath = path.join(__dirname, 'index.tsx')
const source = fs.readFileSync(filePath, 'utf8')
const { code } = esbuild.transformSync(source, {
  loader: 'tsx',
  format: 'cjs',
  target: 'es2020',
  jsx: 'automatic',
})

assert.ok(code.length > 0)
assert.match(source, /updateBrandAliasForCode/)
assert.match(source, /修改品牌名称/)
assert.match(source, /品牌别名/)
assert.match(source, /brand_alias_name/)
assert.doesNotMatch(source, /primary_alias_name/)
assert.doesNotMatch(source, /brand_alias_id/)
assert.doesNotMatch(source, /source: 'brand_form'/)
assert.match(source, /alias_name: trimmedAliasName/)
assert.match(source, /brandPage\?\.items/)
assert.match(source, /category_code: selectedCategoryCode/)
assert.match(source, /page_size: pageSize/)
assert.doesNotMatch(source, /filteredBrands/)
assert.match(source, /编辑/)
assert.match(source, /添加别名/)
assert.match(source, /删除/)

console.log('Brand alias edit source assertions passed')
