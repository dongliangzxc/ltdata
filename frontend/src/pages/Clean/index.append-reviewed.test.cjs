const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const ts = require('typescript')
const assert = require('node:assert/strict')
const page = fs.readFileSync(path.join(__dirname, 'index.tsx'), 'utf8')
const start = page.indexOf('const getMonthlyQueueRowKey =')
const end = page.indexOf('const buildPreviewCols =', start)
const source = `${page.slice(start, end)}\nexports.action = getQueueAction; exports.columns = monthlyQueueColumns;`
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.React, target: ts.ScriptTarget.ES2020 },
}).outputText
const exported = {}
vm.runInNewContext(compiled, {
  exports: exported,
  React: { createElement: (type, props, ...children) => ({ type, props: props ?? {}, children }) },
  Button: 'Button', formatPlatform: value => value, formatText: value => value, formatNumber: value => value,
  processingStatuses: new Set(['queued', 'created', 'cleaning', 'matching', 'processing']),
  appendableStatuses: new Set(['reviewing', 'done', 'published']),
})
const router = {
  category_code: 'router', platform: 'douyin', month: 202610,
  dispatched_count: 1874, queued_count: 1855, pending_count: 19,
  existing_job_id: 293, existing_job_status: 'reviewing', has_reviewed_or_published: true,
}
let selected
for (const status of ['reviewing', 'done', 'published']) {
  const row = { ...router, existing_job_status: status }
  assert.equal(exported.action(row).action, 'appended')
  const button = exported.columns(value => { selected = value }, null, false).at(-1).render(null, row)
  assert.equal(button.children[0], '追加到任务', 'reviewed/published tasks with new rows retain an append action')
  assert.equal(button.props.disabled, false)
  assert.match(button.props.title, /只处理.*新增数据/)
  button.props.onClick()
  assert.equal(selected, row)
}
for (const status of ['queued', 'cleaning', 'matching']) {
  const row = { ...router, existing_job_status: status }
  assert.equal(exported.action(row).disabled, true)
}
assert.equal(exported.action({ ...router, existing_job_status: 'archived' }).action, 'rebuild',
  'archived reviewed tasks must retain their explicit rebuild warning')
assert.equal(exported.columns(() => {}, null, true).at(-1).render(null, router).props.disabled, true)
