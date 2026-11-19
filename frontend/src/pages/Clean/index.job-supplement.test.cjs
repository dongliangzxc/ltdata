const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const assert = require('node:assert/strict')
const ts = require('typescript')

const compile = source => ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.React, target: ts.ScriptTarget.ES2020 },
}).outputText
const helper = {}
vm.runInNewContext(compile(fs.readFileSync(path.join(__dirname, 'supplementTarget.ts'), 'utf8')), { exports: helper })
const { jobSupplementTarget } = helper
const job = {
  id: 123, category_code: 'action_cameras', platform: 'douyin', month: 202608,
  task_name: '运动相机 / douyin / 202608', status: 'reviewing', row_out: 13,
  confirmed_count: 5, publishable_count: 10, pending_count: 2,
  source_scope: { months: [202608] },
}
const expected = { id: 123, task_name: job.task_name, category_code: 'action_cameras', platform: 'douyin', month: 202608 }
for (const status of ['reviewing', 'done', 'published']) {
  assert.deepEqual(JSON.parse(JSON.stringify(jobSupplementTarget({ ...job, status }))), expected,
    'manual/published results and pending review rows must not block supplement upload')
}
assert.equal(jobSupplementTarget({ ...job, category_code: null, dispatch_category_code: 'action_cameras' }).category_code, 'action_cameras')
for (const status of ['queued', 'created', 'cleaning', 'matching', 'processing', 'failed', 'error', 'archived']) {
  assert.equal(jobSupplementTarget({ ...job, status }), null)
}
for (const field of ['id', 'category_code', 'platform', 'month']) {
  assert.equal(jobSupplementTarget({ ...job, [field]: null }), null)
}
assert.equal(jobSupplementTarget({ ...job, source_scope: { months: [202608, 202609] } }), null)

const page = fs.readFileSync(path.join(__dirname, 'index.tsx'), 'utf8')
const columns = {}
const source = page.slice(page.indexOf('const jobColumns ='), page.indexOf('const getMonthlyQueueRowKey ='))
const React = { createElement: (type, props, ...children) => ({ type, props: props ?? {}, children }) }
const icons = Object.fromEntries(['UploadOutlined', 'AimOutlined', 'LineChartOutlined', 'TagsOutlined', 'EyeOutlined', 'FileSearchOutlined', 'DeleteOutlined'].map(icon => [icon, icon]))
vm.runInNewContext(compile(`${source}\nexports.columns = jobColumns`), {
  exports: columns, React, ...icons, Space: 'Space', Button: 'Button', Popconfirm: 'Popconfirm',
  jobSupplementTarget, processingStatuses: new Set(['queued', 'created', 'cleaning', 'matching', 'processing']),
  formatText: value => value, formatPlatform: value => value, formatNumber: value => value,
})
let selected = null
const noop = () => {}
function render(view, row, uploading = false) {
  const cols = columns.columns(noop, noop, noop, noop, noop, view, noop, noop, target => { selected = target }, uploading)
  return cols.at(-1).render(null, row)
}
const cell = render('active', job)
const button = cell.children[0]
assert.equal(button.children[0], '补充数据', 'existing task list must put supplement first so it is visible')
assert.equal(button.props.disabled, false)
button.props.onClick()
assert.deepEqual(JSON.parse(JSON.stringify(selected)), expected, 'upload must target the selected job even if absent from monthly pool')
assert.equal(render('archived', job).children[0], false, 'deleted tab must not expose upload')
assert.equal(render('active', job, true).children[0].props.disabled, true)
for (const status of ['queued', 'failed']) {
  const unavailable = render('active', { ...job, status }).children[0]
  assert.equal(unavailable.props.disabled, true)
  selected = null
  unavailable.props.onClick()
  assert.equal(selected, null)
}
const table = page.slice(page.indexOf('columns={jobColumns('), page.indexOf('title={supplementJob'))
assert.match(table, /openSupplement,\s+supplementing,/)
