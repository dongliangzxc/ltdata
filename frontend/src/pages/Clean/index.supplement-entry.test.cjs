const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const assert = require('node:assert/strict')
const ts = require('typescript')

const source = fs.readFileSync(path.join(__dirname, 'supplementTarget.ts'), 'utf8')
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } })
const exported = {}
vm.runInNewContext(compiled.outputText, { exports: exported })
const { monthlySupplementTarget } = exported
const row = {
  category_code: 'power_bank', category_name: '移动电源', platform: 'tmall', month: 202610,
  existing_job_id: 42, existing_job_name: '移动电源 / 天猫 / 202610',
  existing_job_status: 'done', pending_count: 0, queued_count: 6918,
}
for (const status of ['done', 'reviewing', 'published']) {
  const target = monthlySupplementTarget({ ...row, existing_job_status: status })
  assert.deepEqual(JSON.parse(JSON.stringify(target)), {
    id: 42, task_name: row.existing_job_name, category_code: 'power_bank', platform: 'tmall', month: 202610,
  }, 'zero pending rows and existing reviewed/published results must still allow supplements')
}
for (const status of ['queued', 'created', 'cleaning', 'matching', 'processing', 'failed', 'error', 'archived', null]) {
  assert.equal(monthlySupplementTarget({ ...row, existing_job_status: status }), null)
}
for (const field of ['existing_job_id', 'category_code', 'platform', 'month']) {
  assert.equal(monthlySupplementTarget({ ...row, [field]: null }), null, `missing ${field} must not open an upload`)
}

// Render the actual operation cell and invoke its action, without a browser.
const page = fs.readFileSync(path.join(__dirname, 'index.tsx'), 'utf8')
const columnsSource = page.slice(page.indexOf('const monthlyQueueColumns ='), page.indexOf('const buildPreviewCols ='))
const columnsCompiled = ts.transpileModule(`${columnsSource}\nexports.columns = monthlyQueueColumns`, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.React },
}).outputText
const columnsExports = {}
const React = { createElement: (type, props, ...children) => ({ type, props: props ?? {}, children }) }
vm.runInNewContext(columnsCompiled, {
  exports: columnsExports, React, Space: 'Space', Button: 'Button', UploadOutlined: 'UploadOutlined',
  monthlySupplementTarget, getQueueAction: () => ({ label: '重新清洗', disabled: false, action: 'recleaned' }),
  getMonthlyQueueRowKey: r => `${r.category_code}-${r.platform}-${r.month}`,
  formatPlatform: v => v, formatText: v => v, formatNumber: v => v,
})
let selected = null
const columns = columnsExports.columns(() => assert.fail('supplement must not re-clean'), target => { selected = target }, null, false)
const cell = columns.at(-1).render(null, row)
const button = cell.children[1]
assert.equal(button.children[0].trim(), '补充数据')
assert.equal(button.props.disabled, false)
button.props.onClick()
assert.equal(selected.id, 42)
assert.equal(selected.month, 202610)
for (const [candidate, busyKey, disabled] of [[{ ...row, existing_job_status: 'archived' }, null, false], [row, 'other-row', false], [row, null, true]]) {
  const cols = columnsExports.columns(() => {}, () => {}, busyKey, disabled)
  assert.equal(cols.at(-1).render(null, candidate).children[1].props.disabled, true)
}
assert.match(page, /monthlyQueueColumns\(handleUpsertMonthlyTask, openSupplement,/)
