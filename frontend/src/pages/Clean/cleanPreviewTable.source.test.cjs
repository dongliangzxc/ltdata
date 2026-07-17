const fs = require('node:fs')
const path = require('node:path')
const assert = require('node:assert/strict')

const sourcePath = path.join(__dirname, 'cleanPreviewTable.tsx')
assert.ok(fs.existsSync(sourcePath), 'shared clean preview table module should exist')

const source = fs.readFileSync(sourcePath, 'utf8')

assert.match(source, /export type CleanPreviewRow/, 'shared module should export CleanPreviewRow')
assert.match(source, /export type CleanPreviewResponse/, 'shared module should export CleanPreviewResponse')
assert.match(source, /export type TaggedCleanPreviewResponse/, 'shared module should export TaggedCleanPreviewResponse')
assert.match(source, /export const cleanPreviewColumns/, 'shared module should export cleanPreviewColumns')
assert.match(source, /标准品牌/, 'shared columns should include 标准品牌')
assert.match(source, /商品名称/, 'shared columns should include 商品名称')
assert.match(source, /sales_amount/, 'shared columns should include sales_amount')
