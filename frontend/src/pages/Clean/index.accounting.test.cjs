const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const assert = require('node:assert/strict')
const ts = require('typescript')
const source = fs.readFileSync(path.join(__dirname, 'cleanAccounting.ts'), 'utf8')
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 } })
const exported = {}
vm.runInNewContext(compiled.outputText, { exports: exported })
const { formatCleanAccounting, formatDuplicateBasis } = exported
const base = { input_count: 100, retained_count: 90, filtered_count: 7, duplicate_count: 3, audit_complete: true, difference: 0, status: 'balanced' }
const balanced = formatCleanAccounting(base)
assert.equal(balanced.type, 'success')
assert.equal(balanced.message, '输入 100 条 = 保留 90 条 + 过滤 7 条 + 重复 3 条')
assert.match(balanced.description, /不包含已恢复/)
const legacy = formatCleanAccounting({ ...base, duplicate_count: 1, audit_complete: false, difference: null, status: 'legacy' })
assert.equal(legacy.type, 'info')
assert.match(legacy.message, /已记录重复 1 条/)
assert.doesNotMatch(legacy.message, / = /, 'incomplete history must not pretend to reconcile')
assert.match(legacy.description, /不根据差额推算/)
for (const status of ['processing', 'failed']) {
  const result = formatCleanAccounting({ ...base, status })
  assert.notEqual(result.type, 'success', 'partial execution must not claim a balanced finished task')
  assert.doesNotMatch(result.message, / = /)
  assert.match(result.description, /已提交结果/)
}
assert.match(formatCleanAccounting({ ...base, status: 'mismatch', difference: 2 }).description, /还有 2 条未对上/)
assert.match(formatCleanAccounting({ ...base, status: 'mismatch', difference: -2 }).description, /比输入多 2 条/)
const exact = { dedup_basis: 'item_id_month_shop', dedup_key: { item_id: ' AbC ', month: 202603, shop_name: null } }
const before = JSON.stringify(exact)
assert.equal(formatDuplicateBasis(exact), '商品ID " AbC "、月份 202603、店铺 （空） 完全相同')
assert.equal(JSON.stringify(exact), before, 'display must preserve exact dedup key values')
assert.equal(formatDuplicateBasis({}), '去重依据未记录')
