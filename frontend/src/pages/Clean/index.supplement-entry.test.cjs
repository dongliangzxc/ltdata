const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const assert = require('node:assert/strict')
const ts = require('typescript')

const row = {
  category_code: 'power_bank', category_name: '移动电源', platform: 'tmall', month: 202610,
  existing_job_id: 42, existing_job_name: '移动电源 / 天猫 / 202610',
  existing_job_status: 'done', pending_count: 0, queued_count: 6918,
}
const page = fs.readFileSync(path.join(__dirname, 'index.tsx'), 'utf8')
const columnsSource = page.slice(page.indexOf('const monthlyQueueColumns ='), page.indexOf('const buildPreviewCols ='))
assert.doesNotMatch(columnsSource, /onSupplement|补充数据/, 'monthly pool must not expose a second supplement upload entry')
assert.equal((page.match(/>补充数据<\/Button>/g) ?? []).length, 1, 'only the existing task list should offer supplement upload')
const columnsCompiled = ts.transpileModule(`${columnsSource}\nexports.columns = monthlyQueueColumns`, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.React },
}).outputText
const columnsExports = {}
const React = { createElement: (type, props, ...children) => ({ type, props: props ?? {}, children }) }
vm.runInNewContext(columnsCompiled, {
  exports: columnsExports, React, Button: 'Button',
  getQueueAction: () => ({ label: '重新清洗', disabled: false, action: 'recleaned' }),
  getMonthlyQueueRowKey: r => `${r.category_code}-${r.platform}-${r.month}`,
  formatPlatform: v => v, formatText: v => v, formatNumber: v => v,
})
let selected = null
const columns = columnsExports.columns(candidate => { selected = candidate }, null, false)
const button = columns.at(-1).render(null, row)
assert.equal(button.type, 'Button', 'monthly operations should contain only the normal queue action')
assert.equal(button.children[0], '重新清洗')
assert.equal(button.props.disabled, false)
button.props.onClick()
assert.equal(selected, row, 'queue action must retain its original target')
for (const [busyKey, disabled] of [['other-row', false], [null, true]]) {
  const cols = columnsExports.columns(() => {}, busyKey, disabled)
  assert.equal(cols.at(-1).render(null, row).props.disabled, true)
}
const rowKey = `${row.category_code}-${row.platform}-${row.month}`
assert.equal(columnsExports.columns(() => {}, rowKey, false).at(-1).render(null, row).props.loading, true)
assert.match(page, /monthlyQueueColumns\(handleUpsertMonthlyTask, upsertingRowKey,/)
