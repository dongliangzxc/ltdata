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
assert.match(source, /修改品牌别名/)
assert.match(source, /编辑/)
assert.match(source, /alias_name/)
assert.match(source, /添加别名/)
assert.match(source, /删除/)

console.log('Brand alias edit source assertions passed')
