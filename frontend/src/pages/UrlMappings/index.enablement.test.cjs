const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const ts = require('typescript')

const moduleUnderTest = { exports: {} }
const compiled = ts.transpileModule(fs.readFileSync(path.join(__dirname, 'filters.ts'), 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText
new Function('exports', compiled)(moduleUnderTest.exports)
const { buildUrlMappingFilters, buildUrlMappingDeleteScope, describeUrlMappingFilters } = moduleUnderTest.exports

// Disabled=false is a meaningful query value, and must survive list/count/bulk scopes.
const filters = buildUrlMappingFilters({
  category_code: 'camera', platform: 'jd', start_month: 202512, end_month: 202601, enabled: false,
})
const scope = buildUrlMappingDeleteScope(filters, { all: true, ids: [1, 21] })
assert.equal(scope.enabled, false)
assert.equal(scope.start_month, 202512)
assert.equal(scope.end_month, 202601)
assert.deepEqual(scope.exclude_ids, [1, 21])
assert.equal(Object.isFrozen(scope), true)
assert.deepEqual(describeUrlMappingFilters(scope).slice(-2), [
  ['确认月份范围', '2025-12 至 2026-01'], ['状态', '已禁用'],
])
assert.equal(describeUrlMappingFilters(scope).some(([label]) => label === '年份' || label === '月份'), false,
  'A selected month range should not be described alongside unrestricted legacy year/month filters')

const enabled = buildUrlMappingFilters({ category_code: 'headphone', enabled: true })
assert.equal(enabled.enabled, true)
assert.equal(describeUrlMappingFilters(enabled).at(-1)[1], '已启用')
const unrestricted = buildUrlMappingFilters({ category_code: 'camera' })
assert.equal(Object.hasOwn(unrestricted, 'enabled'), false)
assert.equal(Object.hasOwn(unrestricted, 'start_month'), false)
assert.equal(Object.hasOwn(unrestricted, 'end_month'), false)
assert.deepEqual(buildUrlMappingDeleteScope(filters, { all: false, ids: [] }).include_ids, [])

console.log('URL mapping month/status scope tests passed')
